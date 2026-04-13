from __future__ import annotations

import json
import re
from typing import Callable

from autopapers.json_utils import extract_json_object
from autopapers.llm.minimax import MiniMaxClient, MiniMaxError
from autopapers.models import Paper, PaperDigest, RequestPlan, StoredPaper
from autopapers.pdf import ExtractedPaperContent
from autopapers.utils import extract_paper_reference_texts, normalize_whitespace, parse_arxiv_id, truncate_text

PLAN_PROMPT = """你是 AutoPapers 的任务规划器。只输出一个 JSON 对象。Schema 包含 intent/user_goal/search_query/paper_refs/max_results/reuse_local/rationale。若用户给的是明确论文标题或 arXiv 标识，intent 设为 explain_paper；若用户是在找某方向论文，intent 设为 discover_papers。"""
DIGEST_METADATA_PROMPT = """你是 AutoPapers 的论文整理器。只输出 JSON，字段为 major_topic/minor_topic/keywords。优先用中文。"""
DIGEST_OVERVIEW_PROMPT = """你是 AutoPapers 的论文讲解器，负责先把论文讲明白。只输出 JSON，字段为 one_sentence_takeaway/problem/background/relevance。全部用中文。"""
DIGEST_METHOD_PROMPT = """你是 AutoPapers 的方法解析器。只输出 JSON，字段为 method。请用中文解释方法；若有多步流程请分段或分点；若有公式请保留 $$...$$。"""
DIGEST_EXPERIMENT_PROMPT = """你是 AutoPapers 的实验分析器。只输出 JSON，字段为 experiment_setup/findings/limitations/improvement_ideas。优先用中文，实验设置可分段。"""
DIGEST_CLEANUP_PROMPT = """你是 AutoPapers 的中文清洗器。只输出 JSON，字段为 one_sentence_takeaway/problem/background/method/experiment_setup/findings/limitations/relevance/improvement_ideas。把英文叙述整理成自然中文，保留术语、模型名、数据集名和 LaTeX 公式；长段落要拆段，步骤要分点。"""


