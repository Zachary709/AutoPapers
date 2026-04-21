from __future__ import annotations

from datetime import datetime, timezone
import difflib
import hashlib
import os
from pathlib import Path
import re
from typing import Iterable


INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
ARXIV_ID_PATTERN = re.compile(
    r"(?:(?:arxiv:)|(?:https?://arxiv\.org/(?:abs|pdf)/))?"
    r"(?P<identifier>\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)
OPENREVIEW_ID_PATTERN = re.compile(
    r"(?:https?://openreview\.net/(?:forum|pdf)\?id=)?(?P<identifier>[A-Za-z0-9_-]{6,})",
    re.IGNORECASE,
)
MULTI_REFERENCE_SPLIT_PATTERN = re.compile(
    r"\s*(?:；|;|\n+|\s+和\s+|\s+以及\s+|\s+与\s+|\s+vs\.?\s+|\s+versus\s+)\s*",
    re.IGNORECASE,
)
NUMBERED_REFERENCE_ITEM_PATTERN = re.compile(
    r"(?:^|\s)(?:\d{1,2}\s*[.)、])\s*(.+?)(?=(?:\s+\d{1,2}\s*[.)、]\s+)|$)",
    re.IGNORECASE,
)
QUOTED_REFERENCE_PATTERN = re.compile(r"[\"“‘《](.+?)[\"”’》]")
LEADING_REFERENCE_PREFIX_PATTERN = re.compile(
    r"^(?:请|请你|帮我|帮忙|麻烦|可以|能否|想请你)?\s*"
    r"(?:(?:详细)?(?:介绍|解释|讲讲|总结|概述|分析|比较|对比)|(?:explain|introduce|summarize|compare))\s*"
    r"(?:一下|下)?\s*(?:这个|这篇|这些|这两篇|两篇|多篇)?\s*(?:论文|paper|papers)?\s*",
    re.IGNORECASE,
)
TRAILING_REFERENCE_SUFFIX_PATTERN = re.compile(
    r"\s*(?:这篇论文|该论文|这些论文|paper|papers|的异同|异同|区别|联系)\s*$",
    re.IGNORECASE,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    _write_atomic(path, content.encode(encoding))


def write_bytes_atomic(path: Path, content: bytes) -> None:
    _write_atomic(path, content)


def _write_atomic(path: Path, content: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.name}.tmp")
    with tmp_path.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, target)


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


def parse_arxiv_id(value: str) -> str | None:
    match = ARXIV_ID_PATTERN.search(value)
    if not match:
        return None
    identifier = match.group("identifier")
    return identifier.split("v", 1)[0]


def parse_openreview_id(value: str) -> str | None:
    match = OPENREVIEW_ID_PATTERN.search(value)
    if not match:
        return None
    return match.group("identifier")


def extract_paper_reference_text(text: str) -> str:
    references = extract_paper_reference_texts(text)
    if references:
        return references[0]
    return _extract_single_reference(text)


def extract_paper_reference_texts(text: str) -> list[str]:
    normalized = normalize_whitespace(text)
    explicit_refs = _unique_preserving_order(
        [
            *[match.group("identifier").split("v", 1)[0] for match in ARXIV_ID_PATTERN.finditer(normalized)],
            *[
                _extract_single_reference(match.group(1))
                for match in QUOTED_REFERENCE_PATTERN.finditer(normalized)
            ],
        ]
    )
    explicit_refs = [reference for reference in explicit_refs if reference]
    if len(explicit_refs) > 1:
        return explicit_refs

    normalized = _strip_reference_prefix(normalized)
    numbered_refs = _extract_numbered_references(normalized)
    if len(numbered_refs) > 1:
        return numbered_refs

    if _looks_like_multi_reference(normalized):
        references = _unique_preserving_order(
            [
                _extract_single_reference(part)
                for part in MULTI_REFERENCE_SPLIT_PATTERN.split(normalized)
                if normalize_whitespace(part)
            ]
        )
        references = [reference for reference in references if reference]
        if len(references) > 1:
            return references

    single = explicit_refs[:1] or [_extract_single_reference(normalized)]
    return [reference for reference in single if reference]


def unique_by_arxiv_id(records: Iterable) -> list:
    return unique_by_paper_identity(records)


def unique_by_paper_identity(records: Iterable) -> list:
    seen: set[str] = set()
    unique_records = []
    for record in records:
        paper = record.paper if hasattr(record, "paper") else record
        identifier = paper_identity_key(paper)
        if identifier in seen:
            continue
        seen.add(identifier)
        unique_records.append(record)
    return unique_records


def paper_identity_key(paper) -> str:
    doi = normalize_whitespace(getattr(paper, "doi", ""))
    if doi:
        return f"doi:{doi.casefold()}"
    arxiv_id = normalize_whitespace(getattr(paper, "arxiv_id", ""))
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    openreview_id = normalize_whitespace(getattr(paper, "openreview_id", ""))
    if openreview_id:
        return f"openreview:{openreview_id}"
    forum_id = normalize_whitespace(getattr(paper, "openreview_forum_id", ""))
    if forum_id:
        return f"openreview-forum:{forum_id}"
    scholar_url = normalize_whitespace(getattr(paper, "scholar_url", ""))
    if scholar_url:
        return f"scholar:{scholar_url}"
    title_key = normalize_title_key(getattr(paper, "title", ""))
    year = venue_or_published_year(paper) or ""
    return f"title:{title_key}:{year}"


def venue_or_published_year(paper) -> int | None:
    venue = getattr(paper, "venue", None)
    venue_year = getattr(venue, "year", None) if venue is not None else None
    if venue_year:
        return int(venue_year)
    published = normalize_whitespace(getattr(paper, "published", ""))
    if len(published) >= 4 and published[:4].isdigit():
        return int(published[:4])
    return None


def make_scholar_paper_id(title: str, scholar_url: str = "") -> str:
    basis = normalize_whitespace(scholar_url or title).casefold()
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"scholar:{digest}"


def title_similarity(left: str, right: str) -> float:
    left_key = normalize_title_key(left)
    right_key = normalize_title_key(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    if left_key in right_key or right_key in left_key:
        return 0.92
    left_tokens = set(left_key.split())
    right_tokens = set(right_key.split())
    overlap = len(left_tokens & right_tokens)
    token_score = overlap / max(len(left_tokens | right_tokens), 1) if overlap else 0.0
    ratio = difflib.SequenceMatcher(None, left_key, right_key).ratio()
    return max(ratio, token_score)


def word_similarity(left: str, right: str) -> float:
    left_tokens = _word_tokens(left)
    right_tokens = _word_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(set(left_tokens) & set(right_tokens))
    if overlap == 0:
        return 0.0
    precision = overlap / len(set(right_tokens))
    recall = overlap / len(set(left_tokens))
    if precision + recall == 0:
        return 0.0
    f1 = (2 * precision * recall) / (precision + recall)
    return max(f1, title_similarity(left, right))


def _word_tokens(text: str) -> list[str]:
    normalized = normalize_title_key(text)
    if not normalized:
        return []
    return [token for token in normalized.split() if len(token) > 1]


def _looks_like_reference_prefix(prefix: str) -> bool:
    lowered = prefix.casefold()
    return any(
        marker in lowered
        for marker in (
            "介绍",
            "解释",
            "讲讲",
            "总结",
            "概述",
            "分析",
            "论文",
            "paper",
            "explain",
            "introduce",
            "summarize",
        )
    )


def _extract_single_reference(text: str) -> str:
    normalized = normalize_whitespace(text)
    arxiv_id = parse_arxiv_id(normalized)
    if arxiv_id:
        return arxiv_id

    quoted = QUOTED_REFERENCE_PATTERN.search(normalized)
    if quoted:
        return normalize_whitespace(quoted.group(1))

    normalized = _strip_reference_prefix(normalized)
    normalized = LEADING_REFERENCE_PREFIX_PATTERN.sub("", normalized)
    normalized = TRAILING_REFERENCE_SUFFIX_PATTERN.sub("", normalized)
    return normalize_whitespace(normalized.strip(" \"'“”‘’[]()（）《》"))


def _strip_reference_prefix(text: str) -> str:
    normalized = normalize_whitespace(text)
    for separator in ("：", ":"):
        if separator in normalized:
            prefix, suffix = normalized.split(separator, 1)
            if suffix.strip() and _looks_like_reference_prefix(prefix):
                return normalize_whitespace(suffix)
    return normalized


def _looks_like_multi_reference(text: str) -> bool:
    quoted_references = QUOTED_REFERENCE_PATTERN.findall(text)
    if len(quoted_references) > 1:
        return True
    return bool(MULTI_REFERENCE_SPLIT_PATTERN.search(text))


def _extract_numbered_references(text: str) -> list[str]:
    return _unique_preserving_order(
        [
            _extract_single_reference(match.group(1))
            for match in NUMBERED_REFERENCE_ITEM_PATTERN.finditer(text)
            if normalize_whitespace(match.group(1))
        ]
    )


def _unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        normalized = normalize_whitespace(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_values.append(normalized)
    return unique_values
