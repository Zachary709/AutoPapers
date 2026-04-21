from __future__ import annotations

import re

from autopapers.common.reference_parsing import extract_paper_reference_texts, parse_arxiv_id
from autopapers.common.text_normalization import normalize_title_key, normalize_whitespace
from autopapers.models import Paper, PaperDigest, RequestPlan, StoredPaper
from autopapers.pdf import ExtractedPaperContent
from autopapers.llm.context_builder import abstract_sentences, best_available_sentences


def fallback_plan(user_request: str, max_results: int) -> RequestPlan:
    arxiv_id = parse_arxiv_id(user_request)
    discover_markers = ("找", "搜索", "检索", "最新", "recent", "new", "方向", "相关", "推荐")
    explain_markers = ("介绍", "解释", "讲讲", "这篇论文", "paper", "survey", "article")
    paper_refs = extract_paper_reference_texts(user_request)
    if arxiv_id:
        intent = "explain_paper"
    elif should_lookup_specific_papers(user_request, paper_refs):
        intent = "explain_paper"
    elif any(marker in user_request for marker in discover_markers):
        intent = "discover_papers"
    elif any(marker in user_request.lower() for marker in explain_markers):
        intent = "explain_paper"
    else:
        intent = "discover_papers"
    return RequestPlan(
        intent=intent,
        user_goal=normalize_whitespace(user_request),
        search_query="" if intent == "explain_paper" else normalize_whitespace(user_request),
        paper_refs=paper_refs if intent == "explain_paper" else [],
        max_results=max_results,
        reuse_local=True,
        rationale="Fallback heuristic plan.",
    )


