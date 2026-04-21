from __future__ import annotations

import difflib
import hashlib
from typing import Iterable

from autopapers.common.text_normalization import normalize_title_key, normalize_whitespace


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
