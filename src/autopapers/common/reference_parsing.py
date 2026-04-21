from __future__ import annotations

import re
from typing import Iterable

from autopapers.common.text_normalization import normalize_whitespace


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
