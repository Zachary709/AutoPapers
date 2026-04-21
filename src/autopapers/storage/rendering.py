from __future__ import annotations

from collections import Counter, defaultdict
import os
from pathlib import Path
import re

from autopapers.common.text_normalization import normalize_whitespace, sanitize_path_component, utc_now_iso
from autopapers.models import Paper, StoredPaper


def render_paper_markdown(library, stored: StoredPaper, related_papers: list[StoredPaper]) -> str:
    md_file_path = library.repo_root / stored.md_path
    note_dir = md_file_path.parent
    pdf_absolute = library.repo_root / stored.pdf_path
    pdf_link = ""
    if pdf_absolute.exists():
        pdf_relative = Path(stored.pdf_path).name
        pdf_link = f"[{Path(pdf_relative).name}]({pdf_relative})"

    related_lines = []
    for record in related_papers[:5]:
        target_path = library.repo_root / record.md_path
        link_target = relative_between(note_dir, target_path)
        related_lines.append(f"- [{record.paper.title}]({link_target}) | {record.digest.one_sentence_takeaway}")
    if not related_lines:
        related_lines.append("- 暂无。")

    keywords = ", ".join(stored.digest.keywords)
    abstract_zh = derive_abstract_zh(stored)
    identity_lines = [
        f"- Paper ID: `{stored.paper.paper_id}`",
        f"- Source: {stored.paper.source_primary}",
    ]
    if stored.paper.arxiv_id:
        identity_lines.append(f"- arXiv ID: `{stored.paper.versioned_id or stored.paper.arxiv_id}`")

    publication_lines = [f"- Published: {stored.paper.published}"]
    if stored.paper.venue.name:
        publication_lines.append(f"- Venue: {format_venue_line(stored.paper)}")
    if stored.paper.citation_count is not None:
        publication_lines.append(f"- Citations: {format_citation_line(stored.paper)}")

    research_lines = [f"- Authors: {', '.join(stored.paper.authors)}"]
    research_lines.append(f"- Topics: {stored.digest.major_topic} / {stored.digest.minor_topic}")
    if keywords:
        research_lines.append(f"- Keywords: {keywords}")

    access_lines: list[str] = []
    if pdf_link:
        access_lines.append(f"- PDF: {pdf_link}")
    if stored.paper.entry_url or stored.paper.entry_id:
        access_lines.append(f"- Entry: {stored.paper.entry_url or stored.paper.entry_id}")
    if stored.paper.openreview_url:
        access_lines.append(f"- OpenReview: {stored.paper.openreview_url}")
    if stored.paper.scholar_url:
        access_lines.append(f"- Google Scholar: {stored.paper.scholar_url}")

    lines = [
        f"# {stored.paper.title}",
        "",
        "## Paper Snapshot",
        "",
        "### Identity",
        "",
        *identity_lines,
        "",
        "### Publication",
        "",
        *publication_lines,
        "",
        "### Research Context",
        "",
        *research_lines,
        "",
    ]
    if access_lines:
        lines.extend([
            "### Access",
            "",
            *access_lines,
            "",
        ])
    lines.extend([
        "## 中文摘要",
        "",
        abstract_zh or "暂无中文摘要。",
        "",
        "## English Abstract",
        "",
        stored.paper.abstract,
        "",
    ])
    append_markdown_section(lines, "一句话概括", stored.digest.one_sentence_takeaway)
    append_markdown_section(lines, "论文在做什么", stored.digest.problem)
    append_markdown_section(lines, "直觉上为什么成立", stored.digest.background)
    append_markdown_section(lines, "方法怎么理解", stored.digest.method)
    append_markdown_section(lines, "实验怎么设置", stored.digest.experiment_setup)
    append_markdown_list_section(lines, "实验里最值得关注的点", stored.digest.findings)
    append_markdown_section(lines, "这篇论文的价值", stored.digest.relevance)
    append_markdown_list_section(lines, "局限", stored.digest.limitations)
    append_markdown_list_section(lines, "可以怎么优化", stored.digest.improvement_ideas)
    lines.append("## Related Local Papers")
    lines.append("")
    lines.extend(related_lines)
    lines.append("")
    return "\n".join(lines)


def render_root_summary(records: list[StoredPaper]) -> str:
    lines = ["# AutoPapers Library", ""]
    lines.append(f"- Updated at: {utc_now_iso()}")
    lines.append(f"- Total papers: {len(records)}")
    lines.append("")
    if not records:
        lines.append("Library is currently empty.")
        return "\n".join(lines) + "\n"
    by_major: dict[str, list[StoredPaper]] = defaultdict(list)
    for record in records:
        by_major[record.digest.major_topic].append(record)
    lines.append("## Major Topics")
    lines.append("")
    for major_topic in sorted(by_major):
        major_dir = sanitize_path_component(major_topic)
        minor_count = len({record.digest.minor_topic for record in by_major[major_topic]})
        lines.append(f"- [{major_topic}](./{major_dir}/README.md): {len(by_major[major_topic])} papers, {minor_count} minor topics")
    lines.append("")
    return "\n".join(lines)


