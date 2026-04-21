from __future__ import annotations

from datetime import datetime
from typing import Callable

from autopapers.arxiv import ArxivClient
from autopapers.common.atomic_io import write_text_atomic
from autopapers.common.text_normalization import sanitize_path_component
from autopapers.config import Settings
from autopapers.http_client import build_url_opener
from autopapers.library import PaperLibrary
from autopapers.llm.minimax import MiniMaxClient
from autopapers.llm.planner import Planner
from autopapers.models import Paper, RequestPlan, RunResult, StoredPaper
from autopapers.openreview import OpenReviewClient
from autopapers.openreview_auth import OpenReviewAuthStore
from autopapers.pdf import ExtractedPaperContent, PDFTextExtractor
from autopapers.pipeline.candidate_collection import (
    REFERENCE_CONFIRMATION_THRESHOLD,
    collect_candidates,
    confirm_reference_match,
    resolve_explain_reference,
)
from autopapers.pipeline.metadata_enrichment import (
    build_metadata_refresh_result,
    enrich_paper_metadata,
    enrich_paper_metadata_with_report,
    find_title_match_key,
    merge_candidate_lists,
    merge_candidate_pair,
    metadata_field_changes,
)
from autopapers.pipeline.paper_processing import (
    download_pdf_bytes,
    extract_pdf_content,
    find_existing_record,
    normalize_library_topics,
    reanalyze_library,
    read_existing_pdf_bytes,
    refresh_paper_metadata,
    run_agent_workflow,
    select_library_records,
)
from autopapers.pipeline.progress import emit_progress, processing_percent
from autopapers.pipeline.reporting import (
    build_related_query,
    comparison_report_block,
    ordered_unique,
    paper_report_block,
    render_report,
    save_report,
    shared_keywords,
    suggest_reading_order,
)
from autopapers.retrieval import DiscoverySearchPlanner
from autopapers.scholar import ScholarClient
from autopapers.taxonomy import TopicTaxonomy


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
        return run_agent_workflow(
            self,
            user_request,
            max_results=max_results,
            refresh_existing=refresh_existing,
            notice_callback=notice_callback,
            timeline_callback=timeline_callback,
            progress_callback=progress_callback,
            confirmation_callback=confirmation_callback,
            debug_callback=debug_callback,
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
        return reanalyze_library(
            self,
            arxiv_ids=arxiv_ids,
            paper_ids=paper_ids,
            limit=limit,
            download_missing_pdf=download_missing_pdf,
            format_only=format_only,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
        )

    def _select_library_records(
        self,
        *,
        arxiv_ids: list[str] | None = None,
        paper_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[StoredPaper]:
        return select_library_records(self, arxiv_ids=arxiv_ids, paper_ids=paper_ids, limit=limit)

    def refresh_paper_metadata(
        self,
        paper_id: str,
        *,
        notice_callback: Callable[[str], None] | None = None,
    ) -> dict | None:
        return refresh_paper_metadata(self, paper_id, notice_callback=notice_callback)

    def normalize_library_topics(
        self,
        *,
        notice_callback: Callable[[str], None] | None = None,
    ) -> list[StoredPaper]:
        return normalize_library_topics(self, notice_callback=notice_callback)

    def _extract_pdf_content(self, pdf_bytes: bytes) -> ExtractedPaperContent:
        return extract_pdf_content(self, pdf_bytes)

    def _collect_candidates(
        self,
        plan: RequestPlan,
        user_request: str,
        *,
        notice_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
        confirmation_callback: Callable[[dict[str, object]], bool] | None = None,
    ) -> list[Paper]:
        return collect_candidates(
            self,
            plan,
            user_request,
            notice_callback=notice_callback,
            progress_callback=progress_callback,
            confirmation_callback=confirmation_callback,
        )

    def _resolve_explain_reference(
        self,
        reference: str,
        *,
        notice_callback: Callable[[str], None] | None = None,
        confirmation_callback: Callable[[dict[str, object]], bool] | None = None,
    ) -> Paper:
        return resolve_explain_reference(
            self,
            reference,
            notice_callback=notice_callback,
            confirmation_callback=confirmation_callback,
        )

    def _confirm_reference_match(
        self,
        reference_text: str,
        paper: Paper,
        *,
        source_name: str,
        confirmation_callback: Callable[[dict[str, object]], bool] | None = None,
        notice_callback: Callable[[str], None] | None = None,
    ) -> None:
        return confirm_reference_match(
            reference_text,
            paper,
            source_name=source_name,
            confirmation_callback=confirmation_callback,
            notice_callback=notice_callback,
        )

    def _find_existing_record(self, paper: Paper) -> StoredPaper | None:
        return find_existing_record(self, paper)

    def _download_pdf_bytes(self, paper: Paper) -> bytes:
        return download_pdf_bytes(self, paper)

    def _read_existing_pdf_bytes(self, record: StoredPaper | None) -> bytes:
        return read_existing_pdf_bytes(self, record)

    def _enrich_paper_metadata(
        self,
        paper: Paper,
        *,
        notice_callback: Callable[[str], None] | None = None,
    ) -> Paper:
        return enrich_paper_metadata(self, paper, notice_callback=notice_callback)

    def _enrich_paper_metadata_with_report(
        self,
        paper: Paper,
        *,
        notice_callback: Callable[[str], None] | None = None,
    ) -> tuple[Paper, list[dict[str, object]]]:
        return enrich_paper_metadata_with_report(self, paper, notice_callback=notice_callback)

    @staticmethod
    def _metadata_field_changes(before: Paper, after: Paper) -> list[str]:
        return metadata_field_changes(before, after)

    @staticmethod
    def _build_metadata_refresh_result(
        *,
        paper: Paper,
        source_reports: list[dict[str, object]],
        changed_fields: list[str],
    ) -> dict[str, object]:
        return build_metadata_refresh_result(
            paper=paper,
            source_reports=source_reports,
            changed_fields=changed_fields,
        )

    def _merge_candidate_lists(self, current: list[Paper], incoming: list[Paper]) -> list[Paper]:
        return merge_candidate_lists(self, current, incoming)

    @staticmethod
    def _find_title_match_key(existing: dict[str, Paper], candidate: Paper) -> str | None:
        return find_title_match_key(existing=existing, candidate=candidate)

    def _merge_candidate_pair(self, left: Paper, right: Paper) -> Paper:
        return merge_candidate_pair(self, left, right)

    def _build_related_query(
        self,
        plan: RequestPlan,
        user_request: str,
        new_papers: list[StoredPaper],
        reused_papers: list[StoredPaper],
    ) -> str:
        return build_related_query(plan, user_request, new_papers, reused_papers)

    def _render_report(
        self,
        user_request: str,
        plan: RequestPlan,
        new_papers: list[StoredPaper],
        reused_papers: list[StoredPaper],
        related_papers: list[StoredPaper],
    ) -> str:
        return render_report(user_request, plan, new_papers, reused_papers, related_papers)

    @staticmethod
    def _paper_report_block(record: StoredPaper) -> list[str]:
        return paper_report_block(record)

    def _comparison_report_block(self, records: list[StoredPaper]) -> list[str]:
        return comparison_report_block(records)

    @staticmethod
    def _shared_keywords(records: list[StoredPaper]) -> list[str]:
        return shared_keywords(records)

    @staticmethod
    def _ordered_unique(values) -> list[str]:
        return ordered_unique(values)

    @staticmethod
    def _suggest_reading_order(records: list[StoredPaper]) -> list[StoredPaper]:
        return suggest_reading_order(records)

    @staticmethod
    def _processing_percent(index: int, step: int, total: int) -> int:
        return processing_percent(index, step, total)

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
        emit_progress(
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

    def _save_report(self, user_request: str, markdown: str) -> str:
        self.settings.reports_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = sanitize_path_component(user_request, max_length=48)
        report_path = self.settings.reports_root / f"{timestamp}_{name}.md"
        write_text_atomic(report_path, markdown, encoding="utf-8")
        return report_path.relative_to(self.settings.repo_root).as_posix()
