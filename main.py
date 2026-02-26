from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

try:
    from .memos_client import MemosClient, MemosClientError
    from .tool_models import (
        map_visibility_label_to_api,
        normalize_visibility_label,
    )
except ImportError:
    from memos_client import MemosClient, MemosClientError
    from tool_models import (
        map_visibility_label_to_api,
        normalize_visibility_label,
    )


@register(
    "astrbot_plugin_memos_manager",
    "astrbot_plugin_memos_manager",
    "Memos manager tools for search/create/update/delete.",
    "0.1",
    "",
)
class MemosManagerPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.context.add_llm_tools(
            MemosSearchTool(self),
            MemosCreateTool(self),
            MemosUpdateTool(self),
            MemosDeleteTool(self),
        )

    def _cfg_str(self, key: str, default: str = "") -> str:
        value = self.config.get(key, default)
        return value if isinstance(value, str) else default

    def _cfg_int(self, key: str, default: int) -> int:
        value = self.config.get(key, default)
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except (TypeError, ValueError):
            return default

    def _cfg_bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return default

    def _trace_id(self) -> str:
        return uuid.uuid4().hex[:10]

    def _local_tz(self):
        return datetime.now().astimezone().tzinfo or timezone.utc

    def _parse_date_bound(self, raw: str | None, *, is_end: bool) -> datetime | None:
        if raw is None:
            return None
        text = raw.strip()
        if not text:
            return None
        tz = self._local_tz()
        try:
            if len(text) == 10:
                day = date.fromisoformat(text)
                if is_end:
                    dt = datetime.combine(day, time(23, 59, 59), tzinfo=tz)
                else:
                    dt = datetime.combine(day, time(0, 0, 0), tzinfo=tz)
            else:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
            return dt.astimezone(timezone.utc)
        except ValueError as exc:
            raise ValueError(f"invalid date format: {raw}") from exc

    def _parse_memo_time(self, raw: Any) -> datetime | None:
        if not isinstance(raw, str) or not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _memo_match_keyword(memo: dict[str, Any], query: str) -> bool:
        q_cf = query.casefold()
        content = str(memo.get("content", ""))
        snippet = str(memo.get("snippet", ""))
        tags = memo.get("tags", [])
        tags_text = " ".join(tags) if isinstance(tags, list) else ""
        haystack = f"{content}\n{snippet}\n{tags_text}".casefold()
        return q_cf in haystack

    def _build_client(self) -> MemosClient:
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

    async def run_search(
        self,
        query: str | None,
        include_archived: bool = False,
        start_date: str | None = None,
        end_date: str | None = None,
        date_field: str = "display_time",
    ) -> dict[str, Any]:
        trace_id = self._trace_id()
        steps: list[str] = []
        search_max_count = self._cfg_int("search_max_count", 50)
        selected_date_field = (date_field or "display_time").strip().lower()
        if selected_date_field not in {"display_time", "create_time", "update_time"}:
            selected_date_field = "display_time"
        steps.append(
            f"start memos_search trace={trace_id} query_present={bool(query and query.strip())} "
            f"include_archived={include_archived} search_max_count={search_max_count} "
            f"start_date={start_date!r} end_date={end_date!r} date_field={selected_date_field}"
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

            old_filter_parts: list[str] = []
            if selected_date_field == "display_time":
                if start_dt is not None:
                    old_filter_parts.append(f"display_time_after == {int(start_dt.timestamp())}")
                if end_dt is not None:
                    old_filter_parts.append(f"display_time_before == {int(end_dt.timestamp())}")
            old_filter = " && ".join(old_filter_parts) if old_filter_parts else None

            query_text = (query or "").strip()
            query_mode = "keyword" if query_text else "recent"

            page_size = 100
            page_token: str | None = None
            scanned_count = 0
            date_filtered_count = 0
            keyword_filtered_count = 0
            page_count = 0
            result_memos: list[dict[str, Any]] = []

            while True:
                page_count += 1
                memos_page, next_page_token = await client.list_memos_page(
                    page_size=page_size,
                    page_token=page_token,
                    include_archived=include_archived,
                    old_filter=old_filter,
                )
                if not memos_page:
                    break
                scanned_count += len(memos_page)

                date_kept: list[dict[str, Any]] = []
                for memo in memos_page:
                    if selected_date_field != "display_time":
                        target_dt = self._parse_memo_time(memo.get(selected_date_field))
                        if target_dt is None:
                            continue
                        if start_dt is not None and target_dt < start_dt:
                            continue
                        if end_dt is not None and target_dt > end_dt:
                            continue
                    date_kept.append(memo)
                date_filtered_count += len(date_kept)

                if query_text:
                    keyword_kept = [m for m in date_kept if self._memo_match_keyword(m, query_text)]
                else:
                    keyword_kept = date_kept
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
                f"pipeline_done pages={page_count} scanned={scanned_count} date_kept={date_filtered_count} "
                f"keyword_kept={keyword_filtered_count} final={len(result_memos)}"
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
                        "start_date": start_date,
                        "end_date": end_date,
                        "scanned_count": scanned_count,
                        "date_filtered_count": date_filtered_count,
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
            logger.error(f"[memos_search] trace={trace_id} failed: {exc}")
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


class BaseMemosTool(FunctionTool[AstrAgentContext]):
    def __init__(self, plugin: MemosManagerPlugin):
        self.plugin = plugin


class MemosSearchTool(BaseMemosTool):
    name = "memos_search"
    description = (
        "Search memos with optional date range and keyword. Pipeline is date filtering then "
        "keyword matching. Final returned items are capped by plugin search_max_count."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional keyword query. Empty means return recent memos.",
            },
            "start_date": {
                "type": "string",
                "description": "Optional start date/time. Supports YYYY-MM-DD or ISO8601.",
            },
            "end_date": {
                "type": "string",
                "description": "Optional end date/time. Supports YYYY-MM-DD or ISO8601.",
            },
            "date_field": {
                "type": "string",
                "description": "Date field for filtering: display_time/create_time/update_time.",
                "default": "display_time",
            },
            "include_archived": {
                "type": "boolean",
                "description": "Whether to include archived memos.",
                "default": False,
            },
        },
        "required": [],
    }

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        query = kwargs.get("query")
        include_archived = bool(kwargs.get("include_archived", False))
        return await self.plugin.run_search(
            query=query,
            include_archived=include_archived,
            start_date=kwargs.get("start_date"),
            end_date=kwargs.get("end_date"),
            date_field=str(kwargs.get("date_field", "display_time")),
        )