def render_major_summary(major_topic: str, records: list[StoredPaper]) -> str:
    lines = [f"# {major_topic}", ""]
    lines.append(f"- Total papers: {len(records)}")
    lines.append(f"- Minor topics: {len({record.digest.minor_topic for record in records})}")
    lines.append("")
    lines.append("## Minor Topics")
    lines.append("")
    by_minor: dict[str, list[StoredPaper]] = defaultdict(list)
    for record in records:
        by_minor[record.digest.minor_topic].append(record)
    for minor_topic in sorted(by_minor):
        minor_dir = sanitize_path_component(minor_topic)
        lines.append(f"- [{minor_topic}](./{minor_dir}/README.md): {len(by_minor[minor_topic])} papers")
    lines.append("")
    lines.append("## Representative Papers")
    lines.append("")
    for record in records[:8]:
        minor_dir = sanitize_path_component(record.digest.minor_topic)
        md_name = Path(record.md_path).name
        lines.append(f"- [{record.paper.title}](./{minor_dir}/{md_name}): {record.digest.one_sentence_takeaway}")
    lines.append("")
    return "\n".join(lines)


def render_minor_summary(major_topic: str, minor_topic: str, records: list[StoredPaper]) -> str:
    keyword_counter = Counter()
    for record in records:
        keyword_counter.update(record.digest.keywords)
    lines = [f"# {major_topic} / {minor_topic}", ""]
    lines.append(f"- Total papers: {len(records)}")
    if keyword_counter:
        lines.append(f"- Frequent keywords: {', '.join(keyword for keyword, _ in keyword_counter.most_common(10))}")
    lines.append("")
    lines.append("## Papers")
    lines.append("")
    for record in records:
        relative_name = Path(record.md_path).name
        lines.append(f"### [{record.paper.title}](./{relative_name})")
        lines.append(f"- Source: {record.paper.source_primary}")
        if record.paper.arxiv_id:
            lines.append(f"- arXiv: `{record.paper.versioned_id or record.paper.arxiv_id}`")
        lines.append(f"- Published: {record.paper.published}")
        lines.append(f"- Venue: {format_venue_line(record.paper)}")
        lines.append(f"- Citations: {format_citation_line(record.paper)}")
        lines.append(f"- Takeaway: {record.digest.one_sentence_takeaway}")
        lines.append("")
    return "\n".join(lines)


def format_venue_line(paper: Paper) -> str:
    if paper.venue.name:
        year = f" ({paper.venue.year})" if paper.venue.year else ""
        kind = f" [{paper.venue.kind}]" if paper.venue.kind else ""
        return f"{paper.venue.name}{year}{kind}"
    return "unavailable"


def format_citation_line(paper: Paper) -> str:
    if paper.citation_count is None:
        return "unavailable"
    updated = f" | updated {paper.citation_updated_at}" if paper.citation_updated_at else ""
    source = f" | source {paper.citation_source}" if paper.citation_source else ""
    return f"{paper.citation_count}{source}{updated}"


def derive_abstract_zh(stored: StoredPaper) -> str:
    if normalize_whitespace(stored.digest.abstract_zh):
        return normalize_whitespace(stored.digest.abstract_zh)
    if normalize_whitespace(stored.paper.abstract) and re.search(r"[\u4e00-\u9fff]", stored.paper.abstract):
        return normalize_whitespace(stored.paper.abstract)
    return ""


def relative_between(from_dir: Path, to_path: Path) -> str:
    return Path(os.path.relpath(to_path, start=from_dir)).as_posix()


