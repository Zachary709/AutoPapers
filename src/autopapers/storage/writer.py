from __future__ import annotations

from collections import defaultdict
import json
import shutil
from pathlib import Path

from autopapers.common.atomic_io import write_bytes_atomic, write_text_atomic
from autopapers.common.text_normalization import sanitize_path_component, utc_now_iso
from autopapers.models import Paper, PaperDigest, StoredPaper
from autopapers.storage.rendering import render_major_summary, render_minor_summary, render_paper_markdown, render_root_summary


def upsert_paper(library, paper: Paper, digest: PaperDigest, pdf_bytes: bytes, related_papers: list[StoredPaper]) -> StoredPaper:
    major_dir = library.root / sanitize_path_component(digest.major_topic)
    minor_dir = major_dir / sanitize_path_component(digest.minor_topic)
    minor_dir.mkdir(parents=True, exist_ok=True)
    stem = paper_stem(paper)
    pdf_path = minor_dir / f"{stem}.pdf"
    md_path = minor_dir / f"{stem}.md"
    metadata_path = minor_dir / f"{stem}.metadata.json"

    existing = library._records.get(paper.paper_id)
    preserved_pdf_bytes = b""
    if existing:
        existing_pdf_path = library.repo_root / existing.pdf_path
        if not pdf_bytes and existing_pdf_path.exists():
            preserved_pdf_bytes = existing_pdf_path.read_bytes()
        cleanup_previous_files(library, existing, {pdf_path, md_path, metadata_path})

    effective_pdf_bytes = pdf_bytes or preserved_pdf_bytes
    if effective_pdf_bytes:
        write_bytes_atomic(pdf_path, effective_pdf_bytes)

    stored = StoredPaper(
        paper=paper,
        digest=digest,
        stored_at=utc_now_iso(),
        pdf_path=library._to_repo_relative(pdf_path),
        md_path=library._to_repo_relative(md_path),
        metadata_path=library._to_repo_relative(metadata_path),
    )
    write_text_atomic(md_path, render_paper_markdown(library, stored, related_papers), encoding="utf-8")
    write_text_atomic(
        metadata_path,
        json.dumps(stored.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    library._records[paper.paper_id] = stored
    library._save_index()
    refresh_summaries(library)
    return stored


def rewrite_digest(
    library,
    paper_id: str,
    digest: PaperDigest,
    related_papers: list[StoredPaper],
    *,
    refresh_summaries_enabled: bool = True,
) -> StoredPaper:
    library._reload_index_if_changed()
    existing = library._records.get(paper_id)
    if existing is None:
        raise KeyError(f"Unknown paper_id: {paper_id}")
    stored = StoredPaper(
        paper=existing.paper,
        digest=digest,
        stored_at=existing.stored_at,
        pdf_path=existing.pdf_path,
        md_path=existing.md_path,
        metadata_path=existing.metadata_path,
    )
    markdown_path = library.repo_root / stored.md_path
    metadata_path = library.repo_root / stored.metadata_path
    write_text_atomic(markdown_path, render_paper_markdown(library, stored, related_papers), encoding="utf-8")
    write_text_atomic(
        metadata_path,
        json.dumps(stored.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    library._records[paper_id] = stored
    library._save_index()
    if refresh_summaries_enabled:
        refresh_summaries(library)
    return stored


def delete_paper(library, paper_id: str) -> bool:
    existing = library._records.pop(paper_id, None)
    if existing is None:
        return False
    for relative_path in (existing.pdf_path, existing.md_path, existing.metadata_path):
        absolute = library.repo_root / relative_path
        if absolute.exists() and library.root in absolute.parents:
            absolute.unlink()
    library._save_index()
    refresh_summaries(library)
    return True


def refresh_summaries(library) -> None:
    library.root.mkdir(parents=True, exist_ok=True)
    records = sorted(library._records.values(), key=lambda item: item.paper.published, reverse=True)
    by_major: dict[str, list[StoredPaper]] = defaultdict(list)
    by_minor: dict[tuple[str, str], list[StoredPaper]] = defaultdict(list)
    for record in records:
        by_major[record.digest.major_topic].append(record)
        by_minor[(record.digest.major_topic, record.digest.minor_topic)].append(record)

    active_major_dirs = {library.root / sanitize_path_component(major_topic) for major_topic in by_major}
    active_minor_dirs = {
        library.root / sanitize_path_component(major_topic) / sanitize_path_component(minor_topic)
        for (major_topic, minor_topic) in by_minor
    }
    remove_stale_topic_dirs(library, active_major_dirs, active_minor_dirs)
    write_text_atomic(library.root / "README.md", render_root_summary(records), encoding="utf-8")

    for major_topic, major_records in by_major.items():
        major_dir = library.root / sanitize_path_component(major_topic)
        major_dir.mkdir(parents=True, exist_ok=True)
        write_text_atomic(
            major_dir / "README.md",
            render_major_summary(major_topic, major_records),
            encoding="utf-8",
        )

    for (major_topic, minor_topic), minor_records in by_minor.items():
        minor_dir = library.root / sanitize_path_component(major_topic) / sanitize_path_component(minor_topic)
        minor_dir.mkdir(parents=True, exist_ok=True)
        write_text_atomic(
            minor_dir / "README.md",
            render_minor_summary(major_topic, minor_topic, minor_records),
            encoding="utf-8",
        )


def paper_stem(paper: Paper) -> str:
    title_slug = sanitize_path_component(paper.title, max_length=60)
    return sanitize_path_component(f"{paper.paper_id}_{title_slug}", max_length=96)


def cleanup_previous_files(library, existing: StoredPaper, keep: set[Path]) -> None:
    for relative_path in (existing.pdf_path, existing.md_path, existing.metadata_path):
        absolute = library.repo_root / relative_path
        if absolute in keep:
            continue
        if absolute.exists() and library.root in absolute.parents:
            absolute.unlink()


def remove_stale_topic_dirs(library, active_major_dirs: set[Path], active_minor_dirs: set[Path]) -> None:
    for child in library.root.iterdir():
        if child.is_dir() and child not in active_major_dirs:
            shutil.rmtree(child, ignore_errors=True)
    for major_dir in active_major_dirs:
        if not major_dir.exists():
            continue
        for child in major_dir.iterdir():
            if child.is_dir() and child not in active_minor_dirs:
                shutil.rmtree(child, ignore_errors=True)
