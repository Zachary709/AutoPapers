from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from autopapers.common.reference_parsing import extract_paper_reference_text
from autopapers.common.text_normalization import normalize_title_key, sanitize_path_component, tokenize, utc_now_iso
from autopapers.common.paper_identity import title_similarity
from autopapers.models import StoredPaper


def get_by_paper_id(library, paper_id: str) -> StoredPaper | None:
    reload = library._reload_index_if_changed
    reload()
    return library._records.get(paper_id)


def get_by_arxiv_id(library, arxiv_id: str) -> StoredPaper | None:
    library._reload_index_if_changed()
    for record in library._records.values():
        if record.paper.arxiv_id == arxiv_id:
            return record
    return None


def find_by_title(library, reference: str) -> StoredPaper | None:
    library._reload_index_if_changed()
    target = normalize_title_key(extract_paper_reference_text(reference))
    if not target:
        return None
    for record in library._records.values():
        if normalize_title_key(record.paper.title) == target:
            return record
    return None


def find_best_title_match(library, reference: str, *, min_score: float = 0.72) -> StoredPaper | None:
    library._reload_index_if_changed()
    extracted = extract_paper_reference_text(reference)
    target = normalize_title_key(extracted)
    if not target:
        return None

    best_record: StoredPaper | None = None
    best_score = 0.0
    for record in library._records.values():
        score = title_similarity(extracted, record.paper.title)
        if score > best_score:
            best_score = score
            best_record = record
    if best_record is not None and best_score >= min_score:
        return best_record
    return None


def all_records(library) -> list[StoredPaper]:
    library._reload_index_if_changed()
    return list(library._records.values())


def search(library, query: str, *, limit: int = 5, exclude_ids: set[str] | None = None) -> list[StoredPaper]:
    library._reload_index_if_changed()
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    scored: list[tuple[int, StoredPaper]] = []
    for record in library._records.values():
        if exclude_ids and record.paper.paper_id in exclude_ids:
            continue
        title_tokens = tokenize(record.paper.title)
        abstract_tokens = tokenize(record.paper.abstract)
        topic_tokens = tokenize(
            " ".join(
                [
                    record.digest.major_topic,
                    record.digest.minor_topic,
                    record.digest.one_sentence_takeaway,
                    record.digest.problem,
                    record.digest.method,
                    record.digest.relevance,
                    " ".join(record.digest.keywords),
                    " ".join(record.digest.findings),
                ]
            )
        )
        score = 4 * len(query_tokens & title_tokens) + 2 * len(query_tokens & topic_tokens) + len(query_tokens & abstract_tokens)
        if query.lower() in record.paper.title.lower():
            score += 10
        if score > 0:
            scored.append((score, record))

    scored.sort(key=lambda item: (-item[0], item[1].paper.published))
    return [record for _, record in scored[:limit]]


def topic_snapshot(library) -> str:
    library._reload_index_if_changed()
    if not library._records:
        return "本地论文库为空。"
    by_major: dict[str, list[StoredPaper]] = defaultdict(list)
    for record in library._records.values():
        by_major[record.digest.major_topic].append(record)
    lines = ["本地论文库概览:"]
    for major_topic in sorted(by_major):
        major_records = sorted(by_major[major_topic], key=lambda item: item.paper.published, reverse=True)
        minor_topics = sorted({record.digest.minor_topic for record in major_records})
        lines.append(f"- {major_topic}: {len(major_records)} 篇论文, 子方向 {', '.join(minor_topics[:5])}")
        for record in major_records[:3]:
            lines.append(f"  - {record.paper.title} | {record.digest.one_sentence_takeaway}")
    return "\n".join(lines)


def list_tree(library) -> dict:
    library._reload_index_if_changed()
    records = sorted(library._records.values(), key=lambda item: item.paper.published, reverse=True)
    by_major: dict[str, dict[str, list[StoredPaper]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        by_major[record.digest.major_topic][record.digest.minor_topic].append(record)

    major_nodes: list[dict] = []
    minor_count = 0
    for major_topic in sorted(by_major):
        minor_nodes: list[dict] = []
        for minor_topic in sorted(by_major[major_topic]):
            papers = [serialize_paper_summary(library, record) for record in by_major[major_topic][minor_topic]]
            minor_nodes.append({"name": minor_topic, "slug": sanitize_path_component(minor_topic), "count": len(papers), "papers": papers})
            minor_count += 1
        major_nodes.append(
            {
                "name": major_topic,
                "slug": sanitize_path_component(major_topic),
                "count": sum(node["count"] for node in minor_nodes),
                "minor_topic_count": len(minor_nodes),
                "minor_topics": minor_nodes,
            }
        )

    return {
        "updated_at": utc_now_iso(),
        "stats": {
            "paper_count": len(records),
            "major_topic_count": len(major_nodes),
            "minor_topic_count": minor_count,
        },
        "major_topics": major_nodes,
    }


def get_paper_detail(library, paper_id: str) -> dict | None:
    library._reload_index_if_changed()
    record = library._records.get(paper_id)
    if record is None:
        return None
    markdown_path = library.repo_root / record.md_path
    metadata_path = library.repo_root / record.metadata_path
    pdf_path = library.repo_root / record.pdf_path
    markdown_content = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
    return {
        "summary": serialize_paper_summary(library, record),
        "paper": asdict(record.paper),
        "digest": asdict(record.digest),
        "stored_at": record.stored_at,
        "paths": {"pdf": record.pdf_path, "markdown": record.md_path, "metadata": record.metadata_path},
        "flags": {
            "pdf_exists": pdf_path.exists(),
            "markdown_exists": markdown_path.exists(),
            "metadata_exists": metadata_path.exists(),
        },
        "markdown_content": markdown_content,
    }


def serialize_paper_summary(library, record: StoredPaper) -> dict:
    pdf_path = library.repo_root / record.pdf_path
    return {
        "paper_id": record.paper.paper_id,
        "arxiv_id": record.paper.arxiv_id,
        "versioned_id": record.paper.versioned_id,
        "source_primary": record.paper.source_primary,
        "title": record.paper.title,
        "published": record.paper.published,
        "stored_at": record.stored_at,
        "authors": record.paper.authors,
        "major_topic": record.digest.major_topic,
        "minor_topic": record.digest.minor_topic,
        "takeaway": record.digest.one_sentence_takeaway,
        "keywords": record.digest.keywords,
        "pdf_available": pdf_path.exists(),
        "venue": {
            "name": record.paper.venue.name,
            "kind": record.paper.venue.kind,
            "year": record.paper.venue.year,
        },
        "citation_count": record.paper.citation_count,
        "citation_updated_at": record.paper.citation_updated_at,
        "links": {
            "entry": record.paper.entry_url or record.paper.entry_id,
            "scholar": record.paper.scholar_url,
            "openreview": record.paper.openreview_url,
        },
    }


def to_repo_relative(library, path) -> str:
    return path.relative_to(library.repo_root).as_posix()
