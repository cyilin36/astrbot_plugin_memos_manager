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

# MIME 到扩展名的兜底映射：当文件名没有扩展名、但能确定 MIME 时用于补全。
# Memos 的 validateFilename 拒绝以点或空格开头/结尾的文件名，且附件类型依赖
# 扩展名或内容嗅探，因此补全扩展名能提升识别成功率。
MIME_EXTENSION_FALLBACK = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
    "image/tiff": ".tiff",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def normalize_image_filename(
    filename: str | None,
    mime_type: str = "",
    index: int = 1,
) -> str:
    """清洗附件文件名，保证符合 Memos v0.31 的 validateFilename 规则。

    服务端会拒绝：包含路径分隔符、以点或空格开头/结尾、以及路径穿越的名字。
    这里同时剥离 URL 可能带上的查询串/片段，并在缺少扩展名时按 MIME 补全。
    """
    raw = str(filename or "").strip().replace("\\", "_").replace("/", "_")
    # 剥离可能的目录前缀残留与 URL 的查询串/片段。
    raw = raw.rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0].strip()
    # 服务端拒绝以点/空格开头或结尾的名字；先归一化再判断扩展名，
    # 否则空名字会被拼成 ".png" 并被 strip 成 "png"。
    raw = raw.strip(" .")
    if not raw:
        raw = f"image_{index}"

    if "." not in raw or raw.endswith("."):
        raw = f"{raw}{MIME_EXTENSION_FALLBACK.get(mime_type, '.png')}"

    return raw


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


def escape_cel_string(value: str) -> str:
    """转义 CEL 字符串字面量中的特殊字符。

    filter 是拼接出来的 CEL 表达式（如 `filename.contains("...")`），
    用户关键词里的引号或反斜杠会破坏表达式结构，必须转义。
    反斜杠要最先处理，否则会把后续插入的转义符再次转义。
    """
    text = str(value)
    # 控制字符（含换行/制表）在 CEL 单行字面量里没有意义，统一折叠为空格。
    text = "".join(" " if ch in "\r\n\t" else ch for ch in text)
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    return text


def build_attachment_filter_clause(
    *,
    query: str | None = None,
    image_only: bool = False,
    unbound_only: bool = False,
) -> str | None:
    """构建附件全局搜索（GET /api/v1/attachments）的 CEL filter 子句。

    可用字段（见 filter/schema.go 的 NewAttachmentSchema）：
    - filename：支持 contains
    - mime_type：对应存储列 attachment.type，支持 contains
    - memo_id：仅支持 == / !=，`== null` 渲染为 IS NULL

    无任何筛选时返回 None，避免发送空 filter。
    """
    clauses: list[str] = []

    keyword = (query or "").strip()
    if keyword:
        clauses.append(f'filename.contains("{escape_cel_string(keyword)}")')

    if image_only:
        clauses.append('mime_type.contains("image/")')

    if unbound_only:
        # 未绑定 memo 的附件：memo_id 为 NULL。
        clauses.append("memo_id == null")

    return combine_cel_clauses(*clauses)


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
