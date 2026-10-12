"""覆写 memo 正文前的「先读后写」观察记录。

语义对齐 DSH 的文件观察策略（`dsh-fs-observation-policy` / `dsh-tool-fs`）：

- 检索结果（`memos_search`，已归档走 `memos_archive` 的 `list_archived`）会把
  命中的 memo 连同完整正文返回给模型，因此检索本身即「读取」：插件为返回的
  每条 memo 记录一次观察（memo 版本）。
- 有观察记录时才允许 `memos_update` 覆写正文；未读取即覆写会被拒绝
  （对应 DSH 的 `FS_NOT_OBSERVED`：``edit requires reading "<path>" first``）。
- 覆写前会比对服务端最新版本与观察版本：不一致说明笔记自读取后被外部修改，
  拒绝覆写并要求重新检索（对应 DSH 的 `FS_STALE_VERSION`：
  ``file changed since it was read``）。
- 覆写成功后用服务端返回的新版本刷新观察记录，因此同一会话内读取一次后
  可以连续覆写，无需反复检索。
- 观察记录不持久化：进程重启或 TTL 过期后必须重新读取。

本模块不依赖 AstrBot 运行时，便于单元测试。
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any, Callable, Mapping

# 观察记录的最长存活时间。DSH 的观察记录随会话消亡；AstrBot 侧拿不到会话
# 生命周期事件，因此用一个足够长的 TTL 近似：既避免长期占用内存，又不会在
# 正常对话中途强迫模型重读。
DEFAULT_TTL_SECONDS = 6 * 60 * 60
# 同时保留的会话作用域上限，超出后按最久未使用淘汰。
DEFAULT_MAX_SCOPES = 256


def memo_version(memo: Mapping[str, Any] | None) -> str:
    """计算一条 memo 的观察版本。

    DSH 的版本由文件系统提供（mtime/size）。Memos 没有等价的版本号，
    这里用「更新时间 + 正文哈希」近似：

    - 外部改动正文 → 正文哈希变化 → 版本变化；
    - 外部改动其它字段（会刷新 `update_time`）→ 版本变化；
    - 插件自己覆写成功后会用返回的新版本刷新记录，因此不会自我误判。
    """
    if not memo:
        return ""
    content = str(memo.get("content", "") or "")
    update_time = str(memo.get("update_time", "") or "")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return f"{update_time}#{digest}"


class MemoReadGuard:
    """按「会话作用域 → memo 资源名」记录读取观察。

    `scope` 由调用方提供（插件使用 `unified_msg_origin`，退化到 UID，最后到
    全局），因此不同会话互不共享观察记录，与 DSH 的「观察记录属于会话」一致。
    """

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_scopes: int = DEFAULT_MAX_SCOPES,
        clock: Callable[[], float] | None = None,
    ):
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._max_scopes = max(1, int(max_scopes))
        self._clock = clock or time.monotonic
        # OrderedDict 用于按「最近写入」淘汰最旧的作用域。
        self._scopes: OrderedDict[str, dict[str, tuple[float, str]]] = OrderedDict()

    def observe(self, scope: str, name: str, version: str) -> None:
        """记录（或刷新）一次读取观察。"""
        if not scope or not name:
            return
        now = self._clock()
        self._prune(now)
        bucket = self._scopes.get(scope)
        if bucket is None:
            bucket = {}
            self._scopes[scope] = bucket
        else:
            self._scopes.move_to_end(scope)
        bucket[name] = (now, str(version))
        while len(self._scopes) > self._max_scopes:
            self._scopes.popitem(last=False)

    def observed_version(self, scope: str, name: str) -> str | None:
        """返回该会话对这条 memo 的观察版本；未读或已过期返回 None。"""
        if not scope or not name:
            return None
        now = self._clock()
        bucket = self._scopes.get(scope)
        if not bucket:
            return None
        entry = bucket.get(name)
        if entry is None:
            return None
        observed_at, version = entry
        if now - observed_at > self._ttl_seconds:
            bucket.pop(name, None)
            if not bucket:
                self._scopes.pop(scope, None)
            return None
        return version

    def forget(self, scope: str, name: str) -> None:
        """丢弃某条观察记录（例如笔记已被删除）。"""
        bucket = self._scopes.get(scope)
        if not bucket:
            return
        bucket.pop(name, None)
        if not bucket:
            self._scopes.pop(scope, None)

    def clear(self) -> None:
        """清空全部观察记录。"""
        self._scopes.clear()

    def _prune(self, now: float) -> None:
        """清理所有过期条目。"""
        for scope in list(self._scopes.keys()):
            bucket = self._scopes[scope]
            for name in [
                key
                for key, (observed_at, _version) in bucket.items()
                if now - observed_at > self._ttl_seconds
            ]:
                bucket.pop(name, None)
            if not bucket:
                self._scopes.pop(scope, None)