def fallback_digest(paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> PaperDigest:
    content = extracted_content or ExtractedPaperContent()
    return PaperDigest(
        major_topic=fallback_major_topic(paper),
        minor_topic=fallback_minor_topic(paper),
        keywords=paper.categories[:5] or ["arXiv"],
        abstract_zh=fallback_abstract_zh(paper),
        one_sentence_takeaway=fallback_takeaway(paper, content),
        problem=fallback_problem(paper, content),
        background=fallback_background(content),
        method=fallback_method(content),
        experiment_setup=fallback_experiment_setup(content),
        findings=fallback_findings(paper, content),
        limitations=fallback_limitations(content),
        relevance=fallback_relevance(paper, content, []),
        improvement_ideas=fallback_improvement_ideas(content),
    )


def fallback_major_topic(paper: Paper) -> str:
    return paper.primary_category.split(".", 1)[0].upper() if paper.primary_category and "." in paper.primary_category else "未分类方向"


def fallback_minor_topic(paper: Paper) -> str:
    return paper.primary_category or "待整理子方向"


def coerce_extracted_content(extracted_text: ExtractedPaperContent | str) -> ExtractedPaperContent:
    if isinstance(extracted_text, ExtractedPaperContent):
        return extracted_text
    raw_text = normalize_whitespace(str(extracted_text or ""))
    return ExtractedPaperContent(raw_body=raw_text) if raw_text else ExtractedPaperContent()


def fallback_takeaway(paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> str:
    content = extracted_content or ExtractedPaperContent()
    sentences = best_available_sentences(content, paper.abstract)
    return sentences[0] if sentences else paper.title


def fallback_abstract_zh(paper: Paper) -> str:
    normalized = normalize_whitespace(paper.abstract)
    if not normalized:
        return ""
    if re.search(r"[\u4e00-\u9fff]", normalized):
        return normalized
    return ""


def fallback_problem(paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> str:
    content = extracted_content or ExtractedPaperContent()
    sentences = best_available_sentences(content, paper.abstract)
    if len(sentences) >= 2:
        return "\n\n".join(sentences[:2])
    return sentences[0] if sentences else ""


def fallback_background(extracted_content: ExtractedPaperContent) -> str:
    sentences = abstract_sentences(extracted_content.introduction or extracted_content.conclusion)
    if len(sentences) >= 2:
        return "\n\n".join(sentences[:2])
    return sentences[0] if sentences else ""


def fallback_method(extracted_content: ExtractedPaperContent) -> str:
    sentences = abstract_sentences(extracted_content.method)
    if not sentences:
        return ""
    body = "\n\n".join(sentences[:4])
    if extracted_content.equations:
        body += "\n\n可识别的公式线索：\n" + "\n".join(f"- {item}" for item in extracted_content.equations[:3])
    return body


def fallback_experiment_setup(extracted_content: ExtractedPaperContent) -> str:
    sentences = abstract_sentences(extracted_content.experiments)
    return "\n\n".join(sentences[:3]) if sentences else ""


def fallback_findings(paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> list[str]:
    content = extracted_content or ExtractedPaperContent()
    experiment_sentences = abstract_sentences(content.experiments)
    if experiment_sentences:
        return experiment_sentences[:4]
    abstract_sents = abstract_sentences(paper.abstract)
    return abstract_sents[:2] if abstract_sents else []


def fallback_limitations(extracted_content: ExtractedPaperContent) -> list[str]:
    conclusion_sentences = abstract_sentences(extracted_content.conclusion)
    return [
        sentence
        for sentence in conclusion_sentences
        if any(marker in sentence.lower() for marker in ("limitation", "future work", "challenge", "constraint", "不足", "局限"))
    ][:3]


def fallback_relevance(paper: Paper, extracted_content: ExtractedPaperContent, related_papers: list[StoredPaper]) -> str:
    if related_papers:
        return "可与本地已有相关论文联动阅读，用于补足该主题的理解。"
    if extracted_content.method or extracted_content.experiments:
        return "该论文提供了较完整的正文信息，适合作为该方向的重点阅读材料。"
    return "该论文可作为当前主题的候选参考论文。" if paper.abstract else ""


def fallback_improvement_ideas(extracted_content: ExtractedPaperContent) -> list[str]:
    conclusion_sentences = abstract_sentences(extracted_content.conclusion)
    return [
        sentence
        for sentence in conclusion_sentences
        if any(marker in sentence.lower() for marker in ("future work", "improve", "extend", "future", "优化", "扩展", "未来"))
    ][:3]


def normalize_paper_refs(raw_value: object, *, user_request: str, intent: str) -> list[str]:
    normalized_intent = intent.strip().lower()
    if isinstance(raw_value, list):
        candidates = [str(item) for item in raw_value if normalize_whitespace(str(item))]
    elif normalize_whitespace(str(raw_value)):
        candidates = [str(raw_value)]
    else:
        candidates = []
    refs: list[str] = []
    for candidate in candidates:
        refs.extend(extract_paper_reference_texts(candidate))
    if refs:
        unique_refs: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            if ref not in seen:
                seen.add(ref)
                unique_refs.append(ref)
        return unique_refs
    return extract_paper_reference_texts(user_request) if normalized_intent == "explain_paper" else []


def resolve_request_intent(raw_intent: str, *, user_request: str, paper_refs: list[str]) -> str:
    return "explain_paper" if should_lookup_specific_papers(user_request, paper_refs) else normalize_intent(raw_intent)


def normalize_intent(raw_value: str) -> str:
    return "explain_paper" if raw_value.strip().lower() == "explain_paper" else "discover_papers"


def should_lookup_specific_papers(user_request: str, paper_refs: list[str]) -> bool:
    if not paper_refs:
        return False
    lowered = user_request.lower()
    exact_lookup_markers = ("这篇论文", "这几篇论文", "这些论文", "以下论文", "下列论文", "论文列表", "paper list")
    lookup_verbs = ("找", "查", "定位", "介绍", "解释", "讲讲", "总结", "分析", "对比", "compare")
    relation_markers = ("相关工作", "相关论文", "类似工作", "类似论文", "延伸阅读", "拓展阅读", "围绕", "基于这些论文", "受这些论文启发", "similar papers", "related work")
    if any(marker in user_request for marker in relation_markers) or any(marker in lowered for marker in relation_markers):
        return False
    if parse_arxiv_id(user_request):
        return True
    if any(marker in user_request for marker in exact_lookup_markers):
        return True
    if len(paper_refs) > 1 and any(marker in user_request for marker in lookup_verbs):
        return True
    if len(paper_refs) == 1 and any(marker in user_request for marker in ("这篇论文", "该论文")) and any(marker in user_request for marker in lookup_verbs):
        return True
    if len(paper_refs) == 1 and looks_like_single_paper_title(user_request, paper_refs[0]):
        return True
    return False


def looks_like_single_paper_title(user_request: str, reference: str) -> bool:
    normalized_request = normalize_title_key(user_request)
    normalized_reference = normalize_title_key(reference)
    if not normalized_reference or normalized_request != normalized_reference:
        return False

    raw_reference = normalize_whitespace(reference)
    if any(marker in raw_reference for marker in (":", "：", "?", "？", "!", "！")):
        return True

    english_words = re.findall(r"[A-Za-z][A-Za-z0-9'/-]*", raw_reference)
    if len(english_words) < 4:
        return False
    emphasized_words = sum(
        1
        for word in english_words
        if word.isupper() or (word[0].isupper() and len(word) > 2)
    )
    return emphasized_words >= max(2, len(english_words) // 2)
