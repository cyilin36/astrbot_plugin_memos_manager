from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

try:
    from .memos_client import MemosClient, MemosClientError
    from .tool_models import (
        build_timestamp_clause,
        combine_cel_clauses,
        map_date_field_to_cel,
        map_visibility_label_to_api,
        normalize_visibility_label,
        parse_date_bound,
        readable_visibilities,
        visibility_filter_clause,
    )
except ImportError:
    from memos_client import MemosClient, MemosClientError
    from tool_models import (
        build_timestamp_clause,
        combine_cel_clauses,
        map_date_field_to_cel,
        map_visibility_label_to_api,
        normalize_visibility_label,
        parse_date_bound,
        readable_visibilities,
        visibility_filter_clause,
    )


@register(
    "astrbot_plugin_memos_manager",
    "astrbot_plugin_memos_manager",
    "一个能对usememos/memos进行管理的插件",
    "2.1.0",
    "https://github.com/cyilin36/astrbot_plugin_memos_manager",
)
class MemosManagerPlugin(Star):
    """Memos 管理插件主类。

    说明：
    1) 负责读取配置、注册 LLM tools。
    2) 负责统一构建 Memos 客户端和审计日志。
    3) 负责工具级 UID 白名单鉴权。
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # 一次性迁移旧版配置：v1.2.0 及更早的 allowed_uids 是逗号分隔字符串，
        # 新版改用 AstrBot list 配置项。若存量配置仍是字符串，这里拆成真正的
        # UID 列表并写回配置文件，避免 WebUI 列表编辑器把字符串逐字拆成条目。
        self._migrate_allowed_uids_config()

        # 注册给 Agent 可自动调用的工具。
        tools = [
            MemosSearchTool(self),
            MemosCreateTool(self),
            MemosUpdateTool(self),
            MemosArchiveTool(self),
        ]
        if self._cfg_bool("enable_memos_delete_tool", False):
            tools.append(MemosDeleteTool(self))
        self.context.add_llm_tools(*tools)

    # ------------------------------
    # 配置读取与基础工具方法
    # ------------------------------

    def _cfg_str(self, key: str, default: str = "") -> str:
        """读取字符串配置，若类型不合法则回落默认值。"""
        value = self.config.get(key, default)
        return value if isinstance(value, str) else default

    def _cfg_int(self, key: str, default: int) -> int:
        """读取整数配置，并保证值为正数。"""
        value = self.config.get(key, default)
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except (TypeError, ValueError):
            return default

    def _cfg_bool(self, key: str, default: bool) -> bool:
        """读取布尔配置，兼容字符串形式。"""
        value = self.config.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return default

    def _trace_id(self) -> str:
        """生成短 trace id，方便日志链路追踪。"""
        return uuid.uuid4().hex[:10]

    def _local_tz(self):
        """获取本地时区；若异常回退 UTC。"""
        return datetime.now().astimezone().tzinfo or timezone.utc

    def _build_client(self) -> MemosClient:
        """基于当前配置构建 Memos 客户端。"""
        return MemosClient(
            base_url=self._cfg_str("memos_base_url"),
            token=self._cfg_str("memos_token"),
            timeout_seconds=20,
        )

    def _build_audit(
        self,
        trace_id: str,
        steps: list[str],
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """构建可返回给 LLM 的审计摘要。

        该摘要用于让 Agent 判断工具是否执行完成。
        为避免上下文膨胀，按配置限制字符长度。
        """
        if not self._cfg_bool("enable_ai_audit_log", True):
            return None
        max_chars = self._cfg_int("ai_audit_log_max_chars", 2000)
        joined = "\n".join(steps)
        if len(joined) > max_chars:
            joined = joined[:max_chars] + "..."
        payload: dict[str, Any] = {
            "trace_id": trace_id,
            "steps": joined,
        }
        if metrics:
            payload["metrics"] = metrics
        return payload

    # ------------------------------
    # UID 白名单鉴权
    # ------------------------------

    def _migrate_allowed_uids_config(self) -> None:
        """将旧版字符串格式的 allowed_uids 迁移为 list 并持久化。

        仅当存量配置仍是字符串时执行一次；拆分只按旧版的英文逗号分隔符，
        绝不对字符串逐字符拆分。迁移成功后写入配置文件，保证运行时与
        WebUI 列表编辑器拿到的都是真正的数组。
        """
        value = self.config.get("allowed_uids")
        if not isinstance(value, str) or not value.strip():
            return
        uids = [part.strip() for part in value.split(",") if part.strip()]
        if not uids:
            return
        self.config["allowed_uids"] = uids
        try:
            self.config.save_config()
            logger.info(
                "[memos_config] migrated allowed_uids to list, count=%d",
                len(uids),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "[memos_config] failed to persist allowed_uids migration: %s",
                exc,
            )

    def _parse_allowed_uids(self) -> set[str]:
        """读取白名单 UID。

        `allowed_uids` 是 AstrBot 内置的 list 配置项，用户在 WebUI 中
        逐条添加。此处采用与社区成熟插件一致的防御式读取：值若被误配成
        字符串，仅视为单个 UID；其他异常类型按空处理；绝不逐字符拆分。
        """
        raw = self.config.get("allowed_uids") or []
        if not isinstance(raw, (list, tuple, set)):
            raw = [raw] if isinstance(raw, str) and raw.strip() else []
        return {
            str(item).strip()
            for item in raw
            if item is not None and str(item).strip()
        }

    @staticmethod
    def _extract_uid_from_event(event: Any) -> str | None:
        """从事件对象提取用户 UID。

        优先从 message_obj.sender.user_id 获取；
        再尝试 event.get_sender_id()。
        """
        msg_obj = getattr(event, "message_obj", None)
        if msg_obj is not None:
            sender = getattr(msg_obj, "sender", None)
            # sender 可能是对象，也可能是 dict。
            if sender is not None:
                sender_uid = getattr(sender, "user_id", None)
                if sender_uid is None and isinstance(sender, dict):
                    sender_uid = sender.get("user_id")
                if sender_uid is not None:
                    return str(sender_uid)

        get_sender_id = getattr(event, "get_sender_id", None)
        if callable(get_sender_id):
            try:
                sender_uid = get_sender_id()
                if sender_uid is not None:
                    return str(sender_uid)
            except Exception:
                return None
        return None

    def _extract_uid_from_ctx(self, context: ContextWrapper[AstrAgentContext]) -> str | None:
        """从 tool 上下文提取 UID。

        依据 AstrBot 官方文档与插件实践，优先使用 context.context.event。
        该路径在 tool 调用阶段通常最稳定。
        """
        inner_ctx = getattr(context, "context", None)
        event = getattr(inner_ctx, "event", None)
        if event is not None:
            uid = self._extract_uid_from_event(event)
            if uid:
                return uid

        event = getattr(context, "event", None)
        if event is not None:
            uid = self._extract_uid_from_event(event)
            if uid:
                return uid

        run_ctx = getattr(context, "run_context", None)
        if run_ctx is not None:
            event = getattr(run_ctx, "event", None)
            if event is not None:
                uid = self._extract_uid_from_event(event)
                if uid:
                    return uid
        return None

    def _check_tool_permission(
        self,
        context: ContextWrapper[AstrAgentContext],
        tool_name: str,
    ) -> tuple[bool, str, str | None]:
        """统一进行工具调用权限校验。

        返回：
        - bool: 是否允许
        - str: 失败原因（仅内部描述）
        - str|None: 当前 UID
        """
        if not self._cfg_bool("enable_uid_auth", False):
            return True, "uid_auth_disabled", None

        uid = self._extract_uid_from_ctx(context)
        if not uid:
            return False, f"uid_missing_for_tool_{tool_name}", None
        uid = str(uid)

        allowed_uids = self._parse_allowed_uids()
        if not allowed_uids:
            return False, "allowed_uids_empty", uid

        if uid not in allowed_uids:
            return False, f"uid_not_allowed_for_tool_{tool_name}", uid

        return True, "uid_allowed", uid

    def _auth_denied_result(
        self,
        trace_id: str,
        tool_name: str,
        reason: str,
    ) -> dict[str, Any]:
        """生成统一的鉴权失败返回。

        注意：该返回不泄露 UID 等敏感字段。
        """
        steps = [
            f"auth_denied tool={tool_name}",
            f"reason={reason}",
        ]
        return {
            "ok": False,
            "trace_id": trace_id,
            "result": {},
            "audit": self._build_audit(trace_id, steps),
            "errors": ["当前用户无权限使用该工具"],
        }

    def _tool_input_error(self, trace_id: str, code: str, message: str) -> dict[str, Any]:
        """生成统一的输入参数错误返回。"""
        steps = [
            f"input_error code={code}",
            f"message={message}",
        ]
        return {
            "ok": False,
            "trace_id": trace_id,
            "result": {},
            "audit": self._build_audit(trace_id, steps),
            "errors": [message],
        }

    @staticmethod
    def _parse_optional_text(raw: Any) -> str | None:
        """解析可选文本参数，空白值归一为 None。"""
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    @staticmethod
    def _parse_date_field(raw: Any, default: str = "create_time") -> str:
        """解析日期字段，仅允许 create_time/update_time（display_time 为兼容别名）。"""
        text = str(raw or default).strip().lower()
        if text in {"display_time", "create_time", "update_time"}:
            return text
        return default

    @staticmethod
    def _parse_action(raw: Any, default: str = "set") -> str:
        """解析 archive action，仅允许 set/list_archived。"""
        text = str(raw or default).strip().lower()
        if text in {"set", "list_archived"}:
            return text
        return text

    @staticmethod
    def _parse_bool_with_default(raw: Any, default: bool) -> bool:
        """解析布尔参数，兼容字符串形式。"""
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw)

    @staticmethod
    def _require_name_for_set(raw: Any) -> tuple[bool, str]:
        """校验并提取 name 参数。"""
        name = str(raw or "").strip()
        if not name:
            return False, "name is required when action is set"
        return True, name

    # ------------------------------
    # 搜索相关方法
    # ------------------------------

    def _parse_date_bound(self, raw: str | None, *, is_end: bool) -> datetime | None:
        """解析日期上下界，返回 UTC datetime。

        具体解析与半开区间语义见 `tool_models.parse_date_bound`；
        这里注入本地时区，保证与既有行为一致。
        """
        return parse_date_bound(raw, is_end=is_end, tz=self._local_tz())

    @staticmethod
    def _memo_match_keyword(memo: dict[str, Any], query: str) -> bool:
        """在 content/snippet/tags 上做大小写无关匹配。"""
        q_cf = query.casefold()
        content = str(memo.get("content", ""))
        snippet = str(memo.get("snippet", ""))
        tags = memo.get("tags", [])
        tags_text = " ".join(tags) if isinstance(tags, list) else ""
        haystack = f"{content}\n{snippet}\n{tags_text}".casefold()
        return q_cf in haystack

    async def run_search(
        self,
        query: str | None,
        include_archived: bool = False,
        start_date: str | None = None,
        end_date: str | None = None,
        date_field: str = "create_time",
    ) -> dict[str, Any]:
        """执行 memos 搜索（Memos v0.31）。

        流程：
        1) 组装服务端 CEL：可见性 + 时间半开区间
        2) 服务端按 CEL 分页返回（固定 pageSize，避免 pageToken 失效）
        3) 插件侧关键词过滤 content/snippet/tags
        4) 可见性兜底校验并截断到 search_max_count
        """
        trace_id = self._trace_id()
        steps: list[str] = []
        search_max_count = self._cfg_int("search_max_count", 50)
        selected_date_field = self._parse_date_field(date_field)
        cel_field = map_date_field_to_cel(selected_date_field)
        configured_visibility = self._cfg_str("default_visibility", "workspace")
        allowed_visibilities = readable_visibilities(configured_visibility)
        steps.append(
            f"start memos_search trace={trace_id} query_present={bool(query and query.strip())} "
            f"include_archived={include_archived} search_max_count={search_max_count} "
            f"start_date={start_date!r} end_date={end_date!r} date_field={selected_date_field} "
            f"cel_field={cel_field}"
        )
        try:
            start_dt = self._parse_date_bound(start_date, is_end=False)
            end_dt = self._parse_date_bound(end_date, is_end=True)
            if start_dt and end_dt and start_dt > end_dt:
                return {
                    "ok": False,
                    "trace_id": trace_id,
                    "result": {},
                    "audit": self._build_audit(trace_id, steps + ["error invalid_range start_after_end"]),
                    "errors": ["start_date must be earlier than or equal to end_date"],
                }

            client = self._build_client()

            # v0.31：可见性与时间过滤全部下推到服务端 CEL。
            visibility_clause = visibility_filter_clause(configured_visibility)
            time_clause = build_timestamp_clause(cel_field, start_dt, end_dt)
            filter_cel = combine_cel_clauses(visibility_clause, time_clause)
            steps.append(f"server_filter_cel={filter_cel!r}")

            query_text = (query or "").strip()
            query_mode = "keyword" if query_text else "recent"

            # pageToken 内编码 limit，翻页时必须保持固定 pageSize。
            page_size = 100
            page_token: str | None = None
            scanned_count = 0
            visibility_filtered_count = 0
            keyword_filtered_count = 0
            page_count = 0
            result_memos: list[dict[str, Any]] = []

            while True:
                page_count += 1
                memos_page, next_page_token = await client.list_memos_page(
                    page_size=page_size,
                    page_token=page_token,
                    include_archived=include_archived,
                    filter_cel=filter_cel,
                )
                if not memos_page:
                    break
                scanned_count += len(memos_page)

                # 服务端已按可见性收窄，这里再做一次防御性校验。
                visibility_kept = [
                    memo
                    for memo in memos_page
                    if memo.get("visibility") in allowed_visibilities
                ]
                visibility_filtered_count += len(visibility_kept)

                if query_text:
                    keyword_kept = [m for m in visibility_kept if self._memo_match_keyword(m, query_text)]
                else:
                    keyword_kept = visibility_kept
                keyword_filtered_count += len(keyword_kept)

                for memo in keyword_kept:
                    result_memos.append(memo)
                    if len(result_memos) >= search_max_count:
                        break

                if len(result_memos) >= search_max_count:
                    steps.append("stop_reason=reach_search_max_count")
                    break
                if not next_page_token:
                    steps.append("stop_reason=no_more_pages")
                    break
                page_token = next_page_token

            if query_text:
                steps.append(f"keyword_filter_applied query={query_text!r}")
            else:
                steps.append("keyword_filter_skipped query_empty=true")
            steps.append(
                f"pipeline_done pages={page_count} scanned={scanned_count} "
                f"visibility_kept={visibility_filtered_count} keyword_kept={keyword_filtered_count} "
                f"final={len(result_memos)}"
            )

            logger.info(f"[memos_search] trace={trace_id} ok returned={len(result_memos)}")
            return {
                "ok": True,
                "trace_id": trace_id,
                "result": {
                    "query_mode": query_mode,
                    "search_max_count": search_max_count,
                    "matched_count": len(result_memos),
                    "memos": result_memos,
                },
                "audit": self._build_audit(
                    trace_id,
                    steps,
                    metrics={
                        "query_mode": query_mode,
                        "final_return_limit": search_max_count,
                        "selected_date_field": selected_date_field,
                        "cel_time_field": cel_field,
                        "filter_cel": filter_cel,
                        "start_date": start_date,
                        "end_date": end_date,
                        "scanned_count": scanned_count,
                        "visibility_kept_count": visibility_filtered_count,
                        "keyword_filtered_count": keyword_filtered_count,
                        "matched_count": len(result_memos),
                    },
                ),
                "errors": [],
            }
        except ValueError as exc:
            steps.append(f"error type=invalid_date message={exc}")
            logger.error(f"[memos_search] trace={trace_id} invalid date: {exc}")
            return {
                "ok": False,
                "trace_id": trace_id,
                "result": {},
                "audit": self._build_audit(trace_id, steps),
                "errors": [str(exc)],
            }
        except MemosClientError as exc:
            steps.append(f"error type=memos_client_error message={exc}")
            logger.error(
                "[memos_search] trace=%s failed: %s",
                trace_id,
                getattr(exc, "debug_message", str(exc)),
            )
            return {
                "ok": False,
                "trace_id": trace_id,
                "result": {},
                "audit": self._build_audit(trace_id, steps),
                "errors": [str(exc)],
            }
        except Exception as exc:  # pragma: no cover
            steps.append(f"error type=unexpected message={exc}")
            logger.exception("[memos_search] trace=%s unexpected failure", trace_id)
            return {
                "ok": False,
                "trace_id": trace_id,
                "result": {},
                "audit": self._build_audit(trace_id, steps),
                "errors": [f"unexpected error: {exc}"],
            }

    async def run_create(self, content: str, visibility: str | None = None) -> dict[str, Any]:
        """创建 memo，未指定可见性时使用默认配置。"""
        trace_id = self._trace_id()
        steps: list[str] = []
        try:
            default_visibility = normalize_visibility_label(
                self._cfg_str("default_visibility", "workspace")
            )
            selected = normalize_visibility_label(visibility or default_visibility)
            visibility_api = map_visibility_label_to_api(selected)
            steps.append(
                f"start memos_create trace={trace_id} visibility_label={selected} visibility_api={visibility_api}"
            )

            client = self._build_client()
            memo = await client.create_memo(content=content, visibility=visibility_api)
            steps.append(f"create_done memo={memo.get('name', '')}")
            logger.info(f"[memos_create] trace={trace_id} ok memo={memo.get('name', '')}")
            return {
                "ok": True,
                "trace_id": trace_id,
                "result": {"memo": memo},
                "audit": self._build_audit(trace_id, steps),
                "errors": [],
            }
        except MemosClientError as exc:
            steps.append(f"error type=memos_client_error message={exc}")
            logger.error(
                "[memos_create] trace=%s failed: %s",
                trace_id,
                getattr(exc, "debug_message", str(exc)),
            )
            return {
                "ok": False,
                "trace_id": trace_id,
                "result": {},
                "audit": self._build_audit(trace_id, steps),
                "errors": [str(exc)],
            }
        except Exception as exc:
            steps.append(f"error message={exc}")
            logger.exception("[memos_create] trace=%s failed", trace_id)
            return {
                "ok": False,
                "trace_id": trace_id,
                "result": {},
                "audit": self._build_audit(trace_id, steps),
                "errors": [str(exc)],
            }

    async def run_update(
        self,
        name: str,
        content: str | None = None,
        visibility: str | None = None,
        pinned: bool | None = None,
    ) -> dict[str, Any]:
        """更新 memo 的内容、可见性和置顶状态。"""
        trace_id = self._trace_id()
        steps: list[str] = []
        try:
            update_payload: dict[str, Any] = {}
            if content is not None:
                update_payload["content"] = content
            if visibility is not None:
                update_payload["visibility"] = map_visibility_label_to_api(
                    normalize_visibility_label(visibility)
                )
            if pinned is not None:
                update_payload["pinned"] = pinned

            if not update_payload:
                return {
                    "ok": False,
                    "trace_id": trace_id,
                    "result": {},
                    "audit": self._build_audit(trace_id, ["no_update_fields_provided"]),
                    "errors": ["at least one of content/visibility/pinned is required"],
                }

            steps.append(
                f"start memos_update trace={trace_id} name={name} fields={','.join(update_payload.keys())}"
            )
            client = self._build_client()
            memo = await client.update_memo(name=name, updates=update_payload)
            steps.append("update_done")
            logger.info(f"[memos_update] trace={trace_id} ok memo={name}")
            return {
                "ok": True,
                "trace_id": trace_id,
                "result": {"memo": memo},
                "audit": self._build_audit(trace_id, steps),
                "errors": [],
            }
        except MemosClientError as exc:
            steps.append(f"error type=memos_client_error message={exc}")
            logger.error(
                "[memos_update] trace=%s failed: %s",
                trace_id,
                getattr(exc, "debug_message", str(exc)),
            )
            return {
                "ok": False,
                "trace_id": trace_id,
                "result": {},
                "audit": self._build_audit(trace_id, steps),
                "errors": [str(exc)],
            }
        except Exception as exc:
            steps.append(f"error message={exc}")
            logger.exception("[memos_update] trace=%s failed", trace_id)
            return {
                "ok": False,
                "trace_id": trace_id,
                "result": {},
                "audit": self._build_audit(trace_id, steps),
                "errors": [str(exc)],
            }

    async def run_delete(self, name: str) -> dict[str, Any]:
        """删除 memo。"""
        trace_id = self._trace_id()
        steps: list[str] = [f"start memos_delete trace={trace_id} name={name}"]
        try:
            client = self._build_client()
            await client.delete_memo(name=name)
            steps.append("delete_done")
            logger.info(f"[memos_delete] trace={trace_id} ok memo={name}")
            return {
                "ok": True,
                "trace_id": trace_id,
                "result": {"deleted": name},
                "audit": self._build_audit(trace_id, steps),
                "errors": [],
            }
        except MemosClientError as exc:
            steps.append(f"error type=memos_client_error message={exc}")
            logger.error(
                "[memos_delete] trace=%s failed: %s",
                trace_id,
                getattr(exc, "debug_message", str(exc)),
            )
            return {
                "ok": False,
                "trace_id": trace_id,
                "result": {},
                "audit": self._build_audit(trace_id, steps),
                "errors": [str(exc)],
            }
        except Exception as exc:
            steps.append(f"error message={exc}")
            logger.exception("[memos_delete] trace=%s failed", trace_id)
            return {
                "ok": False,
                "trace_id": trace_id,
                "result": {},
                "audit": self._build_audit(trace_id, steps),
                "errors": [str(exc)],
            }

    async def run_archive(self, name: str, archived: bool = True) -> dict[str, Any]:
        """归档或取消归档 memo。"""
        trace_id = self._trace_id()
        target_state = "ARCHIVED" if archived else "NORMAL"
        steps: list[str] = [
            f"start memos_archive trace={trace_id} name={name} archived={archived} target_state={target_state}"
        ]
        try:
            client = self._build_client()
            memo = await client.update_memo(name=name, updates={"state": target_state})
            steps.append("archive_done")
            logger.info(
                "[memos_archive] trace=%s ok memo=%s target_state=%s",
                trace_id,
                name,
                target_state,
            )
            return {
                "ok": True,
                "trace_id": trace_id,
                "result": {"memo": memo},
                "audit": self._build_audit(trace_id, steps),
                "errors": [],
            }
        except MemosClientError as exc:
            steps.append(f"error type=memos_client_error message={exc}")
            logger.error(
                "[memos_archive] trace=%s failed: %s",
                trace_id,
                getattr(exc, "debug_message", str(exc)),
            )
            return {
                "ok": False,
                "trace_id": trace_id,
                "result": {},
                "audit": self._build_audit(trace_id, steps),
                "errors": [str(exc)],
            }
        except Exception as exc:
            steps.append(f"error message={exc}")
            logger.exception("[memos_archive] trace=%s failed", trace_id)
            return {
                "ok": False,
                "trace_id": trace_id,
                "result": {},
                "audit": self._build_audit(trace_id, steps),
                "errors": [str(exc)],
            }

    async def run_archive_list(
        self,
        query: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        date_field: str = "create_time",
    ) -> dict[str, Any]:
        """查询已归档 memo 列表。"""
        search_result = await self.run_search(
            query=query,
            include_archived=True,
            start_date=start_date,
            end_date=end_date,
            date_field=date_field,
        )
        if not search_result.get("ok"):
            return search_result

        search_max_count = self._cfg_int("search_max_count", 50)

        result = search_result.get("result") or {}
        memos_any = result.get("memos")
        memos: list[dict[str, Any]] = memos_any if isinstance(memos_any, list) else []
        trimmed = memos[:search_max_count]

        result["query_mode"] = "archived_list"
        result["search_max_count"] = search_max_count
        result["matched_count"] = len(trimmed)
        result["memos"] = trimmed
        search_result["result"] = result
        return search_result


class BaseMemosTool(FunctionTool[AstrAgentContext]):
    """所有 Memos Tool 的基类，提供统一鉴权入口。"""

    def __init__(self, plugin: MemosManagerPlugin):
        self.plugin = plugin

    def _check_auth_or_return(
        self,
        context: ContextWrapper[AstrAgentContext],
        tool_name: str,
    ) -> dict[str, Any] | None:
        """在每个工具调用前执行权限校验。

        若校验失败，直接返回错误结果。
        """
        trace_id = self.plugin._trace_id()
        allowed, reason, _uid = self.plugin._check_tool_permission(context, tool_name)
        if allowed:
            return None
        logger.warning("[memos_auth] tool=%s denied reason=%s", tool_name, reason)
        return self.plugin._auth_denied_result(trace_id=trace_id, tool_name=tool_name, reason=reason)


class MemosSearchTool(BaseMemosTool):
    name = "memos_search"
    description = "按日期和关键词检索未归档笔记，返回条数受配置限制。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "关键词，可选。为空时返回日期筛选后的结果。",
            },
            "start_date": {
                "type": "string",
                "description": "起始日期/时间，支持 YYYY-MM-DD 或 ISO8601。",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期/时间，支持 YYYY-MM-DD 或 ISO8601。",
            },
            "date_field": {
                "type": "string",
                "description": "日期字段：create_time（默认，别名 display_time）/update_time。",
                "default": "create_time",
            },
        },
        "required": [],
    }

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        denied = self._check_auth_or_return(context, self.name)
        if denied is not None:
            return denied

        query = self.plugin._parse_optional_text(kwargs.get("query"))
        selected_date_field = self.plugin._parse_date_field(kwargs.get("date_field", "create_time"))
        return await self.plugin.run_search(
            query=query,
            include_archived=False,
            start_date=kwargs.get("start_date"),
            end_date=kwargs.get("end_date"),
            date_field=selected_date_field,
        )


class MemosCreateTool(BaseMemosTool):
    name = "memos_create"
    description = "创建一条新笔记。"
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "笔记正文（Markdown 文本）。",
            },
            "visibility": {
                "type": "string",
                "description": "可选可见性：workspace/private/public。",
            },
        },
        "required": ["content"],
    }

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        denied = self._check_auth_or_return(context, self.name)
        if denied is not None:
            return denied

        return await self.plugin.run_create(
            content=str(kwargs["content"]),
            visibility=kwargs.get("visibility"),
        )


class MemosUpdateTool(BaseMemosTool):
    name = "memos_update"
    description = "更新笔记内容、可见性或置顶状态。"
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "笔记资源名，例如 memos/xxxx。",
            },
            "content": {
                "type": "string",
                "description": "可选：更新后的正文。",
            },
            "visibility": {
                "type": "string",
                "description": "可选可见性：workspace/private/public。",
            },
            "pinned": {
                "type": "boolean",
                "description": "可选：是否置顶。",
            },
        },
        "required": ["name"],
    }

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        denied = self._check_auth_or_return(context, self.name)
        if denied is not None:
            return denied

        return await self.plugin.run_update(
            name=str(kwargs["name"]),
            content=kwargs.get("content"),
            visibility=kwargs.get("visibility"),
            pinned=kwargs.get("pinned"),
        )


class MemosDeleteTool(BaseMemosTool):
    name = "memos_delete"
    description = "按资源名删除一条笔记。"
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "笔记资源名，例如 memos/xxxx。",
            },
        },
        "required": ["name"],
    }

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        denied = self._check_auth_or_return(context, self.name)
        if denied is not None:
            return denied

        return await self.plugin.run_delete(name=str(kwargs["name"]))


class MemosArchiveTool(BaseMemosTool):
    name = "memos_archive"
    description = "归档管理：设置归档状态或查询已归档笔记。"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：set 或 list_archived。",
                "default": "set",
            },
            "name": {
                "type": "string",
                "description": "笔记资源名，例如 memos/xxxx。action=set 时必填。",
            },
            "archived": {
                "type": "boolean",
                "description": "是否归档。true=归档，false=取消归档。action=set 时生效。",
                "default": True,
            },
            "query": {
                "type": "string",
                "description": "关键词。action=list_archived 时可选。",
            },
            "start_date": {
                "type": "string",
                "description": "起始日期/时间，支持 YYYY-MM-DD 或 ISO8601。action=list_archived 时可选。",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期/时间，支持 YYYY-MM-DD 或 ISO8601。action=list_archived 时可选。",
            },
            "date_field": {
                "type": "string",
                "description": "日期字段：create_time（默认，别名 display_time）/update_time。action=list_archived 时生效。",
                "default": "create_time",
            },
        },
        "required": [],
    }

    async def _handle_archive_list(self, kwargs: dict[str, Any]) -> ToolExecResult:
        selected_date_field = self.plugin._parse_date_field(kwargs.get("date_field", "create_time"))
        return await self.plugin.run_archive_list(
            query=self.plugin._parse_optional_text(kwargs.get("query")),
            start_date=kwargs.get("start_date"),
            end_date=kwargs.get("end_date"),
            date_field=selected_date_field,
        )

    async def _handle_archive_set(self, kwargs: dict[str, Any]) -> ToolExecResult:
        ok, name_or_error = self.plugin._require_name_for_set(kwargs.get("name"))
        if not ok:
            trace_id = self.plugin._trace_id()
            return self.plugin._tool_input_error(
                trace_id=trace_id,
                code="missing_name_for_set_action",
                message=name_or_error,
            )

        archived = self.plugin._parse_bool_with_default(kwargs.get("archived"), True)
        return await self.plugin.run_archive(
            name=name_or_error,
            archived=archived,
        )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        denied = self._check_auth_or_return(context, self.name)
        if denied is not None:
            return denied

        action = self.plugin._parse_action(kwargs.get("action", "set"))
        if action == "list_archived":
            return await self._handle_archive_list(kwargs)

        if action != "set":
            trace_id = self.plugin._trace_id()
            return self.plugin._tool_input_error(
                trace_id=trace_id,
                code="invalid_action",
                message="action must be one of: set, list_archived",
            )

        return await self._handle_archive_set(
            kwargs=kwargs,
        )