class Planner:
    def __init__(self, client: MiniMaxClient, default_max_results: int = 5) -> None:
        self.client = client
        self.default_max_results = default_max_results

    def plan_request(self, user_request: str, library_snapshot: str, max_results: int | None = None, *, notice_callback: Callable[[str], None] | None = None) -> RequestPlan:
        requested_limit = max_results or self.default_max_results
        prompt = (
            f"用户请求:\n{user_request.strip()}\n\n"
            f"当前本地论文库概览:\n{truncate_text(library_snapshot, 3000)}\n\n"
            f"默认返回条数: {requested_limit}\n"
        )
        try:
            raw = self.client.chat_text(
                [{"role": "system", "content": PLAN_PROMPT}, {"role": "user", "content": prompt}],
                temperature=0.1,
                max_completion_tokens=800,
                retry_context="任务规划",
                notice_callback=notice_callback,
            )
            data = extract_json_object(raw)
        except MiniMaxError:
            if notice_callback is not None:
                notice_callback("任务规划连续 3 次失败，已切换到本地回退策略。")
            return self._fallback_plan(user_request, requested_limit)
        except (ValueError, TypeError):
            if notice_callback is not None:
                notice_callback("任务规划响应解析失败，已切换到本地回退策略。")
            return self._fallback_plan(user_request, requested_limit)

        paper_refs = self._normalize_paper_refs(data.get("paper_refs", []), user_request=user_request, intent=str(data.get("intent", "")))
        resolved_intent = self._resolve_request_intent(str(data.get("intent", "")), user_request=user_request, paper_refs=paper_refs)
        search_query = "" if resolved_intent == "explain_paper" else normalize_whitespace(str(data.get("search_query", user_request)))
        return RequestPlan(
            intent=resolved_intent,
            user_goal=normalize_whitespace(str(data.get("user_goal", user_request))),
            search_query=search_query,
            paper_refs=paper_refs,
            max_results=max(1, min(int(data.get("max_results", requested_limit)), 20)),
            reuse_local=bool(data.get("reuse_local", True)),
            rationale=normalize_whitespace(str(data.get("rationale", ""))),
        )

    def digest_paper(self, user_request: str, paper: Paper, extracted_text: ExtractedPaperContent | str, related_papers: list[StoredPaper], *, taxonomy_context: str = "", notice_callback: Callable[[str], None] | None = None) -> PaperDigest:
        extracted_content = self._coerce_extracted_content(extracted_text)
        related_context = self._related_context(related_papers)
        overview_context = self._compose_context(extracted_content, include=("abstract", "introduction", "conclusion", "raw_body"), max_chars=14000)
        method_context = self._compose_context(extracted_content, include=("method", "introduction"), max_chars=16000)
        experiment_context = self._compose_context(extracted_content, include=("experiments", "conclusion"), max_chars=14000)
        metadata_context = self._compose_context(extracted_content, include=("abstract", "introduction", "method", "experiments", "conclusion", "raw_body"), max_chars=18000)

        if notice_callback is not None:
            if extracted_content.has_substantial_text():
                notice_callback(f"正在根据 PDF 正文分阶段整理：{truncate_text(paper.title, 48)}")
                if extracted_content.references_trimmed:
                    notice_callback(f"已剔除参考文献等后置内容：{truncate_text(paper.title, 48)}")
            else:
                notice_callback(f"PDF 正文提取不足，将结合摘要进行整理：{truncate_text(paper.title, 48)}")
        metadata = self._run_digest_stage(DIGEST_METADATA_PROMPT, self._build_digest_prompt(user_request, paper, related_context, section_context=metadata_context, stage_label="归档主题与关键词", taxonomy_context=taxonomy_context), retry_context=f"论文归档：{truncate_text(paper.title, 48)}", max_completion_tokens=600, notice_callback=notice_callback, stage_notice=f"正在归纳主题与关键词：{truncate_text(paper.title, 48)}")
        overview = self._run_digest_stage(DIGEST_OVERVIEW_PROMPT, self._build_digest_prompt(user_request, paper, related_context, section_context=overview_context, stage_label="论文概述、直觉与价值"), retry_context=f"论文概述：{truncate_text(paper.title, 48)}", max_completion_tokens=1000, notice_callback=notice_callback, stage_notice=f"正在生成论文概述：{truncate_text(paper.title, 48)}")
        method = self._run_digest_stage(DIGEST_METHOD_PROMPT, self._build_digest_prompt(user_request, paper, related_context, section_context=method_context, stage_label="方法与公式"), retry_context=f"论文方法：{truncate_text(paper.title, 48)}", max_completion_tokens=1400, notice_callback=notice_callback, stage_notice=f"正在解析方法与公式：{truncate_text(paper.title, 48)}")
        experiments = self._run_digest_stage(DIGEST_EXPERIMENT_PROMPT, self._build_digest_prompt(user_request, paper, related_context, section_context=experiment_context, stage_label="实验、局限与改进方向"), retry_context=f"论文实验：{truncate_text(paper.title, 48)}", max_completion_tokens=1200, notice_callback=notice_callback, stage_notice=f"正在整理实验与局限：{truncate_text(paper.title, 48)}")

        draft = PaperDigest(
            major_topic=normalize_whitespace(str((metadata or {}).get("major_topic", ""))) or self._fallback_major_topic(paper),
            minor_topic=normalize_whitespace(str((metadata or {}).get("minor_topic", ""))) or self._fallback_minor_topic(paper),
            keywords=self._normalize_list((metadata or {}).get("keywords", []), fallback=paper.categories[:5] or ["arXiv"]),
            one_sentence_takeaway=self._normalize_rich_text((overview or {}).get("one_sentence_takeaway", "")) or self._fallback_takeaway(paper, extracted_content),
            problem=self._normalize_rich_text((overview or {}).get("problem", "")) or self._fallback_problem(paper, extracted_content),
            background=self._normalize_rich_text((overview or {}).get("background", "")) or self._fallback_background(extracted_content),
            method=self._normalize_rich_text((method or {}).get("method", "")) or self._fallback_method(extracted_content),
            experiment_setup=self._normalize_rich_text((experiments or {}).get("experiment_setup", "")) or self._fallback_experiment_setup(extracted_content),
            findings=self._normalize_list((experiments or {}).get("findings", []), fallback=self._fallback_findings(paper, extracted_content)),
            limitations=self._normalize_list((experiments or {}).get("limitations", []), fallback=self._fallback_limitations(extracted_content)),
            relevance=self._normalize_rich_text((overview or {}).get("relevance", "")) or self._fallback_relevance(paper, extracted_content, related_papers),
            improvement_ideas=self._normalize_list((experiments or {}).get("improvement_ideas", []), fallback=self._fallback_improvement_ideas(extracted_content)),
        )
        return self._cleanup_digest(paper, draft, extracted_content, notice_callback=notice_callback)

    def _cleanup_digest(self, paper: Paper, draft: PaperDigest, extracted_content: ExtractedPaperContent, *, notice_callback: Callable[[str], None] | None = None) -> PaperDigest:
        cleanup_payload = self._collect_cleanup_payload(draft)
        if not cleanup_payload:
            return draft
        context = self._compose_context(extracted_content, include=("abstract", "introduction", "method", "experiments", "conclusion", "raw_body"), max_chars=12000)
        prompt = (
            f"论文标题: {paper.title}\n摘要:\n{paper.abstract}\n\n"
            f"待清洗字段(JSON):\n{json.dumps(cleanup_payload, ensure_ascii=False, indent=2)}\n\n"
            "只返回上述同名字段组成的 JSON，不要新增字段，不要输出解释文字。\n\n"
            f"可参考正文片段:\n{context or '无稳定正文片段，可结合摘要整理。'}\n"
        )
        cleaned = self._run_digest_stage(DIGEST_CLEANUP_PROMPT, prompt, retry_context=f"论文清洗：{truncate_text(paper.title, 48)}", max_completion_tokens=1600, notice_callback=notice_callback, stage_notice=f"正在做中文清洗与分段整理：{truncate_text(paper.title, 48)}")
        merged = self._merge_cleaned_digest(draft, cleaned or {})
        remaining_payload = self._collect_cleanup_payload(merged)
        if remaining_payload:
            if notice_callback is not None:
                notice_callback(f"仍有残余英文或结构化块，继续逐字段清洗：{truncate_text(paper.title, 48)}")
            merged = self._cleanup_digest_fields(paper, merged, extracted_content, remaining_payload, notice_callback=notice_callback)
        return merged

    def _merge_cleaned_digest(self, draft: PaperDigest, cleaned: dict[str, object]) -> PaperDigest:
        return PaperDigest(
            major_topic=draft.major_topic,
            minor_topic=draft.minor_topic,
            keywords=draft.keywords,
            one_sentence_takeaway=self._normalize_rich_text(cleaned.get("one_sentence_takeaway", "")) or draft.one_sentence_takeaway,
            problem=self._normalize_rich_text(cleaned.get("problem", "")) or draft.problem,
            background=self._normalize_rich_text(cleaned.get("background", "")) or draft.background,
            method=self._normalize_rich_text(cleaned.get("method", "")) or draft.method,
            experiment_setup=self._normalize_rich_text(cleaned.get("experiment_setup", "")) or draft.experiment_setup,
            findings=self._normalize_list(cleaned.get("findings", []), fallback=draft.findings),
            limitations=self._normalize_list(cleaned.get("limitations", []), fallback=draft.limitations),
            relevance=self._normalize_rich_text(cleaned.get("relevance", "")) or draft.relevance,
            improvement_ideas=self._normalize_list(cleaned.get("improvement_ideas", []), fallback=draft.improvement_ideas),
        )

    def _cleanup_digest_fields(self, paper: Paper, draft: PaperDigest, extracted_content: ExtractedPaperContent, payload: dict[str, object], *, notice_callback: Callable[[str], None] | None = None) -> PaperDigest:
        context = self._compose_context(extracted_content, include=("abstract", "method", "experiments", "conclusion"), max_chars=7000)
        current = draft
        for field_name, value in payload.items():
            prompt = (
                f"论文标题: {paper.title}\n"
                f"待清洗字段: {field_name}\n"
                f"待清洗内容(JSON):\n{json.dumps({field_name: value}, ensure_ascii=False, indent=2)}\n\n"
                f"只返回形如 {{\"{field_name}\": ...}} 的 JSON，不要输出其他字段。\n\n"
                f"可参考正文片段:\n{context or '无稳定正文片段，可结合摘要整理。'}\n"
            )
            cleaned = self._run_digest_stage(
                DIGEST_CLEANUP_PROMPT,
                prompt,
                retry_context=f"字段清洗：{truncate_text(paper.title, 36)}:{field_name}",
                max_completion_tokens=900,
                notice_callback=notice_callback,
                stage_notice=f"正在补做字段清洗（{field_name}）：{truncate_text(paper.title, 36)}",
            )
            if cleaned and field_name in cleaned:
                current = self._merge_cleaned_digest(current, {field_name: cleaned[field_name]})
        return current

    @staticmethod
    def _normalize_intent(raw_value: str) -> str:
        return "explain_paper" if raw_value.strip().lower() == "explain_paper" else "discover_papers"

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
        return RequestPlan(intent=intent, user_goal=normalize_whitespace(user_request), search_query="" if intent == "explain_paper" else normalize_whitespace(user_request), paper_refs=paper_refs if intent == "explain_paper" else [], max_results=max_results, reuse_local=True, rationale="Fallback heuristic plan.")

    def _fallback_digest(self, paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> PaperDigest:
        content = extracted_content or ExtractedPaperContent()
        return PaperDigest(
            major_topic=self._fallback_major_topic(paper),
            minor_topic=self._fallback_minor_topic(paper),
            keywords=paper.categories[:5] or ["arXiv"],
            one_sentence_takeaway=self._fallback_takeaway(paper, content),
            problem=self._fallback_problem(paper, content),
            background=self._fallback_background(content),
            method=self._fallback_method(content),
            experiment_setup=self._fallback_experiment_setup(content),
            findings=self._fallback_findings(paper, content),
            limitations=self._fallback_limitations(content),
            relevance=self._fallback_relevance(paper, content, []),
            improvement_ideas=self._fallback_improvement_ideas(content),
        )

    @staticmethod
    def _fallback_major_topic(paper: Paper) -> str:
        return paper.primary_category.split(".", 1)[0].upper() if paper.primary_category and "." in paper.primary_category else "未分类方向"

    @staticmethod
    def _fallback_minor_topic(paper: Paper) -> str:
        return paper.primary_category or "待整理子方向"

    @staticmethod
    def _coerce_extracted_content(extracted_text: ExtractedPaperContent | str) -> ExtractedPaperContent:
        if isinstance(extracted_text, ExtractedPaperContent):
            return extracted_text
        raw_text = normalize_whitespace(str(extracted_text or ""))
        return ExtractedPaperContent(raw_body=raw_text) if raw_text else ExtractedPaperContent()

    def _run_digest_stage(self, system_prompt: str, user_prompt: str, *, retry_context: str, max_completion_tokens: int, notice_callback: Callable[[str], None] | None, stage_notice: str) -> dict | None:
        if notice_callback is not None:
            notice_callback(stage_notice)
        try:
            raw = self.client.chat_text([{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], temperature=0.2, max_completion_tokens=max_completion_tokens, retry_context=retry_context, notice_callback=notice_callback)
            return extract_json_object(raw)
        except MiniMaxError:
            if notice_callback is not None:
                notice_callback(f"{retry_context} 连续失败，当前块将使用回退结果。")
            return None
        except (ValueError, TypeError):
            if notice_callback is not None:
                notice_callback(f"{retry_context} 响应解析失败，当前块将使用回退结果。")
            return None

    @staticmethod
    def _build_digest_prompt(user_request: str, paper: Paper, related_context: str, *, section_context: str, stage_label: str, taxonomy_context: str = "") -> str:
        taxonomy_block = f"\n主题体系指引:\n{taxonomy_context}\n" if taxonomy_context else "\n"
        return (
            f"当前任务阶段: {stage_label}\n\n"
            f"用户请求:\n{user_request.strip()}\n\n"
            f"论文标题: {paper.title}\n"
            f"arXiv ID: {paper.arxiv_id}\n"
            f"作者: {', '.join(paper.authors)}\n"
            f"分类: {paper.primary_category} | {', '.join(paper.categories)}\n"
            f"摘要:\n{paper.abstract}\n\n"
            f"精选正文内容:\n{section_context or '无稳定正文片段，可参考摘要。'}\n\n"
            f"本地相关论文:\n{truncate_text(related_context, 3000)}\n"
            f"{taxonomy_block}"
        )

    @staticmethod
    def _compose_context(extracted_content: ExtractedPaperContent, *, include: tuple[str, ...], max_chars: int) -> str:
        blocks: list[str] = []
        for field_name in include:
            body = Planner._normalize_rich_text(getattr(extracted_content, field_name, ""))
            if body:
                blocks.append(f"[{field_name.replace('_', ' ').title()}]\n{body}")
        if "method" in include and extracted_content.equations:
            blocks.append("[Recognizable Equations]\n" + "\n".join(f"- {item}" for item in extracted_content.equations))
        return truncate_text("\n\n".join(blocks), max_chars) if blocks else ""

    @staticmethod
    def _normalize_list(value: object, fallback: list[str]) -> list[str]:
        if isinstance(value, list):
            normalized = [normalize_whitespace(str(item)) for item in value if normalize_whitespace(str(item))]
            if normalized:
                return normalized[:8]
        return fallback

    @staticmethod
    def _normalize_rich_text(value: object) -> str:
        if isinstance(value, dict):
            blocks: list[str] = []
            for key, item in value.items():
                label = normalize_whitespace(str(key))
                if not label:
                    continue
                if isinstance(item, list):
                    items = [normalize_whitespace(str(entry)) for entry in item if normalize_whitespace(str(entry))]
                    if items:
                        blocks.append(f"**{label}**：\n" + "\n".join(f"- {entry}" for entry in items))
                    continue
                rendered = Planner._normalize_rich_text(item)
                if rendered:
                    separator = "：\n" if "\n" in rendered else "："
                    blocks.append(f"**{label}**{separator}{rendered}")
            return "\n\n".join(blocks).strip()
        if isinstance(value, list):
            items = [normalize_whitespace(str(item)) for item in value if normalize_whitespace(str(item))]
            return "\n".join(f"- {item}" for item in items).strip()
        raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        if not raw.strip():
            return ""
        lines = [normalize_whitespace(line) if line.strip() else "" for line in raw.split("\n")]
        collapsed: list[str] = []
        blank_run = 0
        for line in lines:
            if not line:
                blank_run += 1
                if blank_run <= 2 and collapsed:
                    collapsed.append("")
                continue
            blank_run = 0
            collapsed.append(line)
        while collapsed and not collapsed[-1]:
            collapsed.pop()
        return "\n".join(collapsed).strip()

    @staticmethod
    def _digest_needs_cleanup(digest: PaperDigest) -> bool:
        text_fields = [digest.one_sentence_takeaway, digest.problem, digest.background, digest.method, digest.experiment_setup, digest.relevance]
        list_fields = [*digest.findings, *digest.limitations, *digest.improvement_ideas]
        return any(Planner._field_needs_cleanup(text) for text in [*text_fields, *list_fields] if text)

    @staticmethod
    def _collect_cleanup_payload(digest: PaperDigest) -> dict[str, object]:
        payload: dict[str, object] = {}
        for field_name in ("one_sentence_takeaway", "problem", "background", "method", "experiment_setup", "relevance"):
            value = getattr(digest, field_name)
            if Planner._field_needs_cleanup(value):
                payload[field_name] = value
        for field_name in ("findings", "limitations", "improvement_ideas"):
            value = getattr(digest, field_name)
            if any(Planner._field_needs_cleanup(item) for item in value):
                payload[field_name] = value
        return payload

    @staticmethod
    def _field_needs_cleanup(value: str) -> bool:
        return (
            Planner._looks_english_dominant(value)
            or Planner._looks_dense_block(value)
            or Planner._looks_dumped_mapping(value)
        )

    @staticmethod
    def _looks_english_dominant(text: str) -> bool:
        normalized = normalize_whitespace(text)
        if not normalized:
            return False
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", normalized))
        english_words = len(re.findall(r"[A-Za-z]{3,}", normalized))
        return english_words >= 10 and english_words * 2 > max(cjk_count, 1)

    @staticmethod
    def _looks_dense_block(text: str) -> bool:
        raw = str(text or "")
        normalized = normalize_whitespace(raw)
        markers = ("1.", "2.", "3.", "4.", "- **", "$$", "包括：", "如下：", "steps", "phase")
        return bool(normalized) and "\n" not in raw and len(normalized) >= 220 and any(marker in raw or marker in normalized for marker in markers)

    @staticmethod
    def _looks_dumped_mapping(text: str) -> bool:
        normalized = normalize_whitespace(str(text or ""))
        return normalized.startswith("{") and normalized.endswith("}") and ":" in normalized

    @staticmethod
    def _fallback_takeaway(paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> str:
        content = extracted_content or ExtractedPaperContent()
        sentences = Planner._best_available_sentences(content, paper.abstract)
        return sentences[0] if sentences else paper.title

    @staticmethod
    def _fallback_problem(paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> str:
        content = extracted_content or ExtractedPaperContent()
        sentences = Planner._best_available_sentences(content, paper.abstract)
        if len(sentences) >= 2:
            return "\n\n".join(sentences[:2])
        return sentences[0] if sentences else ""

    @staticmethod
    def _fallback_background(extracted_content: ExtractedPaperContent) -> str:
        sentences = Planner._abstract_sentences(extracted_content.introduction or extracted_content.conclusion)
        if len(sentences) >= 2:
            return "\n\n".join(sentences[:2])
        return sentences[0] if sentences else ""

    @staticmethod
    def _fallback_method(extracted_content: ExtractedPaperContent) -> str:
        sentences = Planner._abstract_sentences(extracted_content.method)
        if not sentences:
            return ""
        body = "\n\n".join(sentences[:4])
        if extracted_content.equations:
            body += "\n\n可识别的公式线索：\n" + "\n".join(f"- {item}" for item in extracted_content.equations[:3])
        return body

    @staticmethod
    def _fallback_experiment_setup(extracted_content: ExtractedPaperContent) -> str:
        sentences = Planner._abstract_sentences(extracted_content.experiments)
        return "\n\n".join(sentences[:3]) if sentences else ""

    @staticmethod
    def _fallback_findings(paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> list[str]:
        content = extracted_content or ExtractedPaperContent()
        experiment_sentences = Planner._abstract_sentences(content.experiments)
        if experiment_sentences:
            return experiment_sentences[:4]
        abstract_sentences = Planner._abstract_sentences(paper.abstract)
        return abstract_sentences[:2] if abstract_sentences else []

    @staticmethod
    def _fallback_limitations(extracted_content: ExtractedPaperContent) -> list[str]:
        conclusion_sentences = Planner._abstract_sentences(extracted_content.conclusion)
        return [sentence for sentence in conclusion_sentences if any(marker in sentence.lower() for marker in ("limitation", "future work", "challenge", "constraint", "不足", "局限"))][:3]

    @staticmethod
    def _fallback_relevance(paper: Paper, extracted_content: ExtractedPaperContent, related_papers: list[StoredPaper]) -> str:
        if related_papers:
            return "可与本地已有相关论文联动阅读，用于补足该主题的理解。"
        if extracted_content.method or extracted_content.experiments:
            return "该论文提供了较完整的正文信息，适合作为该方向的重点阅读材料。"
        return "该论文可作为当前主题的候选参考论文。" if paper.abstract else ""

    @staticmethod
    def _fallback_improvement_ideas(extracted_content: ExtractedPaperContent) -> list[str]:
        conclusion_sentences = Planner._abstract_sentences(extracted_content.conclusion)
        return [sentence for sentence in conclusion_sentences if any(marker in sentence.lower() for marker in ("future work", "improve", "extend", "future", "优化", "扩展", "未来"))][:3]

    @staticmethod
    def _abstract_sentences(text: str) -> list[str]:
        normalized = normalize_whitespace(text)
        if not normalized:
            return []
        sentences = [part.strip() for part in re.split(r'(?<=[。！？!?；;])\s+|(?<=[.])\s+(?=[A-Z0-9"“‘\'])', normalized) if part.strip()]
        return sentences or [normalized]

    @staticmethod
    def _best_available_sentences(extracted_content: ExtractedPaperContent, abstract: str) -> list[str]:
        for candidate in (extracted_content.abstract, extracted_content.introduction, extracted_content.conclusion, extracted_content.raw_body, abstract):
            sentences = Planner._abstract_sentences(candidate)
            if sentences:
                return sentences
        return []

    @staticmethod
    def _related_context(records: list[StoredPaper]) -> str:
        if not records:
            return "暂无。"
        return "\n".join(f"- {record.paper.title} | {record.digest.major_topic}/{record.digest.minor_topic} | {record.digest.one_sentence_takeaway} | {record.digest.problem or record.digest.relevance}" for record in records[:5])

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
            unique_refs: list[str] = []
            seen: set[str] = set()
            for ref in refs:
                if ref not in seen:
                    seen.add(ref)
                    unique_refs.append(ref)
            return unique_refs
        return extract_paper_reference_texts(user_request) if normalized_intent == "explain_paper" else []

    def _resolve_request_intent(self, raw_intent: str, *, user_request: str, paper_refs: list[str]) -> str:
        return "explain_paper" if self._should_lookup_specific_papers(user_request, paper_refs) else self._normalize_intent(raw_intent)

    @staticmethod
    def _should_lookup_specific_papers(user_request: str, paper_refs: list[str]) -> bool:
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
        return False
