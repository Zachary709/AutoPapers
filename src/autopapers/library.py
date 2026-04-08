from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil

from autopapers.models import Paper, PaperDigest, StoredPaper
from autopapers.utils import (
    extract_paper_reference_text,
    normalize_title_key,
    sanitize_path_component,
    title_similarity,
    tokenize,
    utc_now_iso,
)


class PaperLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.repo_root = self.root.parent
        self.index_path = self.root / "index.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self._records = self._load_index()
        self._index_mtime_ns = self._get_index_mtime_ns()

    def get_by_arxiv_id(self, arxiv_id: str) -> StoredPaper | None:
        self._reload_index_if_changed()
        return self._records.get(arxiv_id)

    def find_by_title(self, reference: str) -> StoredPaper | None:
        self._reload_index_if_changed()
        target = normalize_title_key(extract_paper_reference_text(reference))
        if not target:
            return None
        for record in self._records.values():
            if normalize_title_key(record.paper.title) == target:
                return record
        return None

    def find_best_title_match(self, reference: str, *, min_score: float = 0.72) -> StoredPaper | None:
        self._reload_index_if_changed()
        extracted = extract_paper_reference_text(reference)
        target = normalize_title_key(extracted)
        if not target:
            return None

        best_record: StoredPaper | None = None
        best_score = 0.0
        for record in self._records.values():
            score = title_similarity(extracted, record.paper.title)
            if score > best_score:
                best_score = score
                best_record = record
        if best_record is not None and best_score >= min_score:
            return best_record
        return None

    def all_records(self) -> list[StoredPaper]:
        self._reload_index_if_changed()
        return list(self._records.values())

    def search(self, query: str, *, limit: int = 5, exclude_ids: set[str] | None = None) -> list[StoredPaper]:
        self._reload_index_if_changed()
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[int, StoredPaper]] = []
        for record in self._records.values():
            if exclude_ids and record.paper.arxiv_id in exclude_ids:
                continue
            title_tokens = tokenize(record.paper.title)
            abstract_tokens = tokenize(record.paper.abstract)
            topic_tokens = tokenize(
                " ".join(
                    [
                        record.digest.major_topic,
                        record.digest.minor_topic,
                        record.digest.one_sentence_takeaway,
                        " ".join(record.digest.keywords),
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

    def topic_snapshot(self) -> str:
        self._reload_index_if_changed()
        if not self._records:
            return "本地论文库为空。"
        by_major: dict[str, list[StoredPaper]] = defaultdict(list)
        for record in self._records.values():
            by_major[record.digest.major_topic].append(record)
        lines = ["本地论文库概览:"]
        for major_topic in sorted(by_major):
            major_records = sorted(by_major[major_topic], key=lambda item: item.paper.published, reverse=True)
            minor_topics = sorted({record.digest.minor_topic for record in major_records})
            lines.append(f"- {major_topic}: {len(major_records)} 篇论文, 子方向 {', '.join(minor_topics[:5])}")
            for record in major_records[:3]:
                lines.append(f"  - {record.paper.title} | {record.digest.one_sentence_takeaway}")
        return "\n".join(lines)

    def list_tree(self) -> dict:
        self._reload_index_if_changed()
        records = sorted(self._records.values(), key=lambda item: item.paper.published, reverse=True)
        by_major: dict[str, dict[str, list[StoredPaper]]] = defaultdict(lambda: defaultdict(list))
        for record in records:
            by_major[record.digest.major_topic][record.digest.minor_topic].append(record)

        major_nodes: list[dict] = []
        minor_count = 0
        for major_topic in sorted(by_major):
            minor_nodes: list[dict] = []
            for minor_topic in sorted(by_major[major_topic]):
                papers = [self._serialize_paper_summary(record) for record in by_major[major_topic][minor_topic]]
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

    def get_paper_detail(self, arxiv_id: str) -> dict | None:
        self._reload_index_if_changed()
        record = self.get_by_arxiv_id(arxiv_id)
        if record is None:
            return None
        markdown_path = self.repo_root / record.md_path
        metadata_path = self.repo_root / record.metadata_path
        pdf_path = self.repo_root / record.pdf_path
        markdown_content = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
        return {
            "summary": self._serialize_paper_summary(record),
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

    def upsert_paper(self, paper: Paper, digest: PaperDigest, pdf_bytes: bytes, related_papers: list[StoredPaper]) -> StoredPaper:
        major_dir = self.root / sanitize_path_component(digest.major_topic)
        minor_dir = major_dir / sanitize_path_component(digest.minor_topic)
        minor_dir.mkdir(parents=True, exist_ok=True)
        stem = self._paper_stem(paper)
        pdf_path = minor_dir / f"{stem}.pdf"
        md_path = minor_dir / f"{stem}.md"
        metadata_path = minor_dir / f"{stem}.metadata.json"

        existing = self._records.get(paper.arxiv_id)
        preserved_pdf_bytes = b""
        if existing:
            existing_pdf_path = self.repo_root / existing.pdf_path
            if not pdf_bytes and existing_pdf_path.exists():
                preserved_pdf_bytes = existing_pdf_path.read_bytes()
            self._cleanup_previous_files(existing, {pdf_path, md_path, metadata_path})

        effective_pdf_bytes = pdf_bytes or preserved_pdf_bytes
        if effective_pdf_bytes:
            pdf_path.write_bytes(effective_pdf_bytes)

        stored = StoredPaper(
            paper=paper,
            digest=digest,
            stored_at=utc_now_iso(),
            pdf_path=self._to_repo_relative(pdf_path),
            md_path=self._to_repo_relative(md_path),
            metadata_path=self._to_repo_relative(metadata_path),
        )
        md_path.write_text(self._render_paper_markdown(stored, related_papers), encoding="utf-8")
        metadata_path.write_text(json.dumps(stored.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._records[paper.arxiv_id] = stored
        self._save_index()
        self.refresh_summaries()
        return stored

    def delete_paper(self, arxiv_id: str) -> bool:
        existing = self._records.pop(arxiv_id, None)
        if existing is None:
            return False
        for relative_path in (existing.pdf_path, existing.md_path, existing.metadata_path):
            absolute = self.repo_root / relative_path
            if absolute.exists() and self.root in absolute.parents:
                absolute.unlink()
        self._save_index()
        self.refresh_summaries()
        return True

    def refresh_summaries(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        records = sorted(self._records.values(), key=lambda item: item.paper.published, reverse=True)
        by_major: dict[str, list[StoredPaper]] = defaultdict(list)
        by_minor: dict[tuple[str, str], list[StoredPaper]] = defaultdict(list)
        for record in records:
            by_major[record.digest.major_topic].append(record)
            by_minor[(record.digest.major_topic, record.digest.minor_topic)].append(record)

        active_major_dirs = {self.root / sanitize_path_component(major_topic) for major_topic in by_major}
        active_minor_dirs = {
            self.root / sanitize_path_component(major_topic) / sanitize_path_component(minor_topic)
            for (major_topic, minor_topic) in by_minor
        }
        self._remove_stale_topic_dirs(active_major_dirs, active_minor_dirs)
        (self.root / "README.md").write_text(self._render_root_summary(records), encoding="utf-8")

        for major_topic, major_records in by_major.items():
            major_dir = self.root / sanitize_path_component(major_topic)
            major_dir.mkdir(parents=True, exist_ok=True)
            (major_dir / "README.md").write_text(self._render_major_summary(major_topic, major_records), encoding="utf-8")

        for (major_topic, minor_topic), minor_records in by_minor.items():
            minor_dir = self.root / sanitize_path_component(major_topic) / sanitize_path_component(minor_topic)
            minor_dir.mkdir(parents=True, exist_ok=True)
            (minor_dir / "README.md").write_text(self._render_minor_summary(major_topic, minor_topic, minor_records), encoding="utf-8")

    def _load_index(self) -> dict[str, StoredPaper]:
        if not self.index_path.exists():
            return {}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        papers = data.get("papers", [])
        return {record["paper"]["arxiv_id"]: StoredPaper.from_dict(record) for record in papers}

    def _save_index(self) -> None:
        payload = {"updated_at": utc_now_iso(), "papers": [record.to_dict() for record in sorted(self._records.values(), key=lambda item: item.paper.arxiv_id)]}
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._index_mtime_ns = self._get_index_mtime_ns()

    def _reload_index_if_changed(self) -> None:
        current_mtime_ns = self._get_index_mtime_ns()
        if current_mtime_ns == self._index_mtime_ns:
            return
        self._records = self._load_index()
        self._index_mtime_ns = current_mtime_ns

    def _get_index_mtime_ns(self) -> int | None:
        if not self.index_path.exists():
            return None
        return self.index_path.stat().st_mtime_ns

    def _paper_stem(self, paper: Paper) -> str:
        title_slug = sanitize_path_component(paper.title, max_length=60)
        return sanitize_path_component(f"{paper.arxiv_id}_{title_slug}", max_length=96)

    def _cleanup_previous_files(self, existing: StoredPaper, keep: set[Path]) -> None:
        for relative_path in (existing.pdf_path, existing.md_path, existing.metadata_path):
            absolute = self.repo_root / relative_path
            if absolute in keep:
                continue
            if absolute.exists() and self.root in absolute.parents:
                absolute.unlink()

    def _remove_stale_topic_dirs(self, active_major_dirs: set[Path], active_minor_dirs: set[Path]) -> None:
        for child in self.root.iterdir():
            if child.is_dir() and child not in active_major_dirs:
                shutil.rmtree(child, ignore_errors=True)
        for major_dir in active_major_dirs:
            if not major_dir.exists():
                continue
            for child in major_dir.iterdir():
                if child.is_dir() and child not in active_minor_dirs:
                    shutil.rmtree(child, ignore_errors=True)

    def _serialize_paper_summary(self, record: StoredPaper) -> dict:
        pdf_path = self.repo_root / record.pdf_path
        return {
            "arxiv_id": record.paper.arxiv_id,
            "versioned_id": record.paper.versioned_id,
            "title": record.paper.title,
            "published": record.paper.published,
            "stored_at": record.stored_at,
            "authors": record.paper.authors,
            "major_topic": record.digest.major_topic,
            "minor_topic": record.digest.minor_topic,
            "takeaway": record.digest.one_sentence_takeaway,
            "keywords": record.digest.keywords,
            "pdf_available": pdf_path.exists(),
        }

    def _to_repo_relative(self, path: Path) -> str:
        return path.relative_to(self.repo_root).as_posix()

    def _render_paper_markdown(self, stored: StoredPaper, related_papers: list[StoredPaper]) -> str:
        md_file_path = self.repo_root / stored.md_path
        note_dir = md_file_path.parent
        pdf_absolute = self.repo_root / stored.pdf_path
        pdf_line = "- PDF: unavailable"
        if pdf_absolute.exists():
            pdf_relative = Path(stored.pdf_path).name
            pdf_line = f"- PDF: [{Path(pdf_relative).name}]({pdf_relative})"

        related_lines = []
        for record in related_papers[:5]:
            target_path = self.repo_root / record.md_path
            link_target = self._relative_between(note_dir, target_path)
            related_lines.append(f"- [{record.paper.title}]({link_target}) | {record.digest.one_sentence_takeaway}")
        if not related_lines:
            related_lines.append("- 暂无。")

        findings = "\n".join(f"- {item}" for item in stored.digest.findings)
        limitations = "\n".join(f"- {item}" for item in stored.digest.limitations)
        keywords = ", ".join(stored.digest.keywords)
        return (
            f"# {stored.paper.title}\n\n"
            f"- arXiv ID: `{stored.paper.versioned_id or stored.paper.arxiv_id}`\n"
            f"- Authors: {', '.join(stored.paper.authors)}\n"
            f"- Published: {stored.paper.published}\n"
            f"- Topics: {stored.digest.major_topic} / {stored.digest.minor_topic}\n"
            f"- Keywords: {keywords}\n"
            f"{pdf_line}\n\n"
            f"## Abstract\n\n{stored.paper.abstract}\n\n"
            f"## One-Sentence Takeaway\n\n{stored.digest.one_sentence_takeaway}\n\n"
            f"## Background\n\n{stored.digest.background}\n\n"
            f"## Core Problem\n\n{stored.digest.problem}\n\n"
            f"## Method\n\n{stored.digest.method}\n\n"
            f"## Findings\n\n{findings}\n\n"
            f"## Limitations\n\n{limitations}\n\n"
            f"## Relevance\n\n{stored.digest.relevance}\n\n"
            f"## Related Local Papers\n\n" + "\n".join(related_lines) + "\n"
        )

    def _render_root_summary(self, records: list[StoredPaper]) -> str:
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

    def _render_major_summary(self, major_topic: str, records: list[StoredPaper]) -> str:
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

    def _render_minor_summary(self, major_topic: str, minor_topic: str, records: list[StoredPaper]) -> str:
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
            lines.append(f"- arXiv: `{record.paper.versioned_id or record.paper.arxiv_id}`")
            lines.append(f"- Published: {record.paper.published}")
            lines.append(f"- Takeaway: {record.digest.one_sentence_takeaway}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _relative_between(from_dir: Path, to_path: Path) -> str:
        return Path(os.path.relpath(to_path, start=from_dir)).as_posix()
