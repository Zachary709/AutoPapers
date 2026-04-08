from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable

from autopapers.arxiv import ArxivClient
from autopapers.config import Settings
from autopapers.http_client import build_url_opener
from autopapers.library import PaperLibrary
from autopapers.llm.minimax import MiniMaxClient
from autopapers.llm.planner import Planner
from autopapers.models import Paper, RequestPlan, RunResult, StoredPaper
from autopapers.pdf import PDFTextExtractor
from autopapers.retrieval import DiscoverySearchPlanner
from autopapers.utils import (
    extract_paper_reference_text,
    extract_paper_reference_texts,
    normalize_title_key,
    sanitize_path_component,
    truncate_text,
    unique_by_arxiv_id,
)


class AutoPapersAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.library = PaperLibrary(settings.library_root)
        shared_opener = build_url_opener(settings.network_proxy_url).open
        self.arxiv = ArxivClient(timeout=settings.request_timeout, opener=shared_opener)
        self.planner = Planner(
            MiniMaxClient(
                api_key=settings.api_key,
                model=settings.model,
                api_url=settings.api_url,
                timeout=settings.request_timeout,
                opener=shared_opener,
            ),
            default_max_results=settings.default_max_results,
        )
        self.discovery_search_planner = DiscoverySearchPlanner()
        self.extractor = PDFTextExtractor(
            max_pages=settings.pdf_max_pages,
            max_chars=settings.pdf_max_chars,
        )

    def run(
        self,
        user_request: str,
        *,
        max_results: int | None = None,
        refresh_existing: bool = False,
        notice_callback: Callable[[str], None] | None = None,
    ) -> RunResult:
        def emit_notice(message: str) -> None:
            if notice_callback is not None:
                notice_callback(message)

        emit_notice("开始任务规划")
        plan = self.planner.plan_request(
            user_request,
            self.library.topic_snapshot(),
            max_results=max_results,
            notice_callback=notice_callback,
        )
        emit_notice(f"规划完成：{plan.intent}，最多处理 {plan.max_results} 篇")
        if plan.intent == "explain_paper":
            reference_count = len(plan.paper_refs or extract_paper_reference_texts(user_request))
            emit_notice(f"开始解析论文引用：{reference_count} 项")
        else:
            emit_notice("开始检索 arXiv 候选论文")
        candidates = unique_by_arxiv_id(
            self._collect_candidates(plan, user_request, notice_callback=notice_callback)
        )
        emit_notice(f"候选论文已就绪：{len(candidates)} 篇")

        new_papers: list[StoredPaper] = []
        reused_papers: list[StoredPaper] = []

        for index, paper in enumerate(candidates, start=1):
            title_label = truncate_text(paper.title, 72)
            existing = self.library.get_by_arxiv_id(paper.arxiv_id)
            if existing and not refresh_existing:
                reused_papers.append(existing)
                emit_notice(f"复用本地论文 {index}/{len(candidates)}：{title_label}")
                continue

            emit_notice(f"处理论文 {index}/{len(candidates)}：{title_label}")
            related_for_summary = self.library.search(
                f"{plan.search_query} {paper.title} {paper.primary_category}",
                limit=3,
                exclude_ids={paper.arxiv_id},
            )
            try:
                pdf_bytes = self.arxiv.download_pdf_bytes(paper)
                if pdf_bytes:
                    emit_notice(f"已下载 PDF：{title_label}")
            except Exception:
                pdf_bytes = b""
                emit_notice(f"PDF 下载失败，改用摘要总结：{title_label}")

            extracted_text = self.extractor.extract(pdf_bytes)
            if extracted_text:
                emit_notice(f"已提取正文片段：{title_label}")
            else:
                emit_notice(f"未提取到稳定正文，改用摘要总结：{title_label}")
            digest = self.planner.digest_paper(
                user_request,
                paper,
                extracted_text,
                related_for_summary,
                notice_callback=notice_callback,
            )
            stored = self.library.upsert_paper(paper, digest, pdf_bytes, related_for_summary)
            new_papers.append(stored)
            emit_notice(f"已写入本地库：{title_label}")

        related_papers: list[StoredPaper] = []
        if plan.reuse_local:
            emit_notice("正在检索相关本地论文")
            related_query = self._build_related_query(plan, user_request, new_papers, reused_papers)
            related_papers = self.library.search(
                related_query,
                limit=5,
                exclude_ids={record.paper.arxiv_id for record in [*new_papers, *reused_papers]},
            )
            emit_notice(f"相关本地论文：{len(related_papers)} 篇")

        emit_notice("正在生成报告")
        report_markdown = self._render_report(user_request, plan, new_papers, reused_papers, related_papers)
        report_path = self._save_report(user_request, report_markdown)
        emit_notice(f"任务完成，报告已保存：{Path(report_path).name}")
        return RunResult(
            plan=plan,
            new_papers=new_papers,
            reused_papers=reused_papers,
            related_papers=related_papers,
            report_markdown=report_markdown,
            report_path=report_path,
        )

    def rebuild_summaries(self) -> None:
        self.library.refresh_summaries()

    def _collect_candidates(
        self,
        plan: RequestPlan,
        user_request: str,
        *,
        notice_callback: Callable[[str], None] | None = None,
    ) -> list[Paper]:
        if plan.intent == "explain_paper":
            references = plan.paper_refs or extract_paper_reference_texts(user_request)
            resolved: list[Paper] = []
            unresolved: list[str] = []
            for reference in references:
                if notice_callback is not None:
                    notice_callback(f"正在解析论文：{truncate_text(reference, 72)}")
                try:
                    resolved.append(self._resolve_explain_reference(reference))
                except LookupError:
                    unresolved.append(reference)
            if resolved:
                if unresolved and notice_callback is not None:
                    notice_callback(f"以下论文未能解析，已跳过：{'；'.join(unresolved)}")
                return resolved
            reference_text = "；".join(unresolved or references) if references else user_request
            raise LookupError(f"未能解析到目标论文：{reference_text}")

        candidates: list[Paper] = []
        last_error: Exception | None = None
        for attempt, spec in enumerate(self.discovery_search_planner.build_specs(plan, user_request), start=1):
            if notice_callback is not None:
                notice_callback(f"检索 arXiv 第 {attempt} 轮：{truncate_text(spec.query, 88)}")
            try:
                results = self.arxiv.search(
                    spec.query,
                    max_results=plan.max_results,
                    field=spec.field,
                    sort_by=spec.sort_by,
                    sort_order=spec.sort_order,
                )
            except Exception as exc:
                last_error = exc
                if notice_callback is not None:
                    notice_callback(f"第 {attempt} 轮检索失败：{truncate_text(str(exc), 120)}")
                continue
            candidates = unique_by_arxiv_id([*candidates, *results])
            if notice_callback is not None:
                notice_callback(f"第 {attempt} 轮命中 {len(results)} 篇，累计 {len(candidates)} 篇")
            if len(candidates) >= plan.max_results:
                break

        if candidates:
            return candidates[: plan.max_results]
        if last_error is not None:
            raise last_error
        return []

    def _resolve_explain_reference(self, reference: str) -> Paper:
        local_exact = self.library.find_by_title(reference)
        if local_exact is not None:
            return local_exact.paper

        local_fuzzy = self.library.find_best_title_match(reference)
        if local_fuzzy is not None:
            return local_fuzzy.paper

        cleaned_reference = extract_paper_reference_text(reference)
        return self.arxiv.resolve_reference(cleaned_reference)

    def _build_related_query(
        self,
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

    def _render_report(
        self,
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
                lines.extend(self._paper_report_block(record))
        lines.append("")

        lines.append("## Directly Reused Local Papers")
        lines.append("")
        if not reused_papers:
            lines.append("- None.")
        else:
            for record in reused_papers:
                lines.extend(self._paper_report_block(record))
        lines.append("")

        compared_records = [*new_papers, *reused_papers]
        if plan.intent == "explain_paper" and len(compared_records) > 1:
            lines.append("## Multi-Paper Comparison")
            lines.append("")
            lines.extend(self._comparison_report_block(compared_records))
            lines.append("")

        lines.append("## Additional Related Local Papers")
        lines.append("")
        if not related_papers:
            lines.append("- None.")
        else:
            for record in related_papers:
                lines.append(
                    f"- [{record.paper.title}]({record.md_path}): {record.digest.one_sentence_takeaway}"
                )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _paper_report_block(record: StoredPaper) -> list[str]:
        lines = [f"### [{record.paper.title}]({record.md_path})"]
        lines.append(f"- arXiv: `{record.paper.versioned_id or record.paper.arxiv_id}`")
        lines.append(f"- Topics: {record.digest.major_topic} / {record.digest.minor_topic}")
        lines.append(f"- PDF: [{Path(record.pdf_path).name}]({record.pdf_path})")
        lines.append(f"- Takeaway: {record.digest.one_sentence_takeaway}")
        for finding in record.digest.findings:
            lines.append(f"- Finding: {finding}")
        return lines

    def _comparison_report_block(self, records: list[StoredPaper]) -> list[str]:
        shared_keywords = self._shared_keywords(records)
        major_topics = self._ordered_unique(record.digest.major_topic for record in records)
        minor_topics = self._ordered_unique(record.digest.minor_topic for record in records)
        reading_order = self._suggest_reading_order(records)

        lines = [
            f"- Compared papers: {len(records)}",
            f"- Shared scope: {', '.join(major_topics[:3])}" if major_topics else "- Shared scope: 未归纳出稳定方向",
        ]
        if shared_keywords:
            lines.append(f"- Shared keywords: {', '.join(shared_keywords[:8])}")
        elif minor_topics:
            lines.append(f"- Topic spread: {', '.join(minor_topics[:6])}")

        for record in records:
            focus = record.digest.problem or record.digest.one_sentence_takeaway or record.paper.abstract
            lines.append(f"- Focus | {record.paper.title}: {truncate_text(focus, 120)}")

        if len(reading_order) > 1:
            lines.append(
                "- Suggested reading order: "
                + " -> ".join(record.paper.title for record in reading_order)
            )
        return lines

    @staticmethod
    def _shared_keywords(records: list[StoredPaper]) -> list[str]:
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
        return [
            keyword_labels[key]
            for key, count in keyword_counter.most_common()
            if count > 1
        ]

    @staticmethod
    def _ordered_unique(values) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    @staticmethod
    def _suggest_reading_order(records: list[StoredPaper]) -> list[StoredPaper]:
        def sort_key(record: StoredPaper) -> tuple[int, str, str]:
            title_key = record.paper.title.casefold()
            survey_priority = 0 if any(marker in title_key for marker in ("survey", "review", "overview", "tutorial")) else 1
            return (
                survey_priority,
                record.paper.published or "",
                title_key,
            )

        return sorted(records, key=sort_key)

    def _save_report(self, user_request: str, markdown: str) -> str:
        self.settings.reports_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = sanitize_path_component(user_request, max_length=48)
        report_path = self.settings.reports_root / f"{timestamp}_{name}.md"
        report_path.write_text(markdown, encoding="utf-8")
        return report_path.relative_to(self.settings.repo_root).as_posix()
