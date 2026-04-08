from __future__ import annotations

import re
from typing import Callable

from autopapers.json_utils import extract_json_object
from autopapers.llm.minimax import MiniMaxClient, MiniMaxError
from autopapers.models import Paper, PaperDigest, RequestPlan, StoredPaper
from autopapers.utils import (
    extract_paper_reference_text,
    extract_paper_reference_texts,
    normalize_whitespace,
    parse_arxiv_id,
    truncate_text,
)


PLAN_PROMPT = """你是 AutoPapers 的任务规划器。
你的职责是把用户请求转换成结构化 JSON。

只允许输出一个 JSON 对象，禁止输出 Markdown、解释或代码块。

JSON Schema:
{
  "intent": "discover_papers" | "explain_paper",
  "user_goal": "string",
  "search_query": "string",
  "paper_refs": ["string"],
  "max_results": 1-20,
  "reuse_local": true,
  "rationale": "string"
}

规则:
1. 如果用户给的是明确论文标题、arXiv ID、arXiv URL，intent 设为 explain_paper。
2. 如果用户要找某个方向的新论文、综述某个研究主题，intent 设为 discover_papers。
3. search_query 要适合直接用于 arXiv 检索。
4. paper_refs 仅保留明确论文标识或标题。
5. max_results 根据用户语义估计，默认 5。
"""

DIGEST_PROMPT = """你是 AutoPapers 的论文摘要器。
给定论文元数据、抽取的正文片段、以及已有本地论文上下文，输出一个 JSON 对象。

只允许输出一个 JSON 对象，禁止输出 Markdown、解释或代码块。

JSON Schema:
{
  "major_topic": "一级方向",
  "minor_topic": "二级方向",
  "keywords": ["关键词1", "关键词2"],
  "one_sentence_takeaway": "一句话总结",
  "background": "研究背景",
  "problem": "核心问题",
  "method": "方法概述",
  "findings": ["发现1", "发现2"],
  "limitations": ["局限1", "局限2"],
  "relevance": "该论文与用户任务以及本地论文库的关系"
}

要求:
1. 全部字段都用中文。
2. major_topic 和 minor_topic 要适合做文件夹名称。
3. findings 和 limitations 各输出 2-4 条。
4. 优先利用论文正文片段；若正文不足，再参考摘要。
"""


