from __future__ import annotations

from collections import Counter
from typing import Callable

from autopapers.common.paper_identity import paper_identity_key, title_similarity, unique_by_paper_identity, venue_or_published_year
from autopapers.common.text_normalization import truncate_text, utc_now_iso
from autopapers.models import Paper


def enrich_paper_metadata(
    agent,
    paper: Paper,
    *,
    notice_callback: Callable[[str], None] | None = None,
) -> Paper:
    merged, _ = enrich_paper_metadata_with_report(agent, paper, notice_callback=notice_callback)
    return merged


def enrich_paper_metadata_with_report(
    agent,
    paper: Paper,
    *,
    notice_callback: Callable[[str], None] | None = None,
) -> tuple[Paper, list[dict[str, object]]]:
    merged = paper
    source_reports: list[dict[str, object]] = []
    if hasattr(agent, "openreview"):
        try:
            openreview_paper = agent.openreview.enrich_metadata(merged)
            updated = merge_candidate_pair(agent, merged, openreview_paper)
            changed_fields = metadata_field_changes(merged, updated)
            source_reports.append(
                {
                    "source": "OpenReview",
                    "status": "updated" if changed_fields else "unchanged",
                    "message": f"补充了 {'、'.join(changed_fields)}。" if changed_fields else "未返回新的收录或链接信息。",
                    "changed_fields": changed_fields,
                }
            )
            merged = updated
        except Exception as exc:
            source_reports.append(
                {
                    "source": "OpenReview",
                    "status": "error",
                    "message": f"请求失败：{truncate_text(str(exc), 120)}",
                    "changed_fields": [],
                }
            )
            if notice_callback is not None:
                notice_callback(f"OpenReview 元数据补充失败：{truncate_text(paper.title, 72)}")
    if hasattr(agent, "scholar"):
        try:
            if hasattr(agent.scholar, "enrich_metadata_report"):
                scholar_report = agent.scholar.enrich_metadata_report(merged)
                scholar_paper = scholar_report.get("paper", merged)
                updated = merge_candidate_pair(agent, merged, scholar_paper)
                changed_fields = metadata_field_changes(merged, updated)
                fallback_used = scholar_report.get("fallback_used") or ""
                source_reports.append(
                    {
                        "source": "Google Scholar",
                        "status": str(scholar_report.get("status") or ("updated" if changed_fields else "unchanged")),
                        "message": str(
                            scholar_report.get("message")
                            or (f"补充了 {'、'.join(changed_fields)}。" if changed_fields else "未返回新的收录或引用信息。")
                        ),
                        "changed_fields": changed_fields,
                        "fallback_used": fallback_used,
                    }
                )
                merged = updated
            else:
                scholar_paper = agent.scholar.enrich_metadata(merged)
                updated = merge_candidate_pair(agent, merged, scholar_paper)
                changed_fields = metadata_field_changes(merged, updated)
                source_reports.append(
                    {
                        "source": "Google Scholar",
                        "status": "updated" if changed_fields else "unchanged",
                        "message": f"补充了 {'、'.join(changed_fields)}。" if changed_fields else "未返回新的收录或引用信息。",
                        "changed_fields": changed_fields,
                    }
                )
                merged = updated
        except Exception as exc:
            source_reports.append(
                {
                    "source": "Google Scholar",
                    "status": "error",
                    "message": f"请求失败：{truncate_text(str(exc), 120)}",
                    "changed_fields": [],
                }
            )
            if notice_callback is not None:
                notice_callback(f"Scholar 元数据补充失败：{truncate_text(paper.title, 72)}")
    return merged, source_reports


def metadata_field_changes(before: Paper, after: Paper) -> list[str]:
    changes: list[str] = []
    if before.venue.name != after.venue.name or before.venue.kind != after.venue.kind or before.venue.year != after.venue.year:
        changes.append("收录信息")
    if before.citation_count != after.citation_count:
        changes.append("引用量")
    if before.scholar_url != after.scholar_url:
        changes.append("Scholar 链接")
    if before.openreview_url != after.openreview_url:
        changes.append("OpenReview 链接")
    if before.doi != after.doi:
        changes.append("DOI")
    return changes


def build_metadata_refresh_result(
    *,
    paper: Paper,
    source_reports: list[dict[str, object]],
    changed_fields: list[str],
) -> dict[str, object]:
    has_error = any(report["status"] == "error" for report in source_reports)
    if changed_fields:
        status = "updated"
        message = f"已刷新元数据：{'、'.join(changed_fields)}。"
    elif has_error:
        status = "warning"
        message = "未拿到新的元数据；部分来源请求失败或被限流。"
    else:
        status = "unchanged"
        message = "未拿到新的元数据；当前来源没有返回新的收录或引用信息。"
    return {
        "status": status,
        "message": message,
        "changed_fields": changed_fields,
        "updated_at": utc_now_iso(),
        "sources": source_reports,
        "venue_available": bool(paper.venue.name),
        "citation_available": paper.citation_count is not None,
    }