def prepare_markdown_section_body(body: str) -> str:
    raw = str(body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return ""
    text = raw
    text = re.sub(r"\s*(\$\$.*?\$\$)\s*", r"\n\n\1\n\n", text, flags=re.S)
    text = re.sub(r"(?<!^)(?=【[^】]+】)", "\n\n", text)
    text = re.sub(r"([：:])\s+(?=(?:\d+\.\s+\*\*|\d+\.\s+|[-*]\s+\*\*))", r"\1\n\n", text)
    text = re.sub(r"\s+(?=(?:\d+\.\s+\*\*|\d+\.\s+[\u4e00-\u9fffA-Za-z]|[-*]\s+\*\*))", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = []
    for line in text.split("\n"):
        normalized = normalize_whitespace(line) if line.strip() else ""
        if normalized in {"#", "##", "###", "####"}:
            normalized = ""
        lines.append(normalized)
    lines = normalize_numbered_heading_lines(lines)
    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        if not line:
            blank_run += 1
            if blank_run <= 2 and cleaned:
                cleaned.append("")
            continue
        blank_run = 0
        cleaned.append(line)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned).strip()


def normalize_numbered_heading_lines(lines: list[str]) -> list[str]:
    normalized_lines: list[str] = []
    for index, line in enumerate(lines):
        if not line:
            normalized_lines.append(line)
            continue
        previous_index, previous_nonempty = neighbor_nonempty_line(lines, index, step=-1)
        next_index, next_nonempty = neighbor_nonempty_line(lines, index, step=1)
        normalized_lines.append(
            normalize_numbered_heading_line(
                line,
                previous_nonempty=previous_nonempty,
                next_nonempty=next_nonempty,
                previous_gap=(index - previous_index - 1) if previous_index is not None else 0,
                next_gap=(next_index - index - 1) if next_index is not None else 0,
            )
        )
    return normalized_lines


def neighbor_nonempty_line(lines: list[str], index: int, *, step: int) -> tuple[int | None, str]:
    cursor = index + step
    while 0 <= cursor < len(lines):
        candidate = lines[cursor].strip()
        if candidate:
            return cursor, candidate
        cursor += step
    return None, ""


def normalize_numbered_heading_line(
    line: str,
    *,
    previous_nonempty: str,
    next_nonempty: str,
    previous_gap: int,
    next_gap: int,
) -> str:
    explicit_heading = re.match(r"^(#{1,6})\s+((?:\d+\.)+\d+|\d+\.)\s+(.+)$", line)
    if explicit_heading:
        return f"{explicit_heading.group(1)} {explicit_heading.group(3).strip()}"

    multilevel_match = re.match(r"^((?:\d+\.)+\d+)\s+(.+)$", line)
    if multilevel_match:
        title = multilevel_match.group(2).strip()
        if looks_like_standalone_numbered_heading(
            title,
            previous_nonempty=previous_nonempty,
            next_nonempty=next_nonempty,
            previous_gap=previous_gap,
            next_gap=next_gap,
        ):
            level = min(6, 2 + len(multilevel_match.group(1).split(".")))
            return f"{'#' * level} {title}"

    single_level_match = re.match(r"^(\d+)\.\s+(.+)$", line)
    if single_level_match:
        title = single_level_match.group(2).strip()
        if looks_like_standalone_numbered_heading(
            title,
            previous_nonempty=previous_nonempty,
            next_nonempty=next_nonempty,
            previous_gap=previous_gap,
            next_gap=next_gap,
        ):
            return f"### {title}"
        previous_ordered_index = ordered_list_index(previous_nonempty)
        if (
            previous_gap > 0
            and previous_ordered_index is not None
            and ordered_list_index(next_nonempty) is None
            and int(single_level_match.group(1)) <= previous_ordered_index
            and looks_like_standalone_numbered_heading(
                title,
                previous_nonempty="",
                next_nonempty=next_nonempty,
                previous_gap=0,
                next_gap=next_gap,
            )
        ):
            return f"### {title}"
    return line


def looks_like_standalone_numbered_heading(
    title: str,
    *,
    previous_nonempty: str,
    next_nonempty: str,
    previous_gap: int,
    next_gap: int,
) -> bool:
    normalized = normalize_whitespace(title)
    if not normalized:
        return False
    if len(normalized) > 48:
        return False
    if any(token in normalized for token in ("**", "$$", "$", "`")):
        return False
    if re.search(r"[。！？!?；;]$", normalized):
        return False
    if re.search(r"[：:].{18,}$", normalized):
        return False
    if previous_gap == 0 and is_ordered_list_like(previous_nonempty):
        return False
    if next_gap == 0 and is_ordered_list_like(next_nonempty):
        return False
    if is_ordered_list_like(previous_nonempty) or is_ordered_list_like(next_nonempty):
        return False
    return True


def is_ordered_list_like(line: str) -> bool:
    return bool(re.match(r"^\d+\.\s+.+$", line))


def ordered_list_index(line: str) -> int | None:
    match = re.match(r"^(\d+)\.\s+.+$", line)
    if not match:
        return None
    return int(match.group(1))


def append_markdown_section(lines: list[str], title: str, body: str) -> None:
    formatted = prepare_markdown_section_body(body)
    if not formatted:
        return
    lines.extend([f"## {title}", "", formatted, ""])


def append_markdown_list_section(lines: list[str], title: str, items: list[str]) -> None:
    normalized_items = [normalize_whitespace(item) for item in items if normalize_whitespace(item)]
    if not normalized_items:
        return
    lines.extend([f"## {title}", ""])
    lines.extend(f"- {item}" for item in normalized_items)
    lines.append("")