class Planner:
    def __init__(self, client: MiniMaxClient, default_max_results: int = 5) -> None:
        self.client = client
        self.default_max_results = default_max_results

    def plan_request(
        self,
        user_request: str,
        library_snapshot: str,
        max_results: int | None = None,
        *,
        notice_callback: Callable[[str], None] | None = None,
    ) -> RequestPlan:
        requested_limit = max_results or self.default_max_results
        prompt = (
            f"用户请求:\n{user_request.strip()}\n\n"
            f"当前本地论文库概览:\n{truncate_text(library_snapshot, 3000)}\n\n"
            f"默认返回条数: {requested_limit}\n"
        )
        try:
            raw = self.client.chat_text(
                [
                    {"role": "system", "content": PLAN_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_completion_tokens=800,
                retry_context="任务规划",
                notice_callback=notice_callback,
            )
        except MiniMaxError:
            if notice_callback is not None:
                notice_callback("任务规划连续 3 次失败，已切换到本地回退策略。")
            return self._fallback_plan(user_request, requested_limit)
        try:
            data = extract_json_object(raw)
            paper_refs = self._normalize_paper_refs(
                data.get("paper_refs", []),
                user_request=user_request,
                intent=str(data.get("intent", "")),
            )
            resolved_intent = self._resolve_request_intent(
                str(data.get("intent", "")),
                user_request=user_request,
                paper_refs=paper_refs,
            )
            search_query = "" if resolved_intent == "explain_paper" else normalize_whitespace(
                str(data.get("search_query", user_request))
            )
            return RequestPlan(
                intent=resolved_intent,
                user_goal=normalize_whitespace(str(data.get("user_goal", user_request))),
                search_query=search_query,
                paper_refs=paper_refs,
                max_results=max(1, min(int(data.get("max_results", requested_limit)), 20)),
                reuse_local=bool(data.get("reuse_local", True)),
                rationale=normalize_whitespace(str(data.get("rationale", ""))),
            )
        except (ValueError, TypeError):
            if notice_callback is not None:
                notice_callback("任务规划响应解析失败，已切换到本地回退策略。")
            return self._fallback_plan(user_request, requested_limit)

    def digest_paper(
        self,
        user_request: str,
        paper: Paper,
        extracted_text: str,
        related_papers: list[StoredPaper],
        *,
        notice_callback: Callable[[str], None] | None = None,
    ) -> PaperDigest:
        related_context = self._related_context(related_papers)
        prompt = (
            f"用户请求:\n{user_request.strip()}\n\n"
            f"论文标题: {paper.title}\n"
            f"arXiv ID: {paper.arxiv_id}\n"
            f"作者: {', '.join(paper.authors)}\n"
            f"分类: {paper.primary_category} | {', '.join(paper.categories)}\n"
            f"摘要:\n{paper.abstract}\n\n"
            f"正文抽取片段:\n{truncate_text(extracted_text or '无正文片段，可参考摘要。', 16000)}\n\n"
            f"本地相关论文:\n{truncate_text(related_context, 3000)}\n"
        )
        try:
            raw = self.client.chat_text(
                [
                    {"role": "system", "content": DIGEST_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_completion_tokens=1500,
                retry_context=f"论文摘要：{truncate_text(paper.title, 48)}",
                notice_callback=notice_callback,
            )
        except MiniMaxError:
            if notice_callback is not None:
                notice_callback(f"论文摘要生成连续 3 次失败，已回退为摘要驱动总结：{truncate_text(paper.title, 48)}")
            return self._fallback_digest(paper)
        try:
            data = extract_json_object(raw)
            return PaperDigest(
                major_topic=normalize_whitespace(str(data.get("major_topic", ""))) or "未分类方向",
                minor_topic=normalize_whitespace(str(data.get("minor_topic", ""))) or "待整理子方向",
                keywords=self._normalize_list(data.get("keywords", []), fallback=paper.categories[:5]),
                one_sentence_takeaway=normalize_whitespace(str(data.get("one_sentence_takeaway", "")))
                or self._fallback_takeaway(paper),
                background=normalize_whitespace(str(data.get("background", ""))) or "摘要信息不足。",
                problem=normalize_whitespace(str(data.get("problem", ""))) or "待补充。",
                method=normalize_whitespace(str(data.get("method", ""))) or "待补充。",
                findings=self._normalize_list(data.get("findings", []), fallback=self._fallback_findings(paper)),
                limitations=self._normalize_list(data.get("limitations", []), fallback=["需要人工进一步阅读原文验证细节。"]),
                relevance=normalize_whitespace(str(data.get("relevance", ""))) or "与当前研究主题相关。",
            )
        except (ValueError, TypeError):
            if notice_callback is not None:
                notice_callback(f"论文摘要响应解析失败，已回退为摘要驱动总结：{truncate_text(paper.title, 48)}")
            return self._fallback_digest(paper)

    @staticmethod
    def _normalize_intent(raw_value: str) -> str:
        value = raw_value.strip().lower()
        if value == "explain_paper":
            return "explain_paper"
        return "discover_papers"

    def _fallback_plan(self, user_request: str, max_results: int) -> RequestPlan:
        arxiv_id = parse_arxiv_id(user_request)
        discover_markers = ("找", "搜索", "检索", "最新", "recent", "new", "方向", "相关", "推荐")
        explain_markers = ("介绍", "解释", "讲讲", "这篇论文", "paper", "survey", "article")
        paper_refs = extract_paper_reference_texts(user_request)
        if arxiv_id:
            intent = "explain_paper"
        elif self._should_lookup_specific_papers(user_request, paper_refs):
            intent = "explain_paper"
        elif any(marker in user_request for marker in discover_markers):
            intent = "discover_papers"
        elif any(marker in user_request.lower() for marker in explain_markers):
            intent = "explain_paper"
        else:
            intent = "discover_papers"

        search_query = "" if intent == "explain_paper" else normalize_whitespace(user_request)
        paper_refs = paper_refs if intent == "explain_paper" else []
        return RequestPlan(
            intent=intent,
            user_goal=normalize_whitespace(user_request),
            search_query=search_query,
            paper_refs=paper_refs,
            max_results=max_results,
            reuse_local=True,
            rationale="Fallback heuristic plan.",
        )

    def _fallback_digest(self, paper: Paper) -> PaperDigest:
        if paper.primary_category and "." in paper.primary_category:
            major_raw, _minor_raw = paper.primary_category.split(".", 1)
            major_topic = major_raw.upper()
            minor_topic = paper.primary_category
        else:
            major_topic = "未分类方向"
            minor_topic = paper.primary_category or "待整理子方向"
        return PaperDigest(
            major_topic=major_topic,
            minor_topic=minor_topic,
            keywords=paper.categories[:5] or ["arXiv"],
            one_sentence_takeaway=self._fallback_takeaway(paper),
            background="摘要驱动的默认总结。",
            problem="需要人工进一步阅读原文确认问题定义。",
            method="需要人工进一步阅读原文确认方法细节。",
            findings=self._fallback_findings(paper),
            limitations=["未获取稳定的正文解析结果，当前总结主要基于摘要。"],
            relevance="可作为当前主题的候选参考论文。",
        )

    @staticmethod
    def _normalize_list(value: object, fallback: list[str]) -> list[str]:
        if isinstance(value, list):
            normalized = [normalize_whitespace(str(item)) for item in value if normalize_whitespace(str(item))]
            if normalized:
                return normalized[:8]
        return fallback

    @staticmethod
    def _fallback_takeaway(paper: Paper) -> str:
        sentences = Planner._abstract_sentences(paper.abstract)
        if sentences:
            return sentences[0]
        return paper.title

    @staticmethod
    def _fallback_findings(paper: Paper) -> list[str]:
        sentences = Planner._abstract_sentences(paper.abstract)
        if sentences:
            return sentences[:3]
        return ["暂无额外发现。"]

    @staticmethod
    def _abstract_sentences(text: str) -> list[str]:
        normalized = normalize_whitespace(text)
        if not normalized:
            return []
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[。！？!?；;])\s+|(?<=[.])\s+(?=[A-Z0-9\"“‘'])", normalized)
            if part.strip()
        ]
        return sentences or [normalized]

    @staticmethod
    def _related_context(records: list[StoredPaper]) -> str:
        if not records:
            return "暂无。"
        lines: list[str] = []
        for record in records[:5]:
            lines.append(
                f"- {record.paper.title} | {record.digest.major_topic}/{record.digest.minor_topic} | "
                f"{record.digest.one_sentence_takeaway}"
            )
        return "\n".join(lines)

    @staticmethod
    def _normalize_paper_refs(raw_value: object, *, user_request: str, intent: str) -> list[str]:
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
            seen: set[str] = set()
            unique_refs: list[str] = []
            for ref in refs:
                if ref in seen:
                    continue
                seen.add(ref)
                unique_refs.append(ref)
            return unique_refs

        if normalized_intent == "explain_paper":
            return extract_paper_reference_texts(user_request)
        return []

    def _resolve_request_intent(self, raw_intent: str, *, user_request: str, paper_refs: list[str]) -> str:
        if self._should_lookup_specific_papers(user_request, paper_refs):
            return "explain_paper"
        return self._normalize_intent(raw_intent)

    @staticmethod
    def _should_lookup_specific_papers(user_request: str, paper_refs: list[str]) -> bool:
        if not paper_refs:
            return False
        lowered = user_request.lower()
        exact_lookup_markers = (
            "这篇论文",
            "这几篇论文",
            "这些论文",
            "以下论文",
            "下列论文",
            "论文列表",
            "paper list",
        )
        lookup_verbs = ("找", "查", "定位", "介绍", "解释", "讲讲", "总结", "分析", "对比", "compare")
        relation_markers = (
            "相关工作",
            "相关论文",
            "类似工作",
            "类似论文",
            "延伸阅读",
            "拓展阅读",
            "围绕",
            "基于这些论文",
            "受这些论文启发",
            "similar papers",
            "related work",
        )
        if any(marker in user_request for marker in relation_markers) or any(marker in lowered for marker in relation_markers):
            return False
        if parse_arxiv_id(user_request):
            return True
        if any(marker in user_request for marker in exact_lookup_markers):
            return True
        if len(paper_refs) > 1 and any(marker in user_request for marker in lookup_verbs):
            return True
        if len(paper_refs) == 1 and any(marker in user_request for marker in ("这篇论文", "该论文")) and any(
            marker in user_request for marker in lookup_verbs
        ):
            return True
        return False
