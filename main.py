from __future__ import annotations

import uuid
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

    async def run_search(self, query: str | None, include_archived: bool = False) -> dict[str, Any]:
        trace_id = self._trace_id()
        steps: list[str] = []
        search_max_count = self._cfg_int("search_max_count", 50)
        steps.append(
            f"start memos_search trace={trace_id} query_present={bool(query and query.strip())} "
            f"include_archived={include_archived} search_max_count={search_max_count}"
        )
        try:
            client = self._build_client()
            memos = await client.list_recent_memos(
                limit=search_max_count,
                include_archived=include_archived,
            )
            steps.append(f"fetched_recent_memos count={len(memos)}")

            if query and query.strip():
                q = query.strip()
                filtered = []
                q_cf = q.casefold()
                for memo in memos:
                    content = str(memo.get("content", ""))
                    snippet = str(memo.get("snippet", ""))
                    tags = memo.get("tags", [])
                    tags_text = " ".join(tags) if isinstance(tags, list) else ""
                    haystack = f"{content}\n{snippet}\n{tags_text}".casefold()
                    if q_cf in haystack:
                        filtered.append(memo)
                memos = filtered
                steps.append(f"keyword_filter_applied query={q!r} matched={len(memos)}")
                query_mode = "keyword"
            else:
                steps.append("keyword_filter_skipped query_empty=true")
                query_mode = "recent"

            logger.info(f"[memos_search] trace={trace_id} ok fetched={len(memos)}")
            return {
                "ok": True,
                "trace_id": trace_id,
                "result": {
                    "query_mode": query_mode,
                    "search_max_count": search_max_count,
                    "matched_count": len(memos),
                    "memos": memos,
                },
                "audit": self._build_audit(
                    trace_id,
                    steps,
                    metrics={
                        "query_mode": query_mode,
                        "search_pool_limit": search_max_count,
                        "matched_count": len(memos),
                    },
                ),
                "errors": [],
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
        "Search memos from the recent memo pool only. Uses plugin search_max_count, "
        "sorted by latest-first. If query is empty, returns recent memos directly."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional keyword query. Empty means return recent memos.",
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
        return await self.plugin.run_search(query=query, include_archived=include_archived)


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
