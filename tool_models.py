from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

VISIBILITY_LABELS = {"workspace", "private", "public"}

# v0.31 的服务端访问作用域：使用当前 token 的用户身份自动收窄可读集合
# （PRIVATE 仅创建者、PROTECTED 所有登录用户、PUBLIC 所有可匿名用户、
#   SPACE 仅该 Space 的 ACTIVE 成员）。插件在此基础上再做一层插件侧收窄。
READABLE_VISIBILITIES = {
    "private": frozenset({"PRIVATE", "PROTECTED", "PUBLIC", "SPACE"}),
    "workspace": frozenset({"PROTECTED", "PUBLIC"}),
    "public": frozenset({"PUBLIC"}),
}

# 日期字段名到 v0.31 CEL 时间字段的映射。
# `display_time` 在 v0.31 已被移除，作为兼容别名回退到创建时间。
DATE_FIELD_TO_CEL = {
    "display_time": "created_ts",
    "create_time": "created_ts",
    "update_time": "updated_ts",
}

CEL_TIMESTAMP_FIELDS = frozenset({"created_ts", "updated_ts"})


def normalize_visibility_label(raw: str | None) -> str:
    value = (raw or "workspace").strip().lower()
    if value not in VISIBILITY_LABELS:
        return "workspace"
    return value


def map_visibility_label_to_api(label: str) -> str:
    normalized = normalize_visibility_label(label)
    if normalized == "workspace":
        return "PROTECTED"
    if normalized == "public":
        return "PUBLIC"
    return "PRIVATE"


def readable_visibilities(label: str | None) -> frozenset[str]:
    normalized = normalize_visibility_label(label)
    return READABLE_VISIBILITIES[normalized]


def visibility_filter_clause(label: str | None) -> str | None:
    """把插件可见性档位翻译为 v0.31 的 CEL 可见性条件。

    - private：不加条件，直接使用服务端作用域返回的全部可读笔记
      （含本人的 PRIVATE 与所属 SPACE 笔记）。
    - workspace：仅 PROTECTED 与 PUBLIC。
    - public：仅 PUBLIC。
    """
    normalized = normalize_visibility_label(label)
    if normalized == "private":
        return None
    if normalized == "public":
        return 'visibility == "PUBLIC"'
    return 'visibility in ["PROTECTED", "PUBLIC"]'


def map_date_field_to_cel(field: str | None) -> str:
    """把插件日期字段名映射到 v0.31 的 CEL 时间字段。"""
    text = (field or "display_time").strip().lower()
    return DATE_FIELD_TO_CEL.get(text, "created_ts")


def _cel_timestamp(value: datetime) -> str:
    """把 datetime 渲染成 CEL 的 timestamp(epoch_seconds) 形式。

    CEL 的 timestamp() 接受 epoch 秒整数，服务端在编译期折叠为常量，
    因此不受实例时区影响。
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return f"timestamp({int(value.timestamp())})"


def build_timestamp_clause(
    cel_field: str,
    start: datetime | None,
    end: datetime | None,
) -> str | None:
    """构建半开区间 `[start, end)` 的时间条件。

    v0.31 的 `created_ts` / `updated_ts` 是时间戳字段，区间统一使用
    `>=` 与 `<`，避免闭区间在秒级精度上重复计入边界记录。
    """
    if cel_field not in CEL_TIMESTAMP_FIELDS:
        raise ValueError(f"unsupported cel timestamp field: {cel_field}")
    parts: list[str] = []
    if start is not None:
        parts.append(f"{cel_field} >= {_cel_timestamp(start)}")
    if end is not None:
        parts.append(f"{cel_field} < {_cel_timestamp(end)}")
    if not parts:
        return None
    return " && ".join(parts)


def combine_cel_clauses(*clauses: str | None) -> str | None:
    """以 `&&` 组合非空 CEL 子句，必要时加括号保证优先级。"""
    parts = [f"({clause})" for clause in clauses if clause]
    if not parts:
        return None
    return " && ".join(parts)


def parse_date_bound(
    raw: str | None,
    *,
    is_end: bool,
    tz: timezone | None = None,
) -> datetime | None:
    """解析日期上下界为 UTC datetime，语义为半开区间 `[start, end)`。

    支持 `YYYY-MM-DD` 与 ISO8601：
    - 起始：当天本地 00:00:00
    - 结束：次日本地 00:00:00（因此结束日全天被包含）

    该函数不依赖本地时区推断，便于测试与跨环境行为一致。
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    local_tz = tz or datetime.now().astimezone().tzinfo or timezone.utc
    try:
        if len(text) == 10:
            day = date.fromisoformat(text)
            dt = datetime.combine(day, time(0, 0, 0), tzinfo=local_tz)
            if is_end:
                dt = dt + timedelta(days=1)
        else:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=local_tz)
        return dt.astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(f"invalid date format: {raw}") from exc
