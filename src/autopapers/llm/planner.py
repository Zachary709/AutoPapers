from __future__ import annotations

import json
import re
from typing import Callable

from autopapers.json_utils import extract_json_object
from autopapers.llm.minimax import MiniMaxClient, MiniMaxError
from autopapers.models import Paper, PaperDigest, RequestPlan, StoredPaper
from autopapers.pdf import ExtractedPaperContent
from autopapers.utils import extract_paper_reference_texts, normalize_title_key, normalize_whitespace, parse_arxiv_id, truncate_text

STRICT_JSON_OUTPUT_RULES = """你必须严格输出一个 JSON 对象，并满足以下规则：
1. 只输出 JSON，不要输出任何解释、前后缀、Markdown、标题、代码块或注释。
2. key 名必须与要求完全一致，禁止新增字段、改名、嵌套到错误层级或省略 required 字段。
3. JSON 必须可被 `json.loads` 直接解析，字符串必须使用双引号。
4. 若信息不足，字符串字段返回 `""`，列表字段返回 `[]`，布尔字段返回 `false`，整数仍返回合法整数。
5. 不要把 JSON 包在 ```json 或其他围栏里。"""

PLAN_PROMPT = (
    "你是 AutoPapers 的任务规划器。Schema 包含 "
    "intent/user_goal/search_query/paper_refs/max_results/reuse_local/rationale。"
    "若用户给的是明确论文标题或 arXiv 标识，intent 设为 explain_paper；"
    "若用户是在找某方向论文，intent 设为 discover_papers。\n\n"
    f"{STRICT_JSON_OUTPUT_RULES}"
)
DIGEST_METADATA_PROMPT = (
    "你是 AutoPapers 的论文整理器。字段为 major_topic/minor_topic/keywords。优先用中文。\n\n"
    f"{STRICT_JSON_OUTPUT_RULES}"
)
DIGEST_ABSTRACT_PROMPT = (
    "你是 AutoPapers 的摘要翻译器。字段为 abstract_zh。要求把给定英文摘要逐句忠实翻译成自然中文，不要扩写，不要总结，不要补充原文没有的信息。保留术语、模型名、数据集名。\n\n"
    f"{STRICT_JSON_OUTPUT_RULES}"
)
DIGEST_OVERVIEW_PROMPT = (
    "你是 AutoPapers 的论文讲解器，负责先把论文讲明白。字段为 one_sentence_takeaway/problem/background/relevance。全部用中文。\n\n"
    f"{STRICT_JSON_OUTPUT_RULES}"
)
DIGEST_METHOD_PROMPT = (
    "你是 AutoPapers 的方法解析器。字段为 method。请用中文解释方法；若有多步流程请分段或分点；若有公式请保留 $$...$$。\n\n"
    f"{STRICT_JSON_OUTPUT_RULES}"
)
DIGEST_EXPERIMENT_PROMPT = (
    "你是 AutoPapers 的实验分析器。字段为 experiment_setup/findings/limitations/improvement_ideas。优先用中文，实验设置可分段。\n\n"
    f"{STRICT_JSON_OUTPUT_RULES}"
)
DIGEST_CLEANUP_PROMPT = (
    "你是 AutoPapers 的中文清洗器。字段为 one_sentence_takeaway/problem/background/method/experiment_setup/findings/limitations/relevance/improvement_ideas。"
    "把英文叙述整理成自然中文，保留术语、模型名、数据集名和 LaTeX 公式；不要新增信息，不要改动事实。后续会有独立步骤统一格式，因此这里只做必要的中文清洗。\n\n"
    f"{STRICT_JSON_OUTPUT_RULES}"
)
DIGEST_FORMAT_PROMPT = (
    "你是 AutoPapers 的最终格式规整器。字段为 abstract_zh/one_sentence_takeaway/problem/background/method/experiment_setup/findings/limitations/relevance/improvement_ideas。"
    "你的任务只有统一格式，绝不能修改内容本身。禁止新增、删除、改写任何事实、术语、模型名、数据集名、数字、年份、公式、引用、结论；禁止改变列表项数量和顺序。"
    "只允许调整换行、空行、列表样式、编号样式、公式块位置，并移除多余的 JSON/标题/代码围栏痕迹。"
    "不要把 `1.`、`2.`、`2.1` 这类层级编号当作标题前缀；如果需要小标题，直接保留标题文字本身。若无法确认是纯格式修正，就原样返回。\n\n"
    f"{STRICT_JSON_OUTPUT_RULES}"
)


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
        debug_callback: Callable[[str], None] | None = None,
    ) -> RequestPlan:
        requested_limit = max_results or self.default_max_results
        response_format = self._plan_response_format()
        prompt = (
            f"用户请求:\n{user_request.strip()}\n\n"
            f"当前本地论文库概览:\n{truncate_text(library_snapshot, 3000)}\n\n"
            f"默认返回条数: {requested_limit}\n"
            f"{self._json_user_prompt_checklist(response_format)}"
        )
        raw = ""
        try:
            raw = self.client.chat_text(
                [{"role": "system", "content": PLAN_PROMPT}, {"role": "user", "content": prompt}],
                temperature=0.1,
                max_completion_tokens=800,
                retry_context="任务规划",
                notice_callback=notice_callback,
                response_format=response_format,
            )
            data = extract_json_object(raw)
        except MiniMaxError:
            if notice_callback is not None:
                notice_callback("任务规划连续失败，已切换到本地回退策略。")
            return self._fallback_plan(user_request, requested_limit)
        except (ValueError, TypeError) as exc:
            self._emit_raw_response_debug(
                debug_callback,
                retry_context="任务规划",
                parse_error=exc,
                raw_response=raw,
            )
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

    def digest_paper(
        self,
        user_request: str,
        paper: Paper,
        extracted_text: ExtractedPaperContent | str,
        related_papers: list[StoredPaper],
        *,
        taxonomy_context: str = "",
        notice_callback: Callable[[str], None] | None = None,
        debug_callback: Callable[[str], None] | None = None,
    ) -> PaperDigest:
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
        abstract_translation = self._run_digest_stage(
            DIGEST_ABSTRACT_PROMPT,
            self._build_abstract_translation_prompt(paper),
            retry_context=f"摘要翻译：{truncate_text(paper.title, 48)}",
            max_completion_tokens=1000,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
            stage_notice=f"正在翻译原始摘要：{truncate_text(paper.title, 48)}",
            response_format=self._abstract_translation_response_format(),
        )
        metadata = self._run_digest_stage(DIGEST_METADATA_PROMPT, self._build_digest_prompt(user_request, paper, related_context, section_context=metadata_context, stage_label="归档主题与关键词", taxonomy_context=taxonomy_context), retry_context=f"论文归档：{truncate_text(paper.title, 48)}", max_completion_tokens=600, notice_callback=notice_callback, debug_callback=debug_callback, stage_notice=f"正在归纳主题与关键词：{truncate_text(paper.title, 48)}", response_format=self._metadata_response_format())
        overview = self._run_digest_stage(DIGEST_OVERVIEW_PROMPT, self._build_digest_prompt(user_request, paper, related_context, section_context=overview_context, stage_label="论文概述、直觉与价值"), retry_context=f"论文概述：{truncate_text(paper.title, 48)}", max_completion_tokens=1000, notice_callback=notice_callback, debug_callback=debug_callback, stage_notice=f"正在生成论文概述：{truncate_text(paper.title, 48)}", response_format=self._overview_response_format())
        method = self._run_digest_stage(DIGEST_METHOD_PROMPT, self._build_digest_prompt(user_request, paper, related_context, section_context=method_context, stage_label="方法与公式"), retry_context=f"论文方法：{truncate_text(paper.title, 48)}", max_completion_tokens=1400, notice_callback=notice_callback, debug_callback=debug_callback, stage_notice=f"正在解析方法与公式：{truncate_text(paper.title, 48)}", response_format=self._method_response_format())
        experiments = self._run_digest_stage(DIGEST_EXPERIMENT_PROMPT, self._build_digest_prompt(user_request, paper, related_context, section_context=experiment_context, stage_label="实验、局限与改进方向"), retry_context=f"论文实验：{truncate_text(paper.title, 48)}", max_completion_tokens=1200, notice_callback=notice_callback, debug_callback=debug_callback, stage_notice=f"正在整理实验与局限：{truncate_text(paper.title, 48)}", response_format=self._experiment_response_format())

        draft = PaperDigest(
            major_topic=normalize_whitespace(str((metadata or {}).get("major_topic", ""))) or self._fallback_major_topic(paper),
            minor_topic=normalize_whitespace(str((metadata or {}).get("minor_topic", ""))) or self._fallback_minor_topic(paper),
            keywords=self._normalize_list((metadata or {}).get("keywords", []), fallback=paper.categories[:5] or ["arXiv"]),
            abstract_zh=self._normalize_rich_text((abstract_translation or {}).get("abstract_zh", "")) or self._fallback_abstract_zh(paper),
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
        cleaned = self._cleanup_digest(paper, draft, extracted_content, notice_callback=notice_callback, debug_callback=debug_callback)
        return self._tighten_digest_format(paper, cleaned, notice_callback=notice_callback, debug_callback=debug_callback)

    def tighten_digest_format_only(
        self,
        paper: Paper,
        digest: PaperDigest,
        *,
        notice_callback: Callable[[str], None] | None = None,
        debug_callback: Callable[[str], None] | None = None,
    ) -> PaperDigest:
        return self._tighten_digest_format(paper, digest, notice_callback=notice_callback, debug_callback=debug_callback)

    def _cleanup_digest(
        self,
        paper: Paper,
        draft: PaperDigest,
        extracted_content: ExtractedPaperContent,
        *,
        notice_callback: Callable[[str], None] | None = None,
        debug_callback: Callable[[str], None] | None = None,
    ) -> PaperDigest:
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
        cleaned = self._run_digest_stage(DIGEST_CLEANUP_PROMPT, prompt, retry_context=f"论文清洗：{truncate_text(paper.title, 48)}", max_completion_tokens=1600, notice_callback=notice_callback, debug_callback=debug_callback, stage_notice=f"正在做中文清洗与分段整理：{truncate_text(paper.title, 48)}", response_format=self._full_digest_response_format())
        merged = self._merge_cleaned_digest(draft, cleaned or {})
        remaining_payload = self._collect_cleanup_payload(merged)
        if remaining_payload:
            if notice_callback is not None:
                notice_callback(f"仍有残余英文或结构化块，继续逐字段清洗：{truncate_text(paper.title, 48)}")
            merged = self._cleanup_digest_fields(paper, merged, extracted_content, remaining_payload, notice_callback=notice_callback, debug_callback=debug_callback)
        return merged

    def _merge_cleaned_digest(self, draft: PaperDigest, cleaned: dict[str, object]) -> PaperDigest:
        return PaperDigest(
            major_topic=draft.major_topic,
            minor_topic=draft.minor_topic,
            keywords=draft.keywords,
            abstract_zh=draft.abstract_zh,
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

    def _cleanup_digest_fields(
        self,
        paper: Paper,
        draft: PaperDigest,
        extracted_content: ExtractedPaperContent,
        payload: dict[str, object],
        *,
        notice_callback: Callable[[str], None] | None = None,
        debug_callback: Callable[[str], None] | None = None,
    ) -> PaperDigest:
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
                debug_callback=debug_callback,
                stage_notice=f"正在补做字段清洗（{field_name}）：{truncate_text(paper.title, 36)}",
                response_format=self._single_field_response_format(field_name, value),
            )
            if cleaned and field_name in cleaned:
                current = self._merge_cleaned_digest(current, {field_name: cleaned[field_name]})
        return current

    def _tighten_digest_format(
        self,
        paper: Paper,
        digest: PaperDigest,
        *,
        notice_callback: Callable[[str], None] | None = None,
        debug_callback: Callable[[str], None] | None = None,
    ) -> PaperDigest:
        payload = self._collect_formatting_payload(digest)
        if not payload:
            return digest
        prompt = (
            f"论文标题: {paper.title}\n"
            "以下字段已经分块生成并汇总完成。你只能统一格式，不能改写内容。\n\n"
            f"待规整字段(JSON):\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "只返回上述同名字段组成的 JSON，不要新增字段，不要输出解释文字。\n"
            "文本字段保持原句原词，只整理段落、空行、列表和公式位置；列表字段必须保持原顺序和原数量。\n"
            "不要输出 Markdown 标题，不要输出代码围栏。\n"
        )
        formatted = self._run_digest_stage(
            DIGEST_FORMAT_PROMPT,
            prompt,
            retry_context=f"格式规整：{truncate_text(paper.title, 48)}",
            max_completion_tokens=1800,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
            stage_notice=f"正在统一最终格式：{truncate_text(paper.title, 48)}",
            response_format=self._full_digest_response_format(),
        )
        if not formatted:
            if notice_callback is not None:
                notice_callback(f"最终格式整包规整失败，改为逐字段规整：{truncate_text(paper.title, 48)}")
            return self._tighten_digest_format_fields(paper, digest, payload, notice_callback=notice_callback, debug_callback=debug_callback)
        return self._merge_formatted_digest(digest, formatted)

    def _tighten_digest_format_fields(
        self,
        paper: Paper,
        draft: PaperDigest,
        payload: dict[str, object],
        *,
        notice_callback: Callable[[str], None] | None = None,
        debug_callback: Callable[[str], None] | None = None,
    ) -> PaperDigest:
        current = draft
        for field_name, value in payload.items():
            prompt = (
                f"论文标题: {paper.title}\n"
                f"待规整字段: {field_name}\n"
                f"待规整内容(JSON):\n{json.dumps({field_name: value}, ensure_ascii=False, indent=2)}\n\n"
                f"只返回形如 {{\"{field_name}\": ...}} 的 JSON，不要输出其他字段。\n"
                "只允许整理换行、空行、列表和公式块，不允许改写内容。\n"
            )
            formatted = self._run_digest_stage(
                DIGEST_FORMAT_PROMPT,
                prompt,
                retry_context=f"字段格式规整：{truncate_text(paper.title, 36)}:{field_name}",
                max_completion_tokens=1000,
                notice_callback=notice_callback,
                debug_callback=debug_callback,
                stage_notice=f"正在逐字段统一格式（{field_name}）：{truncate_text(paper.title, 36)}",
                response_format=self._single_field_response_format(field_name, value),
            )
            if formatted and field_name in formatted:
                current = self._merge_formatted_digest(current, {field_name: formatted[field_name]})
        return current

    def _merge_formatted_digest(self, draft: PaperDigest, formatted: dict[str, object]) -> PaperDigest:
        return PaperDigest(
            major_topic=draft.major_topic,
            minor_topic=draft.minor_topic,
            keywords=draft.keywords,
            abstract_zh=self._accept_formatted_text(draft.abstract_zh, formatted.get("abstract_zh", "")),
            one_sentence_takeaway=self._accept_formatted_text(draft.one_sentence_takeaway, formatted.get("one_sentence_takeaway", "")),
            problem=self._accept_formatted_text(draft.problem, formatted.get("problem", "")),
            background=self._accept_formatted_text(draft.background, formatted.get("background", "")),
            method=self._accept_formatted_text(draft.method, formatted.get("method", "")),
            experiment_setup=self._accept_formatted_text(draft.experiment_setup, formatted.get("experiment_setup", "")),
            findings=self._accept_formatted_list(draft.findings, formatted.get("findings", [])),
            limitations=self._accept_formatted_list(draft.limitations, formatted.get("limitations", [])),
            relevance=self._accept_formatted_text(draft.relevance, formatted.get("relevance", "")),
            improvement_ideas=self._accept_formatted_list(draft.improvement_ideas, formatted.get("improvement_ideas", [])),
        )

    @staticmethod
    def _collect_formatting_payload(digest: PaperDigest) -> dict[str, object]:
        payload: dict[str, object] = {}
        for field_name in (
            "abstract_zh",
            "one_sentence_takeaway",
            "problem",
            "background",
            "method",
            "experiment_setup",
            "relevance",
        ):
            value = getattr(digest, field_name)
            if normalize_whitespace(value):
                payload[field_name] = value
        for field_name in ("findings", "limitations", "improvement_ideas"):
            value = getattr(digest, field_name)
            if value:
                payload[field_name] = value
        return payload

    @staticmethod
    def _accept_formatted_text(original: str, candidate: object) -> str:
        if not normalize_whitespace(original):
            return ""
        formatted = Planner._normalize_rich_text(candidate)
        if not formatted:
            return original
        return formatted if Planner._is_format_preserving_update(original, formatted) else original

    @staticmethod
    def _accept_formatted_list(original: list[str], candidate: object) -> list[str]:
        if not original:
            return []
        if not isinstance(candidate, list):
            return original
        cleaned_items = [Planner._normalize_formatted_list_item(item) for item in candidate]
        if len(cleaned_items) != len(original) or any(not item for item in cleaned_items):
            return original
        if not all(Planner._is_format_preserving_update(before, after) for before, after in zip(original, cleaned_items)):
            return original
        return cleaned_items

    @staticmethod
    def _normalize_formatted_list_item(value: object) -> str:
        rendered = Planner._normalize_rich_text(value)
        if not rendered:
            return ""
        cleaned_lines = [
            re.sub(r"^\s*(?:[-*+]\s+|\d+\.\s+)", "", line)
            for line in rendered.split("\n")
        ]
        return "\n".join(cleaned_lines).strip()

    @staticmethod
    def _is_format_preserving_update(before: str, after: str) -> bool:
        return Planner._format_signature(before) == Planner._format_signature(after)

    @staticmethod
    def _format_signature(text: str) -> str:
        raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        fragments: list[str] = []
        for line in raw.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            stripped = re.sub(r"^\s{0,3}#{1,6}\s+", "", stripped)
            stripped = re.sub(r"^\s*>+\s*", "", stripped)
            stripped = re.sub(r"(?<=[。；;:：])\s*\d+\.\s+(?=(?:\*\*|[A-Za-z\u4e00-\u9fff]))", "", stripped)
            stripped = re.sub(r"^\s*(?:[-*+]\s+|\d+\.\s+)", "", stripped)
            stripped = stripped.replace("**", "").replace("__", "").replace("`", "")
            fragments.append(stripped)
        return re.sub(r"\s+", "", "".join(fragments))

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
            abstract_zh=self._fallback_abstract_zh(paper),
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

    @staticmethod
    def _json_string_schema() -> dict[str, object]:
        return {"type": "string"}

    @classmethod
    def _json_string_array_schema(cls) -> dict[str, object]:
        return {"type": "array", "items": cls._json_string_schema()}

    @classmethod
    def _json_object_response_format(cls, name: str, properties: dict[str, object]) -> dict[str, object]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties.keys()),
                    "additionalProperties": False,
                },
            },
        }

    @classmethod
    def _plan_response_format(cls) -> dict[str, object]:
        return cls._json_object_response_format(
            "request_plan",
            {
                "intent": {"type": "string", "enum": ["explain_paper", "discover_papers"]},
                "user_goal": cls._json_string_schema(),
                "search_query": cls._json_string_schema(),
                "paper_refs": cls._json_string_array_schema(),
                "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                "reuse_local": {"type": "boolean"},
                "rationale": cls._json_string_schema(),
            },
        )

    @classmethod
    def _abstract_translation_response_format(cls) -> dict[str, object]:
        return cls._json_object_response_format(
            "abstract_translation",
            {"abstract_zh": cls._json_string_schema()},
        )

    @classmethod
    def _metadata_response_format(cls) -> dict[str, object]:
        return cls._json_object_response_format(
            "paper_metadata_digest",
            {
                "major_topic": cls._json_string_schema(),
                "minor_topic": cls._json_string_schema(),
                "keywords": cls._json_string_array_schema(),
            },
        )

    @classmethod
    def _overview_response_format(cls) -> dict[str, object]:
        return cls._json_object_response_format(
            "paper_overview_digest",
            {
                "one_sentence_takeaway": cls._json_string_schema(),
                "problem": cls._json_string_schema(),
                "background": cls._json_string_schema(),
                "relevance": cls._json_string_schema(),
            },
        )

    @classmethod
    def _method_response_format(cls) -> dict[str, object]:
        return cls._json_object_response_format(
            "paper_method_digest",
            {"method": cls._json_string_schema()},
        )

    @classmethod
    def _experiment_response_format(cls) -> dict[str, object]:
        return cls._json_object_response_format(
            "paper_experiment_digest",
            {
                "experiment_setup": cls._json_string_schema(),
                "findings": cls._json_string_array_schema(),
                "limitations": cls._json_string_array_schema(),
                "improvement_ideas": cls._json_string_array_schema(),
            },
        )

    @classmethod
    def _full_digest_response_format(cls) -> dict[str, object]:
        return cls._json_object_response_format(
            "paper_full_digest",
            {
                "abstract_zh": cls._json_string_schema(),
                "one_sentence_takeaway": cls._json_string_schema(),
                "problem": cls._json_string_schema(),
                "background": cls._json_string_schema(),
                "method": cls._json_string_schema(),
                "experiment_setup": cls._json_string_schema(),
                "findings": cls._json_string_array_schema(),
                "limitations": cls._json_string_array_schema(),
                "relevance": cls._json_string_schema(),
                "improvement_ideas": cls._json_string_array_schema(),
            },
        )

    @classmethod
    def _single_field_response_format(cls, field_name: str, value: object) -> dict[str, object]:
        field_schema = cls._json_string_array_schema() if isinstance(value, list) else cls._json_string_schema()
        schema_name = re.sub(r"[^a-z0-9_]+", "_", field_name.strip().lower()).strip("_") or "field"
        return cls._json_object_response_format(f"paper_field_{schema_name}", {field_name: field_schema})

    @staticmethod
    def _json_user_prompt_checklist(response_format: dict[str, object]) -> str:
        fields = ", ".join(Planner._response_format_field_names(response_format))
        return (
            "\n输出检查清单（必须全部满足）：\n"
            "- 只返回一个 JSON 对象。\n"
            f"- 只能包含这些字段：{fields}。\n"
            "- 不要输出解释、标题、Markdown、代码块、前后缀文字。\n"
            "- 若字段没有内容，字符串返回 \"\"，列表返回 []。\n"
        )

    @staticmethod
    def _response_format_field_names(response_format: dict[str, object]) -> list[str]:
        schema = ((response_format.get("json_schema") or {}).get("schema") or {})
        properties = schema.get("properties") or {}
        if isinstance(properties, dict):
            return list(properties.keys())
        return []

    @staticmethod
    def _emit_raw_response_debug(
        debug_callback: Callable[[str], None] | None,
        *,
        retry_context: str,
        parse_error: Exception,
        raw_response: str,
    ) -> None:
        if debug_callback is None:
            return
        if not normalize_whitespace(raw_response):
            debug_callback(f"{retry_context} 原始模型返回为空，parse_error={parse_error}")
            return
        snapshot = Planner._raw_response_snapshot(raw_response)
        debug_callback(f"{retry_context} 原始模型返回（解析失败） | parse_error={parse_error} | response={snapshot}")

    @staticmethod
    def _raw_response_snapshot(raw_response: str, max_chars: int = 4000) -> str:
        normalized = raw_response.replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(normalized) <= max_chars:
            return normalized
        return normalized[: max_chars - 3].rstrip() + "..."

    def _run_digest_stage(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        retry_context: str,
        max_completion_tokens: int,
        notice_callback: Callable[[str], None] | None,
        debug_callback: Callable[[str], None] | None,
        stage_notice: str,
        response_format: dict[str, object],
    ) -> dict | None:
        if notice_callback is not None:
            notice_callback(stage_notice)
        raw = ""
        final_user_prompt = user_prompt + self._json_user_prompt_checklist(response_format)
        try:
            raw = self.client.chat_text(
                [{"role": "system", "content": system_prompt}, {"role": "user", "content": final_user_prompt}],
                temperature=0.2,
                max_completion_tokens=max_completion_tokens,
                retry_context=retry_context,
                notice_callback=notice_callback,
                response_format=response_format,
            )
            return extract_json_object(raw)
        except MiniMaxError:
            if notice_callback is not None:
                notice_callback(f"{retry_context} 连续失败，当前块将使用回退结果。")
            return None
        except (ValueError, TypeError) as exc:
            self._emit_raw_response_debug(
                debug_callback,
                retry_context=retry_context,
                parse_error=exc,
                raw_response=raw,
            )
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
            f"Paper ID: {paper.paper_id}\n"
            f"Source: {paper.source_primary}\n"
            f"arXiv ID: {paper.arxiv_id or 'N/A'}\n"
            f"Venue: {paper.venue.name or 'N/A'}\n"
            f"Citations: {paper.citation_count if paper.citation_count is not None else 'N/A'}\n"
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
    def _fallback_abstract_zh(paper: Paper) -> str:
        normalized = normalize_whitespace(paper.abstract)
        if not normalized:
            return ""
        if re.search(r"[\u4e00-\u9fff]", normalized):
            return normalized
        return ""

    @staticmethod
    def _build_abstract_translation_prompt(paper: Paper) -> str:
        return (
            f"论文标题: {paper.title}\n"
            f"原始摘要(必须忠实翻译):\n{paper.abstract}\n\n"
            "只返回一个 JSON 对象，格式为 {\"abstract_zh\": \"...\"}。"
        )

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
        if len(paper_refs) == 1 and Planner._looks_like_single_paper_title(user_request, paper_refs[0]):
            return True
        return False

    @staticmethod
    def _looks_like_single_paper_title(user_request: str, reference: str) -> bool:
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
