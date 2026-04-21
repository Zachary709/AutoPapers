from __future__ import annotations

from pathlib import Path
from threading import RLock

from autopapers.common.text_normalization import sanitize_path_component
from autopapers.models import Paper, PaperDigest, StoredPaper
from autopapers.storage.index_store import get_index_mtime_ns, load_index, reload_index_if_changed, save_index
from autopapers.storage.queries import (
    all_records,
    find_best_title_match,
    find_by_title,
    get_by_arxiv_id,
    get_by_paper_id,
    get_paper_detail,
    list_tree,
    search,
    serialize_paper_summary,
    to_repo_relative,
    topic_snapshot,
)
from autopapers.storage.rendering import (
    append_markdown_list_section,
    append_markdown_section,
    derive_abstract_zh,
    format_citation_line,
    format_venue_line,
    neighbor_nonempty_line,
    normalize_numbered_heading_line,
    normalize_numbered_heading_lines,
    ordered_list_index,
    prepare_markdown_section_body,
    relative_between,
    render_major_summary,
    render_minor_summary,
    render_paper_markdown,
    render_root_summary,
    is_ordered_list_like,
    looks_like_standalone_numbered_heading,
)
from autopapers.storage.writer import (
    cleanup_previous_files,
    delete_paper,
    paper_stem,
    refresh_summaries,
    remove_stale_topic_dirs,
    rewrite_digest,
    upsert_paper,
)


class PaperLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.repo_root = self.root.parent
        self.index_path = self.root / "index.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._records = load_index(self)
        self._index_mtime_ns = get_index_mtime_ns(self)

    def get_by_paper_id(self, paper_id: str) -> StoredPaper | None:
        with self._lock:
            return get_by_paper_id(self, paper_id)

    def get_by_arxiv_id(self, arxiv_id: str) -> StoredPaper | None:
        with self._lock:
            return get_by_arxiv_id(self, arxiv_id)

    def find_by_title(self, reference: str) -> StoredPaper | None:
        with self._lock:
            return find_by_title(self, reference)

    def find_best_title_match(self, reference: str, *, min_score: float = 0.72) -> StoredPaper | None:
        with self._lock:
            return find_best_title_match(self, reference, min_score=min_score)

    def all_records(self) -> list[StoredPaper]:
        with self._lock:
            return all_records(self)

    def search(self, query: str, *, limit: int = 5, exclude_ids: set[str] | None = None) -> list[StoredPaper]:
        with self._lock:
            return search(self, query, limit=limit, exclude_ids=exclude_ids)

    def topic_snapshot(self) -> str:
        with self._lock:
            return topic_snapshot(self)

    def list_tree(self) -> dict:
        with self._lock:
            return list_tree(self)

    def get_paper_detail(self, paper_id: str) -> dict | None:
        with self._lock:
            return get_paper_detail(self, paper_id)

    def upsert_paper(self, paper: Paper, digest: PaperDigest, pdf_bytes: bytes, related_papers: list[StoredPaper]) -> StoredPaper:
        with self._lock:
            return upsert_paper(self, paper, digest, pdf_bytes, related_papers)

    def rewrite_digest(self, paper_id: str, digest: PaperDigest, related_papers: list[StoredPaper], *, refresh_summaries: bool = True) -> StoredPaper:
        with self._lock:
            return rewrite_digest(
                self,
                paper_id,
                digest,
                related_papers,
                refresh_summaries_enabled=refresh_summaries,
            )

    def delete_paper(self, paper_id: str) -> bool:
        with self._lock:
            return delete_paper(self, paper_id)

    def refresh_summaries(self) -> None:
        with self._lock:
            refresh_summaries(self)

    def _load_index(self) -> dict[str, StoredPaper]:
        return load_index(self)

    def _save_index(self) -> None:
        save_index(self)

    def _reload_index_if_changed(self) -> None:
        reload_index_if_changed(self)

    def _get_index_mtime_ns(self) -> int | None:
        return get_index_mtime_ns(self)

    def _paper_stem(self, paper: Paper) -> str:
        return paper_stem(paper)

    def _cleanup_previous_files(self, existing: StoredPaper, keep: set[Path]) -> None:
        cleanup_previous_files(self, existing, keep)

    def _remove_stale_topic_dirs(self, active_major_dirs: set[Path], active_minor_dirs: set[Path]) -> None:
        remove_stale_topic_dirs(self, active_major_dirs, active_minor_dirs)

    def _serialize_paper_summary(self, record: StoredPaper) -> dict:
        return serialize_paper_summary(self, record)

    def _to_repo_relative(self, path: Path) -> str:
        return to_repo_relative(self, path)

    def _render_paper_markdown(self, stored: StoredPaper, related_papers: list[StoredPaper]) -> str:
        return render_paper_markdown(self, stored, related_papers)

    @staticmethod
    def _render_root_summary(records: list[StoredPaper]) -> str:
        return render_root_summary(records)

    @staticmethod
    def _render_major_summary(major_topic: str, records: list[StoredPaper]) -> str:
        return render_major_summary(major_topic, records)

    @staticmethod
    def _render_minor_summary(major_topic: str, minor_topic: str, records: list[StoredPaper]) -> str:
        return render_minor_summary(major_topic, minor_topic, records)

    @staticmethod
    def _format_venue_line(paper: Paper) -> str:
        return format_venue_line(paper)

    @staticmethod
    def _format_citation_line(paper: Paper) -> str:
        return format_citation_line(paper)

    @staticmethod
    def _derive_abstract_zh(stored: StoredPaper) -> str:
        return derive_abstract_zh(stored)

    @staticmethod
    def _relative_between(from_dir: Path, to_path: Path) -> str:
        return relative_between(from_dir, to_path)

    @staticmethod
    def _prepare_markdown_section_body(body: str) -> str:
        return prepare_markdown_section_body(body)

    @staticmethod
    def _normalize_numbered_heading_lines(lines: list[str]) -> list[str]:
        return normalize_numbered_heading_lines(lines)

    @staticmethod
    def _neighbor_nonempty_line(lines: list[str], index: int, *, step: int) -> tuple[int | None, str]:
        return neighbor_nonempty_line(lines, index, step=step)

    @staticmethod
    def _normalize_numbered_heading_line(
        line: str,
        *,
        previous_nonempty: str,
        next_nonempty: str,
        previous_gap: int,
        next_gap: int,
    ) -> str:
        return normalize_numbered_heading_line(
            line,
            previous_nonempty=previous_nonempty,
            next_nonempty=next_nonempty,
            previous_gap=previous_gap,
            next_gap=next_gap,
        )

    @staticmethod
    def _looks_like_standalone_numbered_heading(
        title: str,
        *,
        previous_nonempty: str,
        next_nonempty: str,
        previous_gap: int,
        next_gap: int,
    ) -> bool:
        return looks_like_standalone_numbered_heading(
            title,
            previous_nonempty=previous_nonempty,
            next_nonempty=next_nonempty,
            previous_gap=previous_gap,
            next_gap=next_gap,
        )

    @staticmethod
    def _is_ordered_list_like(line: str) -> bool:
        return is_ordered_list_like(line)

    @staticmethod
    def _ordered_list_index(line: str) -> int | None:
        return ordered_list_index(line)

    @staticmethod
    def _append_markdown_section(lines: list[str], title: str, body: str) -> None:
        append_markdown_section(lines, title, body)

    @staticmethod
    def _append_markdown_list_section(lines: list[str], title: str, items: list[str]) -> None:
        append_markdown_list_section(lines, title, items)

    @staticmethod
    def _sanitize_path_component(value: str, max_length: int = 80) -> str:
        return sanitize_path_component(value, max_length=max_length)
