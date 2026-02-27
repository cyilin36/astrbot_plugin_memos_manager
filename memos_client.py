from __future__ import annotations

from typing import Any

import httpx


class MemosClientError(Exception):
    pass


class MemosClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: int = 20):
        self.base_url = self._normalize_base_url(base_url)
        self.token = token.strip()
        self.timeout_seconds = timeout_seconds
        if not self.base_url:
            raise MemosClientError("memos_base_url is empty")
        if not self.token:
            raise MemosClientError("memos_token is empty")

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        cleaned = (url or "").strip().rstrip("/")
        if not cleaned:
            return ""
        if cleaned.endswith("/api/v1"):
            return cleaned
        return f"{cleaned}/api/v1"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _sanitize_memo(self, memo: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": memo.get("name", ""),
            "content": memo.get("content", ""),
            "visibility": memo.get("visibility", ""),
            "tags": memo.get("tags", []),
            "create_time": memo.get("createTime", ""),
            "update_time": memo.get("updateTime", ""),
            "display_time": memo.get("displayTime", ""),
            "pinned": memo.get("pinned", False),
            "snippet": memo.get("snippet", ""),
            "creator": memo.get("creator", ""),
            "state": memo.get("state", ""),
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=self._headers(),
                )
        except httpx.TimeoutException as exc:
            raise MemosClientError(f"request timeout: {method} {path}") from exc
        except httpx.HTTPError as exc:
            raise MemosClientError(f"network error: {method} {path}: {exc}") from exc

        if response.status_code >= 400:
            message = response.text
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    message = payload.get("message", message)
            except Exception:
                pass
            raise MemosClientError(
                f"memos api error {response.status_code} on {method} {path}: {message}"
            )

        if not response.content:
            return {}
        try:
            data = response.json()
            if isinstance(data, dict):
                return data
            raise MemosClientError(f"unexpected response shape on {method} {path}")
        except ValueError as exc:
            raise MemosClientError(f"invalid json response on {method} {path}") from exc

    async def list_memos_page(
        self,
        *,
        page_size: int,
        page_token: str | None = None,
        include_archived: bool = False,
        old_filter: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        state = "ARCHIVED" if include_archived else "NORMAL"
        params: dict[str, Any] = {
            "pageSize": max(1, int(page_size)),
            "state": state,
            "sort": "display_time",
            "direction": "DESC",
        }
        if page_token:
            params["pageToken"] = page_token
        if old_filter:
            params["oldFilter"] = old_filter
        data = await self._request("GET", "/memos", params=params)
        memos = data.get("memos", [])
        if not isinstance(memos, list):
            raise MemosClientError("invalid memos list in list_memos_page")
        next_page_token = data.get("nextPageToken")
        if not isinstance(next_page_token, str) or not next_page_token:
            next_page_token = None
        return [self._sanitize_memo(m) for m in memos if isinstance(m, dict)], next_page_token

    async def list_recent_memos(self, limit: int, include_archived: bool = False) -> list[dict[str, Any]]:
        memos, _ = await self.list_memos_page(
            page_size=max(1, int(limit)),
            include_archived=include_archived,
        )
        return memos[:limit]

    async def create_memo(self, content: str, visibility: str) -> dict[str, Any]:
        payload = {
            "content": content,
            "visibility": visibility,
        }
        data = await self._request("POST", "/memos", json_body=payload)
        return self._sanitize_memo(data)

    async def update_memo(self, name: str, updates: dict[str, Any]) -> dict[str, Any]:
        if not name.startswith("memos/"):
            raise MemosClientError("memo name must start with memos/")
        mask_paths = list(updates.keys())
        payload = {
            "name": name,
            **updates,
        }
        params = {
            "updateMask": ",".join(mask_paths),
        }
        data = await self._request("PATCH", f"/{name}", params=params, json_body=payload)
        return self._sanitize_memo(data)

    async def delete_memo(self, name: str) -> None:
        if not name.startswith("memos/"):
            raise MemosClientError("memo name must start with memos/")
        await self._request("DELETE", f"/{name}")
