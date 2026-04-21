from __future__ import annotations

from datetime import datetime, timezone
import re


INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize_path_component(value: str, max_length: int = 80) -> str:
    cleaned = INVALID_PATH_CHARS.sub(" ", value).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.strip(" ._")
    if not cleaned:
        cleaned = "untitled"
    return cleaned[:max_length]


def truncate_text(text: str, max_chars: int) -> str:
    normalized = normalize_whitespace(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_title_key(text: str) -> str:
    normalized = normalize_whitespace(text).casefold()
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def tokenize(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text)}
