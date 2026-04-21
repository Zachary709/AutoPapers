from __future__ import annotations

from pathlib import Path
from typing import Callable

from autopapers.common.paper_identity import unique_by_paper_identity
from autopapers.common.reference_parsing import extract_paper_reference_texts
from autopapers.common.text_normalization import truncate_text
from autopapers.models import RequestPlan, RunResult, StoredPaper
from autopapers.pdf import ExtractedPaperContent
from autopapers.pipeline.progress import emit_progress, processing_percent
from autopapers.pipeline.reporting import build_related_query, render_report, save_report


def run_agent_workflow(
    agent,
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

    def emit_progress_event(
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

    emit_progress_event("planning", "任务规划", "正在理解任务并生成执行方案", 5)
    emit_notice("开始任务规划", kind="milestone", stage="planning")
    plan_kwargs = {"notice_callback": notice_callback}
    if debug_callback is not None:
        plan_kwargs["debug_callback"] = debug_callback
    plan = agent.planner.plan_request(
        user_request,
        agent.library.topic_snapshot(),
        max_results=max_results,
        **plan_kwargs,
    )
    emit_progress_event("planning", "任务规划", f"规划完成：{plan.intent}，最多处理 {plan.max_results} 篇", 15)
    emit_notice(f"规划完成：{plan.intent}，最多处理 {plan.max_results} 篇", stage="planning")
    if plan.intent == "explain_paper":
        reference_count = len(plan.paper_refs or extract_paper_reference_texts(user_request))
        emit_progress_event("resolving", "解析论文引用", f"正在解析 {reference_count} 项引用", 18, paper_total=reference_count or None)
        emit_notice(f"开始解析论文引用：{reference_count} 项", kind="milestone", stage="resolving")
    else:
        emit_progress_event("searching", "检索论文源", "正在检索候选论文", 18)
        emit_notice("开始检索多源候选论文", kind="milestone", stage="searching")
    candidates = unique_by_paper_identity(
        agent._collect_candidates(
            plan,
            user_request,
            notice_callback=notice_callback,
            progress_callback=progress_callback,
            confirmation_callback=confirmation_callback,
        )
    )
    emit_progress_event("processing", "处理论文", f"候选论文已就绪：{len(candidates)} 篇", 30, paper_total=len(candidates) or None)
    emit_notice(f"候选论文已就绪：{len(candidates)} 篇", stage="processing")

    new_papers: list[StoredPaper] = []
    reused_papers: list[StoredPaper] = []
    taxonomy_context = agent.taxonomy.prompt_guidance()
    halfway_notice_sent = False
    total_candidates = len(candidates)

    if total_candidates:
        emit_notice(f"开始处理论文：{total_candidates} 篇", kind="milestone", stage="processing")

    for index, paper in enumerate(candidates, start=1):
        title_label = truncate_text(paper.title, 72)
        paper = agent._enrich_paper_metadata(paper, notice_callback=notice_callback)
        existing = agent._find_existing_record(paper)
        if existing and not refresh_existing:
            reused_papers.append(existing)
            emit_progress_event(
                "processing",
                "处理论文",
                f"复用本地论文 {index}/{total_candidates}：{title_label}",
                processing_percent(index, 1, total_candidates),
                paper_index=index,
                paper_total=total_candidates,
                current_title=title_label,
            )
            emit_notice(f"复用本地论文 {index}/{total_candidates}：{title_label}", stage="processing")
            emit_progress_event(
                "processing",
                "处理论文",
                f"已复用本地论文 {index}/{total_candidates}：{title_label}",
                processing_percent(index, 4, total_candidates),
                paper_index=index,
                paper_total=total_candidates,
                current_title=title_label,
            )
            if total_candidates >= 4 and not halfway_notice_sent and index * 2 >= total_candidates:
                emit_notice(f"论文处理已过半：{index}/{total_candidates}", kind="milestone", stage="processing")
                halfway_notice_sent = True
            continue

        emit_progress_event(
            "processing",
            "处理论文",
            f"处理论文 {index}/{total_candidates}：{title_label}",
            processing_percent(index, 1, total_candidates),
            paper_index=index,
            paper_total=total_candidates,
            current_title=title_label,
        )
        emit_notice(f"处理论文 {index}/{total_candidates}：{title_label}", stage="processing")
        related_for_summary = agent.library.search(
            f"{plan.search_query} {paper.title} {paper.primary_category}",
            limit=3,
            exclude_ids={paper.paper_id},
        )
        existing_pdf_bytes = agent._read_existing_pdf_bytes(existing) if existing is not None else b""
        try:
            if refresh_existing and existing_pdf_bytes:
                pdf_bytes = existing_pdf_bytes
                emit_notice(f"已复用本地 PDF 重新整理：{title_label}", stage="processing")
            else:
                pdf_bytes = agent._download_pdf_bytes(paper)
            if pdf_bytes and not (refresh_existing and existing_pdf_bytes):
                emit_notice(f"已下载 PDF：{title_label}", stage="processing")
        except Exception:
            pdf_bytes = b""
            emit_notice(f"PDF 下载失败，已跳过该论文：{title_label}", kind="warning", stage="processing")

        extracted_content = agent._extract_pdf_content(pdf_bytes)
        if extracted_content.has_substantial_text():
            emit_notice(f"已提取正文片段：{title_label}", stage="processing")
        else:
            emit_notice(f"未提取到稳定正文，已跳过该论文：{title_label}", kind="warning", stage="processing")
        emit_progress_event(
            "processing",
            "处理论文",
            f"PDF/正文准备完成 {index}/{total_candidates}：{title_label}",
            processing_percent(index, 2, total_candidates),
            paper_index=index,
            paper_total=total_candidates,
            current_title=title_label,
        )
        if not pdf_bytes or not extracted_content.has_substantial_text():
            if total_candidates >= 4 and not halfway_notice_sent and index * 2 >= total_candidates:
                emit_notice(f"论文处理已过半：{index}/{total_candidates}", kind="milestone", stage="processing")
                halfway_notice_sent = True
            continue
        digest_kwargs = {"taxonomy_context": taxonomy_context, "notice_callback": notice_callback}
        if debug_callback is not None:
            digest_kwargs["debug_callback"] = debug_callback
        digest = agent.planner.digest_paper(
            user_request,
            paper,
            extracted_content,
            related_for_summary,
            **digest_kwargs,
        )
        emit_progress_event(
            "processing",
            "处理论文",
            f"已完成结构化总结 {index}/{total_candidates}：{title_label}",
            processing_percent(index, 3, total_candidates),
            paper_index=index,
            paper_total=total_candidates,
            current_title=title_label,
        )
        digest = agent.taxonomy.canonicalize_digest(paper, digest, [*agent.library.all_records(), *new_papers, *reused_papers])
        stored = agent.library.upsert_paper(paper, digest, pdf_bytes, related_for_summary)
        new_papers.append(stored)
        emit_notice(f"已写入本地库：{title_label}", stage="processing")
        emit_progress_event(
            "processing",
            "处理论文",
            f"已写入本地库 {index}/{total_candidates}：{title_label}",
            processing_percent(index, 4, total_candidates),
            paper_index=index,
            paper_total=total_candidates,
            current_title=title_label,
        )
        if total_candidates >= 4 and not halfway_notice_sent and index * 2 >= total_candidates:
            emit_notice(f"论文处理已过半：{index}/{total_candidates}", kind="milestone", stage="processing")
            halfway_notice_sent = True

    related_papers: list[StoredPaper] = []
    if plan.reuse_local:
        emit_progress_event("related", "相关论文", "正在检索相关本地论文", 88, paper_total=total_candidates or None, paper_index=total_candidates or None)
        emit_notice("正在检索相关本地论文", stage="related")
        related_query = build_related_query(plan, user_request, new_papers, reused_papers)
        related_papers = agent.library.search(
            related_query,
            limit=5,
            exclude_ids={record.paper.paper_id for record in [*new_papers, *reused_papers]},
        )
        emit_progress_event("related", "相关论文", f"相关本地论文：{len(related_papers)} 篇", 94, paper_total=total_candidates or None, paper_index=total_candidates or None)
        emit_notice(f"相关本地论文：{len(related_papers)} 篇", stage="related")

    emit_progress_event("reporting", "生成报告", "正在整理最终报告与结果", 94, paper_total=total_candidates or None, paper_index=total_candidates or None)
    emit_notice("正在生成报告", kind="milestone", stage="reporting")
    report_markdown = render_report(user_request, plan, new_papers, reused_papers, related_papers)
    report_path = save_report(agent, user_request, report_markdown)
    emit_progress_event("reporting", "生成报告", f"报告已保存：{Path(report_path).name}", 99, paper_total=total_candidates or None, paper_index=total_candidates or None)
    emit_notice(f"任务完成，报告已保存：{Path(report_path).name}", stage="reporting")
    return RunResult(
        plan=plan,
        new_papers=new_papers,
        reused_papers=reused_papers,
        related_papers=related_papers,
        report_markdown=report_markdown,
        report_path=report_path,
    )


def reanalyze_library(
    agent,
    *,
    arxiv_ids: list[str] | None = None,
    paper_ids: list[str] | None = None,
    limit: int | None = None,
    download_missing_pdf: bool = False,
    format_only: bool = False,
    notice_callback: Callable[[str], None] | None = None,
    debug_callback: Callable[[str], None] | None = None,
) -> list[StoredPaper]:
    records = select_library_records(agent, paper_ids=paper_ids, arxiv_ids=arxiv_ids, limit=limit)
    if format_only:
        updated: list[StoredPaper] = []
        for index, record in enumerate(records, start=1):
            title_label = truncate_text(record.paper.title, 72)
            if notice_callback is not None:
                notice_callback(f"仅更新最终格式 {index}/{len(records)}：{title_label}")
            related_for_summary = agent.library.search(
                f"{record.paper.title} {record.paper.primary_category}",
                limit=3,
                exclude_ids={record.paper.paper_id},
            )
            format_kwargs = {"notice_callback": notice_callback}
            if debug_callback is not None:
                format_kwargs["debug_callback"] = debug_callback
            formatted_digest = agent.planner.tighten_digest_format_only(record.paper, record.digest, **format_kwargs)
            updated.append(agent.library.rewrite_digest(record.paper.paper_id, formatted_digest, related_for_summary, refresh_summaries=False))
        agent.library.refresh_summaries()
        return updated

    updated: list[StoredPaper] = []
    taxonomy_context = agent.taxonomy.prompt_guidance()
    for index, record in enumerate(records, start=1):
        title_label = truncate_text(record.paper.title, 72)
        if notice_callback is not None:
            notice_callback(f"重新分析论文 {index}/{len(records)}：{title_label}")
        pdf_path = agent.settings.repo_root / record.pdf_path
        pdf_bytes = pdf_path.read_bytes() if pdf_path.exists() else b""
        if not pdf_bytes and download_missing_pdf:
            try:
                pdf_bytes = agent._download_pdf_bytes(record.paper)
                if notice_callback is not None and pdf_bytes:
                    notice_callback(f"已补拉 PDF：{title_label}")
            except Exception:
                if notice_callback is not None:
                    notice_callback(f"缺失 PDF 且补拉失败：{title_label}")
        refreshed_paper = agent._enrich_paper_metadata(record.paper, notice_callback=notice_callback)
        extracted_content = agent._extract_pdf_content(pdf_bytes)
        related_for_summary = agent.library.search(
            f"{refreshed_paper.title} {refreshed_paper.primary_category}",
            limit=3,
            exclude_ids={record.paper.paper_id},
        )
        digest_kwargs = {"taxonomy_context": taxonomy_context, "notice_callback": notice_callback}
        if debug_callback is not None:
            digest_kwargs["debug_callback"] = debug_callback
        digest = agent.planner.digest_paper(
            f"请重新整理并深入总结这篇论文：{refreshed_paper.title}",
            refreshed_paper,
            extracted_content,
            related_for_summary,
            **digest_kwargs,
        )
        digest = agent.taxonomy.canonicalize_digest(refreshed_paper, digest, records)
        updated.append(agent.library.upsert_paper(refreshed_paper, digest, pdf_bytes, related_for_summary))
    agent.library.refresh_summaries()
    return updated


def select_library_records(
    agent,
    *,
    arxiv_ids: list[str] | None = None,
    paper_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[StoredPaper]:
    records = agent.library.all_records()
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
    agent,
    paper_id: str,
    *,
    notice_callback: Callable[[str], None] | None = None,
) -> dict | None:
    record = agent.library.get_by_paper_id(paper_id)
    if record is None:
        return None
    refreshed_paper, refresh_report = agent._enrich_paper_metadata_with_report(record.paper, notice_callback=notice_callback)
    refreshed_paper.paper_id = record.paper.paper_id
    refreshed_paper.source_primary = record.paper.source_primary
    changed_fields = agent._metadata_field_changes(record.paper, refreshed_paper)
    refresh_result = agent._build_metadata_refresh_result(paper=refreshed_paper, source_reports=refresh_report, changed_fields=changed_fields)
    if not changed_fields:
        return {"record": record, "refresh": refresh_result}
    pdf_path = agent.settings.repo_root / record.pdf_path
    pdf_bytes = pdf_path.read_bytes() if pdf_path.exists() else b""
    related_for_summary = agent.library.search(
        f"{refreshed_paper.title} {refreshed_paper.primary_category}",
        limit=3,
        exclude_ids={refreshed_paper.paper_id},
    )
    updated = agent.library.upsert_paper(refreshed_paper, record.digest, pdf_bytes, related_for_summary)
    if notice_callback is not None:
        notice_callback(refresh_result["message"])
    return {"record": updated, "refresh": refresh_result}


def normalize_library_topics(
    agent,
    *,
    notice_callback: Callable[[str], None] | None = None,
) -> list[StoredPaper]:
    records = list(agent.library.all_records())
    updated: list[StoredPaper] = []

    for index, record in enumerate(records, start=1):
        normalized_digest = agent.taxonomy.canonicalize_digest(record.paper, record.digest, records)
        if normalized_digest.major_topic == record.digest.major_topic and normalized_digest.minor_topic == record.digest.minor_topic:
            continue

        title_label = truncate_text(record.paper.title, 72)
        if notice_callback is not None:
            notice_callback(f"规范化主题 {index}/{len(records)}：{title_label} -> {normalized_digest.major_topic} / {normalized_digest.minor_topic}")
        pdf_path = agent.settings.repo_root / record.pdf_path
        pdf_bytes = pdf_path.read_bytes() if pdf_path.exists() else b""
        related_for_summary = agent.library.search(
            f"{record.paper.title} {record.paper.primary_category}",
            limit=3,
            exclude_ids={record.paper.paper_id},
        )
        updated.append(agent.library.upsert_paper(record.paper, normalized_digest, pdf_bytes, related_for_summary))

    agent.library.refresh_summaries()
    return updated


def extract_pdf_content(agent, pdf_bytes: bytes) -> ExtractedPaperContent:
    if hasattr(agent.extractor, "extract_structured"):
        return agent.extractor.extract_structured(pdf_bytes)
    extracted = agent.extractor.extract(pdf_bytes)
    return ExtractedPaperContent(raw_body=extracted)


def find_existing_record(agent, paper) -> StoredPaper | None:
    existing = agent.library.get_by_paper_id(paper.paper_id)
    if existing is not None:
        return existing
    if paper.arxiv_id:
        existing = agent.library.get_by_arxiv_id(paper.arxiv_id)
        if existing is not None:
            return existing
    return agent.library.find_by_title(paper.title)


def download_pdf_bytes(agent, paper) -> bytes:
    if paper.arxiv_id and "arxiv.org" in (paper.pdf_url or ""):
        return agent.arxiv.download_pdf_bytes(paper)
    if paper.openreview_id or paper.openreview_forum_id or "openreview.net" in (paper.pdf_url or ""):
        return agent.openreview.download_pdf_bytes(paper)
    if paper.pdf_url:
        return agent.scholar.download_pdf_bytes(paper)
    raise ValueError(f"No PDF URL available for {paper.title}")


def read_existing_pdf_bytes(agent, record: StoredPaper | None) -> bytes:
    if record is None:
        return b""
    pdf_path = agent.settings.repo_root / record.pdf_path
    return pdf_path.read_bytes() if pdf_path.exists() else b""
