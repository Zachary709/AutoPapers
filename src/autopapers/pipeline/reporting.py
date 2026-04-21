from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from autopapers.common.reference_parsing import extract_paper_reference_text, extract_paper_reference_texts
from autopapers.common.text_normalization import normalize_title_key, sanitize_path_component, truncate_text
from autopapers.common.atomic_io import write_text_atomic
from autopapers.models import RequestPlan, StoredPaper


def build_related_query(
    plan: RequestPlan,
    user_request: str,
    new_papers: list[StoredPaper],
    reused_papers: list[StoredPaper],
) -> str:
    if plan.search_query:
        return plan.search_query
    if plan.intent == "explain_paper":
        references = plan.paper_refs or extract_paper_reference_texts(user_request)
        cleaned_refs = [extract_paper_reference_text(reference) for reference in references if reference]
        combined = " ".join(cleaned_refs[:4]).strip()
        if combined:
            return combined
        if new_papers:
            return new_papers[0].paper.title
        if reused_papers:
            return reused_papers[0].paper.title
    return user_request


def render_report(
    user_request: str,
    plan: RequestPlan,
    new_papers: list[StoredPaper],
    reused_papers: list[StoredPaper],
    related_papers: list[StoredPaper],
) -> str:
    lines = ["# AutoPapers Report", ""]
    lines.append("## Request")
    lines.append("")
    lines.append(user_request.strip())
    lines.append("")
    lines.append("## Plan")
    lines.append("")
    lines.append(f"- Intent: {plan.intent}")
    lines.append(f"- Goal: {plan.user_goal}")
    if plan.search_query:
        lines.append(f"- Search query: {plan.search_query}")
    if plan.paper_refs:
        lines.append(f"- Paper refs: {', '.join(plan.paper_refs)}")
    lines.append(f"- Max results: {plan.max_results}")
    if plan.rationale:
        lines.append(f"- Rationale: {plan.rationale}")
    lines.append("")

    lines.append("## New Or Refreshed Papers")
    lines.append("")
    if not new_papers:
        lines.append("- None.")
    else:
        for record in new_papers:
            lines.extend(paper_report_block(record))
    lines.append("")

    lines.append("## Directly Reused Local Papers")
    lines.append("")
    if not reused_papers:
        lines.append("- None.")
    else:
        for record in reused_papers:
            lines.extend(paper_report_block(record))
    lines.append("")

    compared_records = [*new_papers, *reused_papers]
    if plan.intent == "explain_paper" and len(compared_records) > 1:
        lines.append("## Multi-Paper Comparison")
        lines.append("")
        lines.extend(comparison_report_block(compared_records))
        lines.append("")

    lines.append("## Additional Related Local Papers")
    lines.append("")
    if not related_papers:
        lines.append("- None.")
    else:
        for record in related_papers:
            lines.append(f"- [{record.paper.title}]({record.md_path}): {record.digest.one_sentence_takeaway}")
    lines.append("")
    return "\n".join(lines)


def paper_report_block(record: StoredPaper) -> list[str]:
    lines = [f"### [{record.paper.title}]({record.md_path})"]
    lines.append(f"- Paper ID: `{record.paper.paper_id}`")
    lines.append(f"- Source: {record.paper.source_primary}")
    if record.paper.arxiv_id:
        lines.append(f"- arXiv: `{record.paper.versioned_id or record.paper.arxiv_id}`")
    if record.paper.venue.name:
        venue_year = f" ({record.paper.venue.year})" if record.paper.venue.year else ""
        venue_kind = f" [{record.paper.venue.kind}]" if record.paper.venue.kind else ""
        lines.append(f"- Venue: {record.paper.venue.name}{venue_year}{venue_kind}")
    if record.paper.citation_count is not None:
        lines.append(f"- Citations: {record.paper.citation_count}")
    lines.append(f"- Topics: {record.digest.major_topic} / {record.digest.minor_topic}")
    lines.append(f"- PDF: [{Path(record.pdf_path).name}]({record.pdf_path})")
    lines.append(f"- Takeaway: {record.digest.one_sentence_takeaway}")
    if record.digest.problem:
        lines.append(f"- 论文在做什么: {record.digest.problem}")
    if record.digest.experiment_setup:
        lines.append(f"- 实验怎么设置: {truncate_text(record.digest.experiment_setup, 180)}")
    for finding in record.digest.findings[:4]:
        lines.append(f"- Finding: {finding}")
    return lines


def comparison_report_block(records: list[StoredPaper]) -> list[str]:
    shared_keyword_values = shared_keywords(records)
    major_topics = ordered_unique(record.digest.major_topic for record in records)
    minor_topics = ordered_unique(record.digest.minor_topic for record in records)
    reading_order = suggest_reading_order(records)

    lines = [
        f"- Compared papers: {len(records)}",
        f"- Shared scope: {', '.join(major_topics[:3])}" if major_topics else "- Shared scope: 未归纳出稳定方向",
    ]
    if shared_keyword_values:
        lines.append(f"- Shared keywords: {', '.join(shared_keyword_values[:8])}")
    elif minor_topics:
        lines.append(f"- Topic spread: {', '.join(minor_topics[:6])}")

    for record in records:
        focus = record.digest.problem or record.digest.method or record.digest.one_sentence_takeaway or record.paper.abstract
        lines.append(f"- Focus | {record.paper.title}: {truncate_text(focus, 120)}")

    if len(reading_order) > 1:
        lines.append("- Suggested reading order: " + " -> ".join(record.paper.title for record in reading_order))
    return lines


def shared_keywords(records: list[StoredPaper]) -> list[str]:
    keyword_counter: Counter[str] = Counter()
    keyword_labels: dict[str, str] = {}
    for record in records:
        seen_in_record: set[str] = set()
        for keyword in record.digest.keywords:
            key = normalize_title_key(keyword)
            if not key or key in seen_in_record:
                continue
            seen_in_record.add(key)
            keyword_counter[key] += 1
            keyword_labels.setdefault(key, keyword)
    shared = [keyword_labels[key] for key, count in keyword_counter.items() if count == len(records)]
    if shared:
        return shared
    return [keyword_labels[key] for key, count in keyword_counter.most_common() if count > 1]


def ordered_unique(values) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def suggest_reading_order(records: list[StoredPaper]) -> list[StoredPaper]:
    def sort_key(record: StoredPaper) -> tuple[int, str, str]:
        title_key = record.paper.title.casefold()
        survey_priority = 0 if any(marker in title_key for marker in ("survey", "review", "overview", "tutorial")) else 1
        return (survey_priority, record.paper.published or "", title_key)

    return sorted(records, key=sort_key)


def save_report(agent, user_request: str, markdown: str) -> str:
    agent.settings.reports_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = sanitize_path_component(user_request, max_length=48)
    report_path = agent.settings.reports_root / f"{timestamp}_{name}.md"
    write_text_atomic(report_path, markdown, encoding="utf-8")
    return report_path.relative_to(agent.settings.repo_root).as_posix()
