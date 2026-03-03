from __future__ import annotations

from typing import Any

import httpx


class MemosClientError(Exception):
    def __init__(
        self,
        user_message: str,
        *,
        status_code: int | None = None,
        method: str | None = None,
        path: str | None = None,
        raw_message: str | None = None,
    ):
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code
        self.method = method
        self.path = path
        self.raw_message = raw_message

    @property
    def debug_message(self) -> str:
        parts: list[str] = [self.user_message]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.method and self.path:
            parts.append(f"request={self.method} {self.path}")
        if self.raw_message:
            parts.append(f"raw={self.raw_message}")
        return " | ".join(parts)

    def __str__(self) -> str:
        return self.user_message


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

    @staticmethod
    def _user_message_by_status(status_code: int) -> str:
        if status_code == 401:
            return "认证失败：请检查 memos_token 是否正确"
        if status_code == 403:
            return "权限不足：当前 token 无权执行该操作"
        if status_code == 404:
            return "资源不存在：请确认 memo name 是否正确"
        if status_code == 429:
            return "请求过于频繁：请稍后重试"
        if 500 <= status_code <= 599:
            return "Memos 服务异常：请稍后重试"
        if 400 <= status_code <= 499:
            return "请求参数不合法：请检查输入"
        return "请求 Memos 失败：请稍后重试"

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
            raise MemosClientError(
                "请求 Memos 超时：请稍后重试",
                method=method,
                path=path,
                raw_message=str(exc),
            ) from exc
        except httpx.HTTPError as exc:
            raise MemosClientError(
                "连接 Memos 失败：请检查网络或服务地址",
                method=method,
                path=path,
                raw_message=str(exc),
            ) from exc

        if response.status_code >= 400:
            message = response.text
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    message = payload.get("message", message)
            except Exception:
                pass
            raise MemosClientError(
                self._user_message_by_status(response.status_code),
                status_code=response.status_code,
                method=method,
                path=path,
                raw_message=message,
            )

        if not response.content:
            return {}
        try:
            data = response.json()
            if isinstance(data, dict):
                return data
            raise MemosClientError(
                "Memos 返回格式异常：请稍后重试",
                method=method,
                path=path,
            )
        except ValueError as exc:
            raise MemosClientError(
                "Memos 返回数据无法解析：请稍后重试",
                method=method,
                path=path,
                raw_message=str(exc),
            ) from exc

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
            raise MemosClientError("memo name 格式错误：必须以 memos/ 开头")
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
            raise MemosClientError("memo name 格式错误：必须以 memos/ 开头")
        await self._request("DELETE", f"/{name}")
