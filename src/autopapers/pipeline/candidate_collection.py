from __future__ import annotations

from typing import Callable
from urllib.error import HTTPError, URLError

from autopapers.arxiv import ArxivError
from autopapers.common.paper_identity import paper_identity_key, title_similarity, unique_by_paper_identity, venue_or_published_year, word_similarity
from autopapers.common.reference_parsing import extract_paper_reference_text, extract_paper_reference_texts
from autopapers.common.text_normalization import normalize_title_key, truncate_text
from autopapers.models import Paper, RequestPlan, TaskCancelledError
from autopapers.openreview import OpenReviewAuthError, OpenReviewClientUnavailableError
from autopapers.pipeline.progress import emit_progress
from autopapers.scholar import ScholarBlockedError


REFERENCE_CONFIRMATION_THRESHOLD = 0.58


def collect_candidates(
    agent,
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
            emit_progress(
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
                resolved = agent._merge_candidate_lists(
                    resolved,
                    [
                        resolve_explain_reference(
                            agent,
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
    specs = agent.discovery_search_planner.build_specs(plan, user_request)
    total_specs = max(len(specs), 1)
    for attempt, spec in enumerate(specs, start=1):
        if notice_callback is not None:
            notice_callback(f"多源检索第 {attempt} 轮：{truncate_text(spec.query, 88)}")
        round_results: list[Paper] = []
        searchers = [
            (
                "arXiv",
                lambda: agent.arxiv.search(
                    spec.query,
                    max_results=plan.max_results,
                    field=spec.field,
                    sort_by=spec.sort_by,
                    sort_order=spec.sort_order,
                ),
            )
        ]
        if hasattr(agent, "openreview"):
            searchers.append(("OpenReview", lambda: agent.openreview.search(spec.query, max_results=plan.max_results)))
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
        candidates = agent._merge_candidate_lists(candidates, round_results)
        if notice_callback is not None:
            notice_callback(f"第 {attempt} 轮累计候选 {len(candidates)} 篇")
        emit_progress(
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
            if not hasattr(agent, "scholar"):
                break
            try:
                scholar_results = agent.scholar.search(query, max_results=plan.max_results)
            except Exception as exc:
                last_error = exc
                if notice_callback is not None:
                    notice_callback(f"Scholar 补充检索失败：{truncate_text(str(exc), 120)}")
                continue
            candidates = agent._merge_candidate_lists(candidates, scholar_results)
            if notice_callback is not None:
                notice_callback(f"Scholar 补充后累计候选 {len(candidates)} 篇")
            if len(candidates) >= plan.max_results:
                break

    if candidates:
        return candidates[: plan.max_results]
    if last_error is not None:
        raise last_error
    return []


def resolve_explain_reference(
    agent,
    reference: str,
    *,
    notice_callback: Callable[[str], None] | None = None,
    confirmation_callback: Callable[[dict[str, object]], bool] | None = None,
) -> Paper:
    local_exact = agent.library.find_by_title(reference)
    if local_exact is not None:
        return local_exact.paper

    local_fuzzy = agent.library.find_best_title_match(reference)
    if local_fuzzy is not None:
        return local_fuzzy.paper

    cleaned_reference = extract_paper_reference_text(reference)
    resolvers = [("arXiv", agent.arxiv.resolve_reference)]
    if hasattr(agent, "openreview"):
        resolvers.append(("OpenReview", agent.openreview.resolve_reference))
    if hasattr(agent, "scholar"):
        resolvers.append(("Google Scholar", agent.scholar.resolve_reference))
    for source_name, resolver in resolvers:
        try:
            paper = resolver(cleaned_reference)
            confirm_reference_match(
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
                notice_callback(f"{source_name} 解析失败，已切换下一个来源：{truncate_text(str(exc), 120)}")
            continue
    raise LookupError(cleaned_reference)


def confirm_reference_match(
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
