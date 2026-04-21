from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError

from autopapers.arxiv import ArxivClient, ArxivError
from autopapers.config import Settings
from autopapers.http_client import build_url_opener
from autopapers.library import PaperLibrary
from autopapers.llm.minimax import MiniMaxClient
from autopapers.llm.planner import Planner
from autopapers.models import Paper, RequestPlan, RunResult, StoredPaper, TaskCancelledError
from autopapers.openreview import OpenReviewAuthError, OpenReviewClient, OpenReviewClientUnavailableError
from autopapers.openreview_auth import OpenReviewAuthStore
from autopapers.pdf import ExtractedPaperContent, PDFTextExtractor
from autopapers.retrieval import DiscoverySearchPlanner
from autopapers.scholar import ScholarBlockedError, ScholarClient
from autopapers.taxonomy import TopicTaxonomy
from autopapers.utils import (
    extract_paper_reference_text,
    extract_paper_reference_texts,
    normalize_title_key,
    paper_identity_key,
    sanitize_path_component,
    title_similarity,
    truncate_text,
    unique_by_paper_identity,
    utc_now_iso,
    venue_or_published_year,
    word_similarity,
    write_text_atomic,
)


REFERENCE_CONFIRMATION_THRESHOLD = 0.58


class AutoPapersAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.library = PaperLibrary(settings.library_root)
        shared_opener = build_url_opener(settings.network_proxy_url).open
        self.arxiv = ArxivClient(timeout=settings.request_timeout, opener=shared_opener)
        self.openreview = OpenReviewClient(
            timeout=settings.request_timeout,
            auth_store=OpenReviewAuthStore(settings.openreview_auth_path) if settings.openreview_auth_path else None,
            proxy_url=settings.network_proxy_url,
        )
        self.scholar = ScholarClient(timeout=settings.request_timeout, opener=shared_opener)
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
        self.taxonomy = TopicTaxonomy()
        self.extractor = PDFTextExtractor(
            max_pages=settings.pdf_max_pages,
            max_chars=settings.pdf_max_chars,
        )

    def rebuild_planner(self) -> None:
        shared_opener = build_url_opener(self.settings.network_proxy_url).open
        self.planner = Planner(
            MiniMaxClient(
                api_key=self.settings.api_key,
                model=self.settings.model,
                api_url=self.settings.api_url,
                timeout=self.settings.request_timeout,
                opener=shared_opener,
            ),
            default_max_results=self.settings.default_max_results,
        )
        self.arxiv = ArxivClient(timeout=self.settings.request_timeout, opener=shared_opener)
        self.scholar = ScholarClient(timeout=self.settings.request_timeout, opener=shared_opener)

    def run(
        self,
        user_request: str,
        *,
        max_results: int | None = None,
        refresh_existing: bool = False,
        notice_callback: Callable[[str], None] | None = None,
        timeline_callback: Callable[[dict[str, object]], None] | None = None,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
        confirmation_callback: Callable[[dict[str, object]], bool] | None = None,
        debug_callback: Callable[[str], None] | None = None,
    ) -> RunResult:
        def emit_notice(message: str, *, kind: str = "info", stage: str | None = None) -> None:
            if timeline_callback is not None:
                timeline_callback({"message": message, "kind": kind, "stage": stage})
                return
            if notice_callback is not None:
                notice_callback(message)

        def emit_progress(
            stage: str,
            label: str,
            detail: str,
            percent: int,
            *,
            indeterminate: bool = False,
            paper_index: int | None = None,
            paper_total: int | None = None,
            current_title: str | None = None,
        ) -> None:
            self._emit_progress(
                progress_callback,
                stage=stage,
                label=label,
                detail=detail,
                percent=percent,
                indeterminate=indeterminate,
                paper_index=paper_index,
                paper_total=paper_total,
                current_title=current_title,
            )

        emit_progress("planning", "任务规划", "正在理解任务并生成执行方案", 5)
        emit_notice("开始任务规划", kind="milestone", stage="planning")
        plan_kwargs = {"notice_callback": notice_callback}
        if debug_callback is not None:
            plan_kwargs["debug_callback"] = debug_callback
        plan = self.planner.plan_request(
            user_request,
            self.library.topic_snapshot(),
            max_results=max_results,
            **plan_kwargs,
        )
        emit_progress("planning", "任务规划", f"规划完成：{plan.intent}，最多处理 {plan.max_results} 篇", 15)
        emit_notice(f"规划完成：{plan.intent}，最多处理 {plan.max_results} 篇", stage="planning")
        if plan.intent == "explain_paper":
            reference_count = len(plan.paper_refs or extract_paper_reference_texts(user_request))
            emit_progress("resolving", "解析论文引用", f"正在解析 {reference_count} 项引用", 18, paper_total=reference_count or None)
            emit_notice(f"开始解析论文引用：{reference_count} 项", kind="milestone", stage="resolving")
        else:
            emit_progress("searching", "检索论文源", "正在检索候选论文", 18)
            emit_notice("开始检索多源候选论文", kind="milestone", stage="searching")
        candidates = unique_by_paper_identity(
            self._collect_candidates(
                plan,
                user_request,
                notice_callback=notice_callback,
                progress_callback=progress_callback,
                confirmation_callback=confirmation_callback,
            )
        )
        emit_progress("processing", "处理论文", f"候选论文已就绪：{len(candidates)} 篇", 30, paper_total=len(candidates) or None)
        emit_notice(f"候选论文已就绪：{len(candidates)} 篇", stage="processing")

        new_papers: list[StoredPaper] = []
        reused_papers: list[StoredPaper] = []
        taxonomy_context = self.taxonomy.prompt_guidance()
        halfway_notice_sent = False
        total_candidates = len(candidates)

        if total_candidates:
            emit_notice(f"开始处理论文：{total_candidates} 篇", kind="milestone", stage="processing")

        for index, paper in enumerate(candidates, start=1):
            title_label = truncate_text(paper.title, 72)
            paper = self._enrich_paper_metadata(paper, notice_callback=notice_callback)
            existing = self._find_existing_record(paper)
            if existing and not refresh_existing:
                reused_papers.append(existing)
                emit_progress(
                    "processing",
                    "处理论文",
                    f"复用本地论文 {index}/{total_candidates}：{title_label}",
                    self._processing_percent(index, 1, total_candidates),
                    paper_index=index,
                    paper_total=total_candidates,
                    current_title=title_label,
                )
                emit_notice(f"复用本地论文 {index}/{total_candidates}：{title_label}", stage="processing")
                emit_progress(
                    "processing",
                    "处理论文",
                    f"已复用本地论文 {index}/{total_candidates}：{title_label}",
                    self._processing_percent(index, 4, total_candidates),
                    paper_index=index,
                    paper_total=total_candidates,
                    current_title=title_label,
                )
                if total_candidates >= 4 and not halfway_notice_sent and index * 2 >= total_candidates:
                    emit_notice(f"论文处理已过半：{index}/{total_candidates}", kind="milestone", stage="processing")
                    halfway_notice_sent = True
                continue

            emit_progress(
                "processing",
                "处理论文",
                f"处理论文 {index}/{total_candidates}：{title_label}",
                self._processing_percent(index, 1, total_candidates),
                paper_index=index,
                paper_total=total_candidates,
                current_title=title_label,
            )
            emit_notice(f"处理论文 {index}/{total_candidates}：{title_label}", stage="processing")
            related_for_summary = self.library.search(
                f"{plan.search_query} {paper.title} {paper.primary_category}",
                limit=3,
                exclude_ids={paper.paper_id},
            )
            existing_pdf_bytes = self._read_existing_pdf_bytes(existing) if existing is not None else b""
            try:
                if refresh_existing and existing_pdf_bytes:
                    pdf_bytes = existing_pdf_bytes
                    emit_notice(f"已复用本地 PDF 重新整理：{title_label}", stage="processing")
                else:
                    pdf_bytes = self._download_pdf_bytes(paper)
                if pdf_bytes and not (refresh_existing and existing_pdf_bytes):
                    emit_notice(f"已下载 PDF：{title_label}", stage="processing")
            except Exception:
                pdf_bytes = b""
                emit_notice(f"PDF 下载失败，已跳过该论文：{title_label}", kind="warning", stage="processing")

            extracted_content = self._extract_pdf_content(pdf_bytes)
            if extracted_content.has_substantial_text():
                emit_notice(f"已提取正文片段：{title_label}", stage="processing")
            else:
                emit_notice(f"未提取到稳定正文，已跳过该论文：{title_label}", kind="warning", stage="processing")
            emit_progress(
                "processing",
                "处理论文",
                f"PDF/正文准备完成 {index}/{total_candidates}：{title_label}",
                self._processing_percent(index, 2, total_candidates),
                paper_index=index,
                paper_total=total_candidates,
                current_title=title_label,
            )
            if not pdf_bytes or not extracted_content.has_substantial_text():
                if total_candidates >= 4 and not halfway_notice_sent and index * 2 >= total_candidates:
                    emit_notice(f"论文处理已过半：{index}/{total_candidates}", kind="milestone", stage="processing")
                    halfway_notice_sent = True
                continue
            digest_kwargs = {
                "taxonomy_context": taxonomy_context,
                "notice_callback": notice_callback,
            }
            if debug_callback is not None:
                digest_kwargs["debug_callback"] = debug_callback
            digest = self.planner.digest_paper(
                user_request,
                paper,
                extracted_content,
                related_for_summary,
                **digest_kwargs,
            )
            emit_progress(
                "processing",
                "处理论文",
                f"已完成结构化总结 {index}/{total_candidates}：{title_label}",
                self._processing_percent(index, 3, total_candidates),
                paper_index=index,
                paper_total=total_candidates,
                current_title=title_label,
            )
            digest = self.taxonomy.canonicalize_digest(
                paper,
                digest,
                [*self.library.all_records(), *new_papers, *reused_papers],
            )
            stored = self.library.upsert_paper(paper, digest, pdf_bytes, related_for_summary)
            new_papers.append(stored)
            emit_notice(f"已写入本地库：{title_label}", stage="processing")
            emit_progress(
                "processing",
                "处理论文",
                f"已写入本地库 {index}/{total_candidates}：{title_label}",
                self._processing_percent(index, 4, total_candidates),
                paper_index=index,
                paper_total=total_candidates,
                current_title=title_label,
            )
            if total_candidates >= 4 and not halfway_notice_sent and index * 2 >= total_candidates:
                emit_notice(f"论文处理已过半：{index}/{total_candidates}", kind="milestone", stage="processing")
                halfway_notice_sent = True

        related_papers: list[StoredPaper] = []
        if plan.reuse_local:
            emit_progress(
                "related",
                "相关论文",
                "正在检索相关本地论文",
                88,
                paper_total=total_candidates or None,
                paper_index=total_candidates or None,
            )
            emit_notice("正在检索相关本地论文", stage="related")
            related_query = self._build_related_query(plan, user_request, new_papers, reused_papers)
            related_papers = self.library.search(
                related_query,
                limit=5,
                exclude_ids={record.paper.paper_id for record in [*new_papers, *reused_papers]},
            )
            emit_progress(
                "related",
                "相关论文",
                f"相关本地论文：{len(related_papers)} 篇",
                94,
                paper_total=total_candidates or None,
                paper_index=total_candidates or None,
            )
            emit_notice(f"相关本地论文：{len(related_papers)} 篇", stage="related")

        emit_progress(
            "reporting",
            "生成报告",
            "正在整理最终报告与结果",
            94,
            paper_total=total_candidates or None,
            paper_index=total_candidates or None,
        )
        emit_notice("正在生成报告", kind="milestone", stage="reporting")
        report_markdown = self._render_report(user_request, plan, new_papers, reused_papers, related_papers)
        report_path = self._save_report(user_request, report_markdown)
        emit_progress(
            "reporting",
            "生成报告",
            f"报告已保存：{Path(report_path).name}",
            99,
            paper_total=total_candidates or None,
            paper_index=total_candidates or None,
        )
        emit_notice(f"任务完成，报告已保存：{Path(report_path).name}", stage="reporting")
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

    def reanalyze_library(
        self,
        *,
        arxiv_ids: list[str] | None = None,
        paper_ids: list[str] | None = None,
        limit: int | None = None,
        download_missing_pdf: bool = False,
        format_only: bool = False,
        notice_callback: Callable[[str], None] | None = None,
        debug_callback: Callable[[str], None] | None = None,
    ) -> list[StoredPaper]:
        records = self._select_library_records(
            paper_ids=paper_ids,
            arxiv_ids=arxiv_ids,
            limit=limit,
        )
        if format_only:
            updated: list[StoredPaper] = []
            for index, record in enumerate(records, start=1):
                title_label = truncate_text(record.paper.title, 72)
                if notice_callback is not None:
                    notice_callback(f"仅更新最终格式 {index}/{len(records)}：{title_label}")
                related_for_summary = self.library.search(
                    f"{record.paper.title} {record.paper.primary_category}",
                    limit=3,
                    exclude_ids={record.paper.paper_id},
                )
                format_kwargs = {"notice_callback": notice_callback}
                if debug_callback is not None:
                    format_kwargs["debug_callback"] = debug_callback
                formatted_digest = self.planner.tighten_digest_format_only(
                    record.paper,
                    record.digest,
                    **format_kwargs,
                )
                updated.append(
                    self.library.rewrite_digest(
                        record.paper.paper_id,
                        formatted_digest,
                        related_for_summary,
                        refresh_summaries=False,
                    )
                )
            self.library.refresh_summaries()
            return updated

        updated: list[StoredPaper] = []
        taxonomy_context = self.taxonomy.prompt_guidance()
        for index, record in enumerate(records, start=1):
            title_label = truncate_text(record.paper.title, 72)
            if notice_callback is not None:
                notice_callback(f"重新分析论文 {index}/{len(records)}：{title_label}")
            pdf_path = self.settings.repo_root / record.pdf_path
            pdf_bytes = pdf_path.read_bytes() if pdf_path.exists() else b""
            if not pdf_bytes and download_missing_pdf:
                try:
                    pdf_bytes = self._download_pdf_bytes(record.paper)
                    if notice_callback is not None and pdf_bytes:
                        notice_callback(f"已补拉 PDF：{title_label}")
                except Exception:
                    if notice_callback is not None:
                        notice_callback(f"缺失 PDF 且补拉失败：{title_label}")
            refreshed_paper = self._enrich_paper_metadata(record.paper, notice_callback=notice_callback)
            extracted_content = self._extract_pdf_content(pdf_bytes)
            related_for_summary = self.library.search(
                f"{refreshed_paper.title} {refreshed_paper.primary_category}",
                limit=3,
                exclude_ids={record.paper.paper_id},
            )
            digest_kwargs = {
                "taxonomy_context": taxonomy_context,
                "notice_callback": notice_callback,
            }
            if debug_callback is not None:
                digest_kwargs["debug_callback"] = debug_callback
            digest = self.planner.digest_paper(
                f"请重新整理并深入总结这篇论文：{refreshed_paper.title}",
                refreshed_paper,
                extracted_content,
                related_for_summary,
                **digest_kwargs,
            )
            digest = self.taxonomy.canonicalize_digest(refreshed_paper, digest, records)
            updated.append(self.library.upsert_paper(refreshed_paper, digest, pdf_bytes, related_for_summary))
        self.library.refresh_summaries()
        return updated

    def _select_library_records(
        self,
        *,
        arxiv_ids: list[str] | None = None,
        paper_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[StoredPaper]:
        records = self.library.all_records()
        if paper_ids:
            wanted_paper_ids = set(paper_ids)
            records = [record for record in records if record.paper.paper_id in wanted_paper_ids]
        if arxiv_ids:
            wanted = set(arxiv_ids)
            records = [record for record in records if record.paper.arxiv_id in wanted]
        records = sorted(records, key=lambda item: item.paper.published, reverse=True)
        if limit is not None:
            records = records[: max(0, limit)]
        return records

    def refresh_paper_metadata(
        self,
        paper_id: str,
        *,
        notice_callback: Callable[[str], None] | None = None,
    ) -> dict | None:
        record = self.library.get_by_paper_id(paper_id)
        if record is None:
            return None
        refreshed_paper, refresh_report = self._enrich_paper_metadata_with_report(record.paper, notice_callback=notice_callback)
        refreshed_paper.paper_id = record.paper.paper_id
        refreshed_paper.source_primary = record.paper.source_primary
        changed_fields = self._metadata_field_changes(record.paper, refreshed_paper)
        refresh_result = self._build_metadata_refresh_result(
            paper=refreshed_paper,
            source_reports=refresh_report,
            changed_fields=changed_fields,
        )
        if not changed_fields:
            return {"record": record, "refresh": refresh_result}
        pdf_path = self.settings.repo_root / record.pdf_path
        pdf_bytes = pdf_path.read_bytes() if pdf_path.exists() else b""
        related_for_summary = self.library.search(
            f"{refreshed_paper.title} {refreshed_paper.primary_category}",
            limit=3,
            exclude_ids={refreshed_paper.paper_id},
        )
        updated = self.library.upsert_paper(refreshed_paper, record.digest, pdf_bytes, related_for_summary)
        if notice_callback is not None:
            notice_callback(refresh_result["message"])
        return {"record": updated, "refresh": refresh_result}

    def normalize_library_topics(
        self,
        *,
        notice_callback: Callable[[str], None] | None = None,
    ) -> list[StoredPaper]:
        records = list(self.library.all_records())
        updated: list[StoredPaper] = []

        for index, record in enumerate(records, start=1):
            normalized_digest = self.taxonomy.canonicalize_digest(record.paper, record.digest, records)
            if (
                normalized_digest.major_topic == record.digest.major_topic
                and normalized_digest.minor_topic == record.digest.minor_topic
            ):
                continue

            title_label = truncate_text(record.paper.title, 72)
            if notice_callback is not None:
                notice_callback(
                    f"规范化主题 {index}/{len(records)}：{title_label} -> {normalized_digest.major_topic} / {normalized_digest.minor_topic}"
                )
            pdf_path = self.settings.repo_root / record.pdf_path
            pdf_bytes = pdf_path.read_bytes() if pdf_path.exists() else b""
            related_for_summary = self.library.search(
                f"{record.paper.title} {record.paper.primary_category}",
                limit=3,
                exclude_ids={record.paper.paper_id},
            )
            updated.append(self.library.upsert_paper(record.paper, normalized_digest, pdf_bytes, related_for_summary))

        self.library.refresh_summaries()
        return updated

    def _extract_pdf_content(self, pdf_bytes: bytes) -> ExtractedPaperContent:
        if hasattr(self.extractor, "extract_structured"):
            return self.extractor.extract_structured(pdf_bytes)
        extracted = self.extractor.extract(pdf_bytes)
        return ExtractedPaperContent(raw_body=extracted)

    def _collect_candidates(
        self,
        plan: RequestPlan,
        user_request: str,
        *,
        notice_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
        confirmation_callback: Callable[[dict[str, object]], bool] | None = None,
    ) -> list[Paper]:
        if plan.intent == "explain_paper":
            references = plan.paper_refs or extract_paper_reference_texts(user_request)
            resolved: list[Paper] = []
            unresolved: list[str] = []
            total_references = max(len(references), 1)
            for index, reference in enumerate(references, start=1):
                if notice_callback is not None:
                    notice_callback(f"正在解析论文：{truncate_text(reference, 72)}")
                self._emit_progress(
                    progress_callback,
                    stage="resolving",
                    label="解析论文引用",
                    detail=f"正在解析论文 {index}/{total_references}",
                    percent=15 + round(index / total_references * 15),
                    paper_index=index,
                    paper_total=total_references,
                    current_title=truncate_text(reference, 72),
                )
                try:
                    resolved = self._merge_candidate_lists(
                        resolved,
                        [
                            self._resolve_explain_reference(
                                reference,
                                notice_callback=notice_callback,
                                confirmation_callback=confirmation_callback,
                            )
                        ],
                    )
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
        specs = self.discovery_search_planner.build_specs(plan, user_request)
        total_specs = max(len(specs), 1)
        for attempt, spec in enumerate(specs, start=1):
            if notice_callback is not None:
                notice_callback(f"多源检索第 {attempt} 轮：{truncate_text(spec.query, 88)}")
            round_results: list[Paper] = []
            searchers = [
                (
                    "arXiv",
                    lambda: self.arxiv.search(
                        spec.query,
                        max_results=plan.max_results,
                        field=spec.field,
                        sort_by=spec.sort_by,
                        sort_order=spec.sort_order,
                    ),
                )
            ]
            if hasattr(self, "openreview"):
                searchers.append(("OpenReview", lambda: self.openreview.search(spec.query, max_results=plan.max_results)))
            for source_name, searcher in searchers:
                try:
                    source_results = searcher()
                except Exception as exc:
                    last_error = exc
                    if notice_callback is not None:
                        notice_callback(f"{source_name} 第 {attempt} 轮检索失败：{truncate_text(str(exc), 120)}")
                    continue
                if notice_callback is not None and source_results:
                    notice_callback(f"{source_name} 第 {attempt} 轮命中 {len(source_results)} 篇")
                round_results.extend(source_results)
            candidates = self._merge_candidate_lists(candidates, round_results)
            if notice_callback is not None:
                notice_callback(f"第 {attempt} 轮累计候选 {len(candidates)} 篇")
            self._emit_progress(
                progress_callback,
                stage="searching",
                label="检索论文源",
                detail=f"第 {attempt} 轮累计候选 {len(candidates)} 篇",
                percent=15 + round(attempt / total_specs * 15),
            )
            if len(candidates) >= plan.max_results:
                break

        if len(candidates) < plan.max_results:
            fallback_queries = [query for query in [plan.search_query, user_request] if normalize_title_key(query)]
            for fallback_index, query in enumerate(fallback_queries, start=1):
                if notice_callback is not None:
                    notice_callback(f"Scholar 补充检索第 {fallback_index} 轮：{truncate_text(query, 88)}")
                if not hasattr(self, "scholar"):
                    break
                try:
                    scholar_results = self.scholar.search(query, max_results=plan.max_results)
                except Exception as exc:
                    last_error = exc
                    if notice_callback is not None:
                        notice_callback(f"Scholar 补充检索失败：{truncate_text(str(exc), 120)}")
                    continue
                candidates = self._merge_candidate_lists(candidates, scholar_results)
                if notice_callback is not None:
                    notice_callback(f"Scholar 补充后累计候选 {len(candidates)} 篇")
                if len(candidates) >= plan.max_results:
                    break

        if candidates:
            return candidates[: plan.max_results]
        if last_error is not None:
            raise last_error
        return []

    def _resolve_explain_reference(
        self,
        reference: str,
        *,
        notice_callback: Callable[[str], None] | None = None,
        confirmation_callback: Callable[[dict[str, object]], bool] | None = None,
    ) -> Paper:
        local_exact = self.library.find_by_title(reference)
        if local_exact is not None:
            return local_exact.paper

        local_fuzzy = self.library.find_best_title_match(reference)
        if local_fuzzy is not None:
            return local_fuzzy.paper

        cleaned_reference = extract_paper_reference_text(reference)
        resolvers = [("arXiv", self.arxiv.resolve_reference)]
        if hasattr(self, "openreview"):
            resolvers.append(("OpenReview", self.openreview.resolve_reference))
        if hasattr(self, "scholar"):
            resolvers.append(("Google Scholar", self.scholar.resolve_reference))
        for source_name, resolver in resolvers:
            try:
                paper = resolver(cleaned_reference)
                self._confirm_reference_match(
                    cleaned_reference,
                    paper,
                    source_name=source_name,
                    confirmation_callback=confirmation_callback,
                    notice_callback=notice_callback,
                )
                return paper
            except LookupError:
                continue
            except (HTTPError, URLError, ArxivError, ScholarBlockedError, OpenReviewAuthError, OpenReviewClientUnavailableError, OSError) as exc:
                if notice_callback is not None:
                    notice_callback(
                        f"{source_name} 解析失败，已切换下一个来源：{truncate_text(str(exc), 120)}"
                    )
                continue
        raise LookupError(cleaned_reference)

    def _confirm_reference_match(
        self,
        reference_text: str,
        paper: Paper,
        *,
        source_name: str,
        confirmation_callback: Callable[[dict[str, object]], bool] | None = None,
        notice_callback: Callable[[str], None] | None = None,
    ) -> None:
        if not reference_text.strip():
            return
        if paper.arxiv_id and extract_paper_reference_text(reference_text) == paper.arxiv_id:
            return
        score = word_similarity(reference_text, paper.title)
        if score >= REFERENCE_CONFIRMATION_THRESHOLD:
            return
        detail = (
            f"候选论文标题与输入标题单词相似度较低（{score:.2f}）。"
            f"来源：{source_name}。候选题目：{truncate_text(paper.title, 120)}"
        )
        if notice_callback is not None:
            notice_callback(detail)
        if confirmation_callback is None:
            if notice_callback is not None:
                notice_callback("当前会话不支持交互确认，已按默认继续。")
            return
        approved = confirmation_callback(
            {
                "prompt": "找到的论文题目与输入标题差异较大，是否仍然保存并解析？",
                "detail": detail,
                "source": source_name,
                "requested_title": reference_text,
                "candidate_title": paper.title,
                "similarity_score": round(score, 4),
            }
        )
        if not approved:
            raise TaskCancelledError("用户拒绝保存和解析低相似度候选论文，任务已终止。")
        if notice_callback is not None:
            notice_callback("用户已确认继续处理该低相似度候选论文。")

    def _find_existing_record(self, paper: Paper) -> StoredPaper | None:
        existing = self.library.get_by_paper_id(paper.paper_id)
        if existing is not None:
            return existing
        if paper.arxiv_id:
            existing = self.library.get_by_arxiv_id(paper.arxiv_id)
            if existing is not None:
                return existing
        return self.library.find_by_title(paper.title)

    def _download_pdf_bytes(self, paper: Paper) -> bytes:
        if paper.arxiv_id and "arxiv.org" in (paper.pdf_url or ""):
            return self.arxiv.download_pdf_bytes(paper)
        if paper.openreview_id or paper.openreview_forum_id or "openreview.net" in (paper.pdf_url or ""):
            return self.openreview.download_pdf_bytes(paper)
        if paper.pdf_url:
            return self.scholar.download_pdf_bytes(paper)
        raise ValueError(f"No PDF URL available for {paper.title}")

    def _read_existing_pdf_bytes(self, record: StoredPaper | None) -> bytes:
        if record is None:
            return b""
        pdf_path = self.settings.repo_root / record.pdf_path
        return pdf_path.read_bytes() if pdf_path.exists() else b""

    def _enrich_paper_metadata(
        self,
        paper: Paper,
        *,
        notice_callback: Callable[[str], None] | None = None,
    ) -> Paper:
        merged, _ = self._enrich_paper_metadata_with_report(paper, notice_callback=notice_callback)
        return merged

    def _enrich_paper_metadata_with_report(
        self,
        paper: Paper,
        *,
        notice_callback: Callable[[str], None] | None = None,
    ) -> tuple[Paper, list[dict[str, object]]]:
        merged = paper
        source_reports: list[dict[str, object]] = []
        if hasattr(self, "openreview"):
            try:
                openreview_paper = self.openreview.enrich_metadata(merged)
                updated = self._merge_candidate_pair(merged, openreview_paper)
                changed_fields = self._metadata_field_changes(merged, updated)
                source_reports.append(
                    {
                        "source": "OpenReview",
                        "status": "updated" if changed_fields else "unchanged",
                        "message": (
                            f"补充了 {'、'.join(changed_fields)}。"
                            if changed_fields
                            else "未返回新的收录或链接信息。"
                        ),
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
        if hasattr(self, "scholar"):
            try:
                if hasattr(self.scholar, "enrich_metadata_report"):
                    scholar_report = self.scholar.enrich_metadata_report(merged)
                    scholar_paper = scholar_report.get("paper", merged)
                    updated = self._merge_candidate_pair(merged, scholar_paper)
                    changed_fields = self._metadata_field_changes(merged, updated)
                    fallback_used = scholar_report.get("fallback_used") or ""
                    source_reports.append(
                        {
                            "source": "Google Scholar",
                            "status": str(scholar_report.get("status") or ("updated" if changed_fields else "unchanged")),
                            "message": str(
                                scholar_report.get("message")
                                or (
                                    f"补充了 {'、'.join(changed_fields)}。"
                                    if changed_fields
                                    else "未返回新的收录或引用信息。"
                                )
                            ),
                            "changed_fields": changed_fields,
                            "fallback_used": fallback_used,
                        }
                    )
                    merged = updated
                else:
                    scholar_paper = self.scholar.enrich_metadata(merged)
                    updated = self._merge_candidate_pair(merged, scholar_paper)
                    changed_fields = self._metadata_field_changes(merged, updated)
                    source_reports.append(
                        {
                            "source": "Google Scholar",
                            "status": "updated" if changed_fields else "unchanged",
                            "message": (
                                f"补充了 {'、'.join(changed_fields)}。"
                                if changed_fields
                                else "未返回新的收录或引用信息。"
                            ),
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

    @staticmethod
    def _metadata_field_changes(before: Paper, after: Paper) -> list[str]:
        changes: list[str] = []
        if (
            before.venue.name != after.venue.name
            or before.venue.kind != after.venue.kind
            or before.venue.year != after.venue.year
        ):
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

    @staticmethod
    def _build_metadata_refresh_result(
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

    def _merge_candidate_lists(self, current: list[Paper], incoming: list[Paper]) -> list[Paper]:
        merged: dict[str, Paper] = {paper_identity_key(paper): paper for paper in current}
        for paper in incoming:
            identity = paper_identity_key(paper)
            if identity in merged:
                merged[identity] = self._merge_candidate_pair(merged[identity], paper)
                continue
            title_match_key = self._find_title_match_key(merged, paper)
            if title_match_key:
                merged[title_match_key] = self._merge_candidate_pair(merged[title_match_key], paper)
                continue
            merged[identity] = paper
        return unique_by_paper_identity(merged.values())

    def _find_title_match_key(self, existing: dict[str, Paper], candidate: Paper) -> str | None:
        candidate_year = venue_or_published_year(candidate)
        for key, paper in existing.items():
            if title_similarity(candidate.title, paper.title) < 0.93:
                continue
            existing_year = venue_or_published_year(paper)
            if candidate_year and existing_year and candidate_year != existing_year:
                continue
            return key
        return None

    def _merge_candidate_pair(self, left: Paper, right: Paper) -> Paper:
        if left is right:
            return left
        source_rank = {"arxiv": 3, "openreview": 2, "scholar": 1}
        primary = left if source_rank.get(left.source_primary, 0) >= source_rank.get(right.source_primary, 0) else right
        secondary = right if primary is left else left
        venue = self._choose_venue(left, right)
        citation_holder = self._choose_citation_holder(left, right)
        citation_count = citation_holder.citation_count if citation_holder is not None else None
        citation_source = citation_holder.citation_source if citation_holder is not None else ""
        citation_updated_at = citation_holder.citation_updated_at if citation_holder is not None else ""
        source_primary = "arxiv" if (left.arxiv_id or right.arxiv_id) else ("openreview" if (left.openreview_id or right.openreview_id or left.openreview_forum_id or right.openreview_forum_id) else primary.source_primary)
        arxiv_id = left.arxiv_id or right.arxiv_id
        openreview_id = left.openreview_id or right.openreview_id
        openreview_forum_id = left.openreview_forum_id or right.openreview_forum_id
        paper_id = arxiv_id or (f"openreview:{openreview_forum_id or openreview_id}" if (openreview_forum_id or openreview_id) else primary.paper_id)
        pdf_url = self._choose_pdf_url(left, right)
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
            categories=self._merge_string_lists(left.categories, right.categories),
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

    @staticmethod
    def _choose_citation_holder(left: Paper, right: Paper) -> Paper | None:
        def rank(paper: Paper) -> tuple[int, int]:
            source_rank = {
                "google_scholar": 3,
                "semantic_scholar": 2,
                "openalex": 1,
                "crossref": 1,
            }
            return (
                source_rank.get(paper.citation_source or "", 0),
                1 if paper.citation_count is not None else 0,
            )

        candidates = [paper for paper in (left, right) if paper.citation_count is not None]
        if not candidates:
            return None
        return max(candidates, key=rank)

    @staticmethod
    def _merge_string_lists(left: list[str], right: list[str]) -> list[str]:
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

    @staticmethod
    def _choose_venue(left: Paper, right: Paper):
        ranked = {"openreview": 3, "scholar": 2, "arxiv": 1}
        candidates = sorted([left, right], key=lambda item: ranked.get(item.source_primary, 0), reverse=True)
        for candidate in candidates:
            if candidate.venue.name:
                return candidate.venue
        return candidates[0].venue

    @staticmethod
    def _choose_pdf_url(left: Paper, right: Paper) -> str:
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
            focus = record.digest.problem or record.digest.method or record.digest.one_sentence_takeaway or record.paper.abstract
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

    @staticmethod
    def _processing_percent(index: int, step: int, total: int) -> int:
        if total <= 0:
            return 30
        completed_steps = max(0, ((index - 1) * 4) + step)
        return min(88, 30 + round((completed_steps / (total * 4)) * 58))

    @staticmethod
    def _emit_progress(
        progress_callback: Callable[[dict[str, object]], None] | None,
        *,
        stage: str,
        label: str,
        detail: str,
        percent: int,
        indeterminate: bool = False,
        paper_index: int | None = None,
        paper_total: int | None = None,
        current_title: str | None = None,
    ) -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "stage": stage,
                "label": label,
                "detail": detail,
                "percent": percent,
                "indeterminate": indeterminate,
                "paper_index": paper_index,
                "paper_total": paper_total,
                "current_title": current_title,
            }
        )

    def _save_report(self, user_request: str, markdown: str) -> str:
        self.settings.reports_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = sanitize_path_component(user_request, max_length=48)
        report_path = self.settings.reports_root / f"{timestamp}_{name}.md"
        write_text_atomic(report_path, markdown, encoding="utf-8")
        return report_path.relative_to(self.settings.repo_root).as_posix()
