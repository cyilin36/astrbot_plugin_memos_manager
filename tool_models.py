from __future__ import annotations


VISIBILITY_LABELS = {"workspace", "private", "public"}


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
