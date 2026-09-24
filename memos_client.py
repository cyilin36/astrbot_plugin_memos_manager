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
    """Memos v0.31 REST (gRPC-Gateway) client.

    只使用 v0.31 仍然存在的公开路由：
    - GET    /api/v1/memos
    - POST   /api/v1/memos
    - PATCH  /api/v1/memos/{memo}
    - DELETE /api/v1/memos/{memo}

    v0.24 时代的 `GET /api/v1/users/{user}/memos`、`oldFilter`、`sort`、
    `direction` 与 `display_time` 在 v0.31 中均已移除，故不再使用。
    """

    def __init__(self, base_url: str, token: str, timeout_seconds: int = 20):
        self.base_url = self._normalize_base_url(base_url)
        self.token = token.strip()
        self.timeout_seconds = timeout_seconds
        # 可选的 httpx transport 注入点：生产环境为 None（使用默认网络），
        # 测试时替换为 MockTransport 即可完全离线断言请求形状。
        self._transport: httpx.AsyncBaseTransport | None = None
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

    @staticmethod
    def _sanitize_memo(memo: dict[str, Any]) -> dict[str, Any]:
        """归一化 v0.31 Memo 结构，只保留插件关心的字段。

        `display_time` 在 v0.31 已被删除（proto 中显式 reserved），因此不再输出；
        时间统一使用 `create_time` / `update_time`（RFC3339）。
        """
        sanitized: dict[str, Any] = {
            "name": memo.get("name", ""),
            "content": memo.get("content", ""),
            "visibility": memo.get("visibility", ""),
            "tags": memo.get("tags", []),
            "create_time": memo.get("createTime", ""),
            "update_time": memo.get("updateTime", ""),
            "pinned": memo.get("pinned", False),
            "snippet": memo.get("snippet", ""),
            "creator": memo.get("creator", ""),
            "state": memo.get("state", ""),
        }
        # v0.31 新增字段，缺失时保持缺省以避免污染输出。
        if isinstance(memo.get("property"), dict):
            sanitized["property"] = memo["property"]
        if memo.get("space"):
            sanitized["space"] = memo["space"]
        if memo.get("parent"):
            sanitized["parent"] = memo["parent"]
        return sanitized

    @staticmethod
    def _user_message_by_status(status_code: int) -> str:
        if status_code == 401:
            return "认证失败：memos_token 无效或已过期（v0.31 请使用 PAT）"
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
        # 去掉 None 值，避免 grpc-gateway 把空串当成显式参数。
        clean_params = {
            key: value
            for key, value in (params or {}).items()
            if value is not None and value != ""
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self._transport
            ) as client:
                response = await client.request(
                    method,
                    url,
                    params=clean_params or None,
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
        except ValueError as exc:
            raise MemosClientError(
                "Memos 返回数据无法解析：请稍后重试",
                method=method,
                path=path,
                raw_message=str(exc),
            ) from exc
        if not isinstance(data, dict):
            raise MemosClientError(
                "Memos 返回格式异常：请稍后重试",
                method=method,
                path=path,
            )
        return data

    async def list_memos_page(
        self,
        *,
        page_size: int,
        page_token: str | None = None,
        include_archived: bool = False,
        order_by: str = "pinned desc, create_time desc",
        filter_cel: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """列出笔记。

        v0.31 注意：一旦请求携带 `pageToken`，服务端会使用 token 中编码的
        limit 而忽略本次的 `pageSize`，因此翻页过程中必须保持 page_size 固定。
        """
        params: dict[str, Any] = {
            "pageSize": max(1, int(page_size)),
            "state": "ARCHIVED" if include_archived else "NORMAL",
            "orderBy": order_by,
        }
        if page_token:
            params["pageToken"] = page_token
        if filter_cel:
            params["filter"] = filter_cel
        data = await self._request("GET", "/memos", params=params)
        memos = data.get("memos", [])
        if not isinstance(memos, list):
            raise MemosClientError("invalid memos list in list_memos_page")
        next_page_token = data.get("nextPageToken")
        if not isinstance(next_page_token, str) or not next_page_token:
            next_page_token = None
        return [
            self._sanitize_memo(m) for m in memos if isinstance(m, dict)
        ], next_page_token

    async def list_recent_memos(
        self,
        limit: int,
        include_archived: bool = False,
        filter_cel: str | None = None,
    ) -> list[dict[str, Any]]:
        memos, _ = await self.list_memos_page(
            page_size=max(1, int(limit)),
            include_archived=include_archived,
            filter_cel=filter_cel,
        )
        return memos[:limit]

    async def create_memo(
        self,
        content: str,
        visibility: str,
        memo_id: str | None = None,
    ) -> dict[str, Any]:
        """创建笔记。

        v0.31 的 `POST /api/v1/memos` 请求体直接是 Memo（不再有 `memo` 外层包装）。
        """
        payload: dict[str, Any] = {
            "content": content,
            "visibility": visibility,
        }
        params: dict[str, Any] = {}
        if memo_id:
            params["memoId"] = memo_id
        data = await self._request(
            "POST",
            "/memos",
            params=params or None,
            json_body=payload,
        )
        return self._sanitize_memo(data)

    async def update_memo(self, name: str, updates: dict[str, Any]) -> dict[str, Any]:
        """更新笔记。

        `updateMask` 是 query 参数，多个字段以英文逗号分隔（grpc-gateway 会按
        逗号拆分 FieldMask）。请求体是 Memo 本身。
        """
        if not name.startswith("memos/"):
            raise MemosClientError("memo name 格式错误：必须以 memos/ 开头")
        if not updates:
            raise MemosClientError("updates 为空：至少需要一个待更新字段")
        mask_paths = list(updates.keys())
        payload = {
            "name": name,
            **updates,
        }
        params = {
            "updateMask": ",".join(mask_paths),
        }
        data = await self._request(
            "PATCH",
            f"/{name}",
            params=params,
            json_body=payload,
        )
        return self._sanitize_memo(data)

    async def delete_memo(self, name: str, force: bool | None = None) -> None:
        if not name.startswith("memos/"):
            raise MemosClientError("memo name 格式错误：必须以 memos/ 开头")
        params: dict[str, Any] = {}
        if force is not None:
            params["force"] = "true" if force else "false"
        await self._request("DELETE", f"/{name}", params=params or None)