def merge_candidate_lists(agent, current: list[Paper], incoming: list[Paper]) -> list[Paper]:
    merged: dict[str, Paper] = {paper_identity_key(paper): paper for paper in current}
    for paper in incoming:
        identity = paper_identity_key(paper)
        if identity in merged:
            merged[identity] = merge_candidate_pair(agent, merged[identity], paper)
            continue
        title_match_key = find_title_match_key(existing=merged, candidate=paper)
        if title_match_key:
            merged[title_match_key] = merge_candidate_pair(agent, merged[title_match_key], paper)
            continue
        merged[identity] = paper
    return unique_by_paper_identity(merged.values())


def find_title_match_key(*, existing: dict[str, Paper], candidate: Paper) -> str | None:
    candidate_year = venue_or_published_year(candidate)
    for key, paper in existing.items():
        if title_similarity(candidate.title, paper.title) < 0.93:
            continue
        existing_year = venue_or_published_year(paper)
        if candidate_year and existing_year and candidate_year != existing_year:
            continue
        return key
    return None


def merge_candidate_pair(agent, left: Paper, right: Paper) -> Paper:
    if left is right:
        return left
    source_rank = {"arxiv": 3, "openreview": 2, "scholar": 1}
    primary = left if source_rank.get(left.source_primary, 0) >= source_rank.get(right.source_primary, 0) else right
    secondary = right if primary is left else left
    venue = choose_venue(left, right)
    citation_holder = choose_citation_holder(left, right)
    citation_count = citation_holder.citation_count if citation_holder is not None else None
    citation_source = citation_holder.citation_source if citation_holder is not None else ""
    citation_updated_at = citation_holder.citation_updated_at if citation_holder is not None else ""
    source_primary = "arxiv" if (left.arxiv_id or right.arxiv_id) else ("openreview" if (left.openreview_id or right.openreview_id or left.openreview_forum_id or right.openreview_forum_id) else primary.source_primary)
    arxiv_id = left.arxiv_id or right.arxiv_id
    openreview_id = left.openreview_id or right.openreview_id
    openreview_forum_id = left.openreview_forum_id or right.openreview_forum_id
    paper_id = arxiv_id or (f"openreview:{openreview_forum_id or openreview_id}" if (openreview_forum_id or openreview_id) else primary.paper_id)
    pdf_url = choose_pdf_url(left, right)
    entry_url = primary.entry_url or primary.entry_id or secondary.entry_url or secondary.entry_id
    return Paper(
        paper_id=paper_id,
        source_primary=source_primary,
        title=primary.title or secondary.title,
        abstract=primary.abstract or secondary.abstract,
        authors=primary.authors or secondary.authors,
        published=primary.published or secondary.published,
        updated=primary.updated or secondary.updated,
        entry_id=entry_url,
        entry_url=entry_url,
        pdf_url=pdf_url,
        primary_category=primary.primary_category or secondary.primary_category,
        categories=merge_string_lists(left.categories, right.categories),
        arxiv_id=arxiv_id,
        versioned_id=left.versioned_id or right.versioned_id or arxiv_id or "",
        openreview_id=openreview_id,
        openreview_forum_id=openreview_forum_id,
        doi=left.doi or right.doi,
        scholar_url=left.scholar_url or right.scholar_url,
        openreview_url=left.openreview_url or right.openreview_url,
        venue=venue,
        citation_count=citation_count,
        citation_source=citation_source,
        citation_updated_at=citation_updated_at,
    )


def choose_citation_holder(left: Paper, right: Paper) -> Paper | None:
    def rank(paper: Paper) -> tuple[int, int]:
        source_rank = {
            "google_scholar": 3,
            "semantic_scholar": 2,
            "openalex": 1,
            "crossref": 1,
        }
        return (source_rank.get(paper.citation_source or "", 0), 1 if paper.citation_count is not None else 0)

    candidates = [paper for paper in (left, right) if paper.citation_count is not None]
    if not candidates:
        return None
    return max(candidates, key=rank)


def merge_string_lists(left: list[str], right: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*left, *right]:
        normalized = item.strip()
        if not normalized:
            continue
        lowered = normalized.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        merged.append(normalized)
    return merged


def choose_venue(left: Paper, right: Paper):
    ranked = {"openreview": 3, "scholar": 2, "arxiv": 1}
    candidates = sorted([left, right], key=lambda item: ranked.get(item.source_primary, 0), reverse=True)
    for candidate in candidates:
        if candidate.venue.name:
            return candidate.venue
    return candidates[0].venue


def choose_pdf_url(left: Paper, right: Paper) -> str:
    def rank(paper: Paper) -> int:
        if paper.arxiv_id and paper.pdf_url:
            return 3
        if (paper.openreview_id or paper.openreview_forum_id) and paper.pdf_url:
            return 2
        if paper.pdf_url:
            return 1
        return 0

    best = max((left, right), key=rank)
    return best.pdf_url