class MemosCreateTool(BaseMemosTool):
    name = "memos_create"
    description = "Create a new memo. Visibility defaults to plugin default_visibility."
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Memo content in markdown.",
            },
            "visibility": {
                "type": "string",
                "description": "Optional visibility label: workspace/private/public.",
            },
        },
        "required": ["content"],
    }

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        return await self.plugin.run_create(
            content=str(kwargs["content"]),
            visibility=kwargs.get("visibility"),
        )


class MemosUpdateTool(BaseMemosTool):
    name = "memos_update"
    description = "Update memo content/visibility/pinned by memo name."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Memo resource name, e.g. memos/xxxx.",
            },
            "content": {
                "type": "string",
                "description": "Optional updated markdown content.",
            },
            "visibility": {
                "type": "string",
                "description": "Optional visibility label: workspace/private/public.",
            },
            "pinned": {
                "type": "boolean",
                "description": "Optional pinned flag.",
            },
        },
        "required": ["name"],
    }

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        return await self.plugin.run_update(
            name=str(kwargs["name"]),
            content=kwargs.get("content"),
            visibility=kwargs.get("visibility"),
            pinned=kwargs.get("pinned"),
        )


class MemosDeleteTool(BaseMemosTool):
    name = "memos_delete"
    description = "Delete a memo by resource name."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Memo resource name, e.g. memos/xxxx.",
            },
        },
        "required": ["name"],
    }

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        return await self.plugin.run_delete(name=str(kwargs["name"]))
