from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Callable

from autopapers.json_utils import extract_json_object
from autopapers.llm.context_builder import (
    build_abstract_translation_prompt,
    build_digest_prompt,
    collect_cleanup_payload,
    compose_context,
    normalize_list,
    normalize_rich_text,
    related_context,
)
from autopapers.llm.fallbacks import (
    coerce_extracted_content,
    fallback_abstract_zh,
    fallback_background,
    fallback_experiment_setup,
    fallback_findings,
    fallback_improvement_ideas,
    fallback_limitations,
    fallback_major_topic,
    fallback_method,
    fallback_minor_topic,
    fallback_problem,
    fallback_relevance,
    fallback_takeaway,
)
from autopapers.llm.minimax import MiniMaxError
from autopapers.llm.prompt_specs import (
    DIGEST_ABSTRACT_PROMPT,
    DIGEST_CLEANUP_PROMPT,
    DIGEST_EXPERIMENT_PROMPT,
    DIGEST_FORMAT_PROMPT,
    DIGEST_METADATA_PROMPT,
    DIGEST_METHOD_PROMPT,
    DIGEST_OVERVIEW_PROMPT,
)
from autopapers.llm.response_formats import (
    abstract_translation_response_format,
    experiment_response_format,
    full_digest_response_format,
    json_user_prompt_checklist,
    metadata_response_format,
    method_response_format,
    overview_response_format,
    single_field_response_format,
)
from autopapers.common.text_normalization import normalize_whitespace, truncate_text
from autopapers.models import Paper, PaperDigest, StoredPaper
from autopapers.pdf import ExtractedPaperContent


@dataclass(frozen=True, slots=True)
class StageSpec:
    key: str
    system_prompt: str
    response_format: dict[str, object]
    max_completion_tokens: int
    stage_notice_template: str
    retry_context_template: str
    build_prompt: Callable[[Paper], str]


def digest_paper(
    planner,
    user_request: str,
    paper: Paper,
    extracted_text: ExtractedPaperContent | str,
    related_papers: list[StoredPaper],
    *,
    taxonomy_context: str = "",
    notice_callback: Callable[[str], None] | None = None,
    debug_callback: Callable[[str], None] | None = None,
) -> PaperDigest:
    extracted_content = coerce_extracted_content(extracted_text)
    contexts = _digest_contexts(extracted_content)
    local_related_context = related_context(related_papers)

    if notice_callback is not None:
        if extracted_content.has_substantial_text():
            notice_callback(f"正在根据 PDF 正文分阶段整理：{truncate_text(paper.title, 48)}")
            if extracted_content.references_trimmed:
                notice_callback(f"已剔除参考文献等后置内容：{truncate_text(paper.title, 48)}")
        else:
            notice_callback(f"PDF 正文提取不足，将结合摘要进行整理：{truncate_text(paper.title, 48)}")

    stage_specs = _build_primary_stage_specs(
        user_request,
        paper,
        local_related_context,
        taxonomy_context=taxonomy_context,
        contexts=contexts,
    )
    stage_results: dict[str, dict | None] = {}
    for spec in stage_specs:
        stage_results[spec.key] = run_digest_stage(
            planner,
            spec.system_prompt,
            spec.build_prompt(paper),
            retry_context=spec.retry_context_template.format(title=truncate_text(paper.title, 48)),
            max_completion_tokens=spec.max_completion_tokens,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
            stage_notice=spec.stage_notice_template.format(title=truncate_text(paper.title, 48)),
            response_format=spec.response_format,
        )

    abstract_translation = stage_results.get("abstract")
    metadata = stage_results.get("metadata")
    overview = stage_results.get("overview")
    method = stage_results.get("method")
    experiments = stage_results.get("experiments")

    draft = PaperDigest(
        major_topic=normalize_whitespace(str((metadata or {}).get("major_topic", ""))) or fallback_major_topic(paper),
        minor_topic=normalize_whitespace(str((metadata or {}).get("minor_topic", ""))) or fallback_minor_topic(paper),
        keywords=normalize_list((metadata or {}).get("keywords", []), fallback=paper.categories[:5] or ["arXiv"]),
        abstract_zh=normalize_rich_text((abstract_translation or {}).get("abstract_zh", "")) or fallback_abstract_zh(paper),
        one_sentence_takeaway=normalize_rich_text((overview or {}).get("one_sentence_takeaway", "")) or fallback_takeaway(paper, extracted_content),
        problem=normalize_rich_text((overview or {}).get("problem", "")) or fallback_problem(paper, extracted_content),
        background=normalize_rich_text((overview or {}).get("background", "")) or fallback_background(extracted_content),
        method=normalize_rich_text((method or {}).get("method", "")) or fallback_method(extracted_content),
        experiment_setup=normalize_rich_text((experiments or {}).get("experiment_setup", "")) or fallback_experiment_setup(extracted_content),
        findings=normalize_list((experiments or {}).get("findings", []), fallback=fallback_findings(paper, extracted_content)),
        limitations=normalize_list((experiments or {}).get("limitations", []), fallback=fallback_limitations(extracted_content)),
        relevance=normalize_rich_text((overview or {}).get("relevance", "")) or fallback_relevance(paper, extracted_content, related_papers),
        improvement_ideas=normalize_list((experiments or {}).get("improvement_ideas", []), fallback=fallback_improvement_ideas(extracted_content)),
    )
    cleaned = cleanup_digest(planner, paper, draft, extracted_content, notice_callback=notice_callback, debug_callback=debug_callback)
    return tighten_digest_format(planner, paper, cleaned, notice_callback=notice_callback, debug_callback=debug_callback)


def cleanup_digest(
    planner,
    paper: Paper,
    draft: PaperDigest,
    extracted_content: ExtractedPaperContent,
    *,
    notice_callback: Callable[[str], None] | None = None,
    debug_callback: Callable[[str], None] | None = None,
) -> PaperDigest:
    cleanup_payload = collect_cleanup_payload(draft)
    if not cleanup_payload:
        return draft
    context = compose_context(extracted_content, include=("abstract", "introduction", "method", "experiments", "conclusion", "raw_body"), max_chars=12000)
    prompt = (
        f"论文标题: {paper.title}\n摘要:\n{paper.abstract}\n\n"
        f"待清洗字段(JSON):\n{json.dumps(cleanup_payload, ensure_ascii=False, indent=2)}\n\n"
        "只返回上述同名字段组成的 JSON，不要新增字段，不要输出解释文字。\n\n"
        f"可参考正文片段:\n{context or '无稳定正文片段，可结合摘要整理。'}\n"
    )
    cleaned = run_digest_stage(
        planner,
        DIGEST_CLEANUP_PROMPT,
        prompt,
        retry_context=f"论文清洗：{truncate_text(paper.title, 48)}",
        max_completion_tokens=1600,
        notice_callback=notice_callback,
        debug_callback=debug_callback,
        stage_notice=f"正在做中文清洗与分段整理：{truncate_text(paper.title, 48)}",
        response_format=full_digest_response_format(),
    )
    merged = merge_cleaned_digest(draft, cleaned or {})
    remaining_payload = collect_cleanup_payload(merged)
    if remaining_payload:
        if notice_callback is not None:
            notice_callback(f"仍有残余英文或结构化块，继续逐字段清洗：{truncate_text(paper.title, 48)}")
        merged = cleanup_digest_fields(
            planner,
            paper,
            merged,
            extracted_content,
            remaining_payload,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
        )
    return merged


def cleanup_digest_fields(
    planner,
    paper: Paper,
    draft: PaperDigest,
    extracted_content: ExtractedPaperContent,
    payload: dict[str, object],
    *,
    notice_callback: Callable[[str], None] | None = None,
    debug_callback: Callable[[str], None] | None = None,
) -> PaperDigest:
    context = compose_context(extracted_content, include=("abstract", "method", "experiments", "conclusion"), max_chars=7000)
    current = draft
    for field_name, value in payload.items():
        prompt = (
            f"论文标题: {paper.title}\n"
            f"待清洗字段: {field_name}\n"
            f"待清洗内容(JSON):\n{json.dumps({field_name: value}, ensure_ascii=False, indent=2)}\n\n"
            f"只返回形如 {{\"{field_name}\": ...}} 的 JSON，不要输出其他字段。\n\n"
            f"可参考正文片段:\n{context or '无稳定正文片段，可结合摘要整理。'}\n"
        )
        cleaned = run_digest_stage(
            planner,
            DIGEST_CLEANUP_PROMPT,
            prompt,
            retry_context=f"字段清洗：{truncate_text(paper.title, 36)}:{field_name}",
            max_completion_tokens=900,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
            stage_notice=f"正在补做字段清洗（{field_name}）：{truncate_text(paper.title, 36)}",
            response_format=single_field_response_format(field_name, value),
        )
        if cleaned and field_name in cleaned:
            current = merge_cleaned_digest(current, {field_name: cleaned[field_name]})
    return current


def merge_cleaned_digest(draft: PaperDigest, cleaned: dict[str, object]) -> PaperDigest:
    return PaperDigest(
        major_topic=draft.major_topic,
        minor_topic=draft.minor_topic,
        keywords=draft.keywords,
        abstract_zh=draft.abstract_zh,
        one_sentence_takeaway=normalize_rich_text(cleaned.get("one_sentence_takeaway", "")) or draft.one_sentence_takeaway,
        problem=normalize_rich_text(cleaned.get("problem", "")) or draft.problem,
        background=normalize_rich_text(cleaned.get("background", "")) or draft.background,
        method=normalize_rich_text(cleaned.get("method", "")) or draft.method,
        experiment_setup=normalize_rich_text(cleaned.get("experiment_setup", "")) or draft.experiment_setup,
        findings=normalize_list(cleaned.get("findings", []), fallback=draft.findings),
        limitations=normalize_list(cleaned.get("limitations", []), fallback=draft.limitations),
        relevance=normalize_rich_text(cleaned.get("relevance", "")) or draft.relevance,
        improvement_ideas=normalize_list(cleaned.get("improvement_ideas", []), fallback=draft.improvement_ideas),
    )


def tighten_digest_format(
    planner,
    paper: Paper,
    digest: PaperDigest,
    *,
    notice_callback: Callable[[str], None] | None = None,
    debug_callback: Callable[[str], None] | None = None,
) -> PaperDigest:
    payload = collect_formatting_payload(digest)
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
    formatted = run_digest_stage(
        planner,
        DIGEST_FORMAT_PROMPT,
        prompt,
        retry_context=f"格式规整：{truncate_text(paper.title, 48)}",
        max_completion_tokens=1800,
        notice_callback=notice_callback,
        debug_callback=debug_callback,
        stage_notice=f"正在统一最终格式：{truncate_text(paper.title, 48)}",
        response_format=full_digest_response_format(),
    )
    if not formatted:
        if notice_callback is not None:
            notice_callback(f"最终格式整包规整失败，改为逐字段规整：{truncate_text(paper.title, 48)}")
        return tighten_digest_format_fields(
            planner,
            paper,
            digest,
            payload,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
        )
    return merge_formatted_digest(digest, formatted)


def tighten_digest_format_fields(
    planner,
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
        formatted = run_digest_stage(
            planner,
            DIGEST_FORMAT_PROMPT,
            prompt,
            retry_context=f"字段格式规整：{truncate_text(paper.title, 36)}:{field_name}",
            max_completion_tokens=1000,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
            stage_notice=f"正在逐字段统一格式（{field_name}）：{truncate_text(paper.title, 36)}",
            response_format=single_field_response_format(field_name, value),
        )
        if formatted and field_name in formatted:
            current = merge_formatted_digest(current, {field_name: formatted[field_name]})
    return current


def merge_formatted_digest(draft: PaperDigest, formatted: dict[str, object]) -> PaperDigest:
    return PaperDigest(
        major_topic=draft.major_topic,
        minor_topic=draft.minor_topic,
        keywords=draft.keywords,
        abstract_zh=accept_formatted_text(draft.abstract_zh, formatted.get("abstract_zh", "")),
        one_sentence_takeaway=accept_formatted_text(draft.one_sentence_takeaway, formatted.get("one_sentence_takeaway", "")),
        problem=accept_formatted_text(draft.problem, formatted.get("problem", "")),
        background=accept_formatted_text(draft.background, formatted.get("background", "")),
        method=accept_formatted_text(draft.method, formatted.get("method", "")),
        experiment_setup=accept_formatted_text(draft.experiment_setup, formatted.get("experiment_setup", "")),
        findings=accept_formatted_list(draft.findings, formatted.get("findings", [])),
        limitations=accept_formatted_list(draft.limitations, formatted.get("limitations", [])),
        relevance=accept_formatted_text(draft.relevance, formatted.get("relevance", "")),
        improvement_ideas=accept_formatted_list(draft.improvement_ideas, formatted.get("improvement_ideas", [])),
    )


def collect_formatting_payload(digest: PaperDigest) -> dict[str, object]:
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


def accept_formatted_text(original: str, candidate: object) -> str:
    if not normalize_whitespace(original):
        return ""
    formatted = normalize_rich_text(candidate)
    if not formatted:
        return original
    return formatted if is_format_preserving_update(original, formatted) else original


def accept_formatted_list(original: list[str], candidate: object) -> list[str]:
    if not original:
        return []
    if not isinstance(candidate, list):
        return original
    cleaned_items = [normalize_formatted_list_item(item) for item in candidate]
    if len(cleaned_items) != len(original) or any(not item for item in cleaned_items):
        return original
    if not all(is_format_preserving_update(before, after) for before, after in zip(original, cleaned_items)):
        return original
    return cleaned_items


def normalize_formatted_list_item(value: object) -> str:
    rendered = normalize_rich_text(value)
    if not rendered:
        return ""
    cleaned_lines = [
        re.sub(r"^\s*(?:[-*+]\s+|\d+\.\s+)", "", line)
        for line in rendered.split("\n")
    ]
    return "\n".join(cleaned_lines).strip()


def is_format_preserving_update(before: str, after: str) -> bool:
    return format_signature(before) == format_signature(after)


def format_signature(text: str) -> str:
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


def emit_raw_response_debug(
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
    snapshot = raw_response_snapshot(raw_response)
    debug_callback(f"{retry_context} 原始模型返回（解析失败） | parse_error={parse_error} | response={snapshot}")


def raw_response_snapshot(raw_response: str, max_chars: int = 4000) -> str:
    normalized = raw_response.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def run_digest_stage(
    planner,
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
    final_user_prompt = user_prompt + json_user_prompt_checklist(response_format)
    try:
        raw = planner.client.chat_text(
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
        emit_raw_response_debug(
            debug_callback,
            retry_context=retry_context,
            parse_error=exc,
            raw_response=raw,
        )
        if notice_callback is not None:
            notice_callback(f"{retry_context} 响应解析失败，当前块将使用回退结果。")
        return None


def _digest_contexts(extracted_content: ExtractedPaperContent) -> dict[str, str]:
    return {
        "overview": compose_context(extracted_content, include=("abstract", "introduction", "conclusion", "raw_body"), max_chars=14000),
        "method": compose_context(extracted_content, include=("method", "introduction"), max_chars=16000),
        "experiment": compose_context(extracted_content, include=("experiments", "conclusion"), max_chars=14000),
        "metadata": compose_context(extracted_content, include=("abstract", "introduction", "method", "experiments", "conclusion", "raw_body"), max_chars=18000),
    }


def _build_primary_stage_specs(
    user_request: str,
    paper: Paper,
    related_context_text: str,
    *,
    taxonomy_context: str,
    contexts: dict[str, str],
) -> list[StageSpec]:
    return [
        StageSpec(
            key="abstract",
            system_prompt=DIGEST_ABSTRACT_PROMPT,
            response_format=abstract_translation_response_format(),
            max_completion_tokens=1000,
            stage_notice_template="正在翻译原始摘要：{title}",
            retry_context_template="摘要翻译：{title}",
            build_prompt=lambda current_paper: build_abstract_translation_prompt(current_paper),
        ),
        StageSpec(
            key="metadata",
            system_prompt=DIGEST_METADATA_PROMPT,
            response_format=metadata_response_format(),
            max_completion_tokens=600,
            stage_notice_template="正在归纳主题与关键词：{title}",
            retry_context_template="论文归档：{title}",
            build_prompt=lambda current_paper: build_digest_prompt(
                user_request,
                current_paper,
                related_context_text,
                section_context=contexts["metadata"],
                stage_label="归档主题与关键词",
                taxonomy_context=taxonomy_context,
            ),
        ),
        StageSpec(
            key="overview",
            system_prompt=DIGEST_OVERVIEW_PROMPT,
            response_format=overview_response_format(),
            max_completion_tokens=1000,
            stage_notice_template="正在生成论文概述：{title}",
            retry_context_template="论文概述：{title}",
            build_prompt=lambda current_paper: build_digest_prompt(
                user_request,
                current_paper,
                related_context_text,
                section_context=contexts["overview"],
                stage_label="论文概述、直觉与价值",
            ),
        ),
        StageSpec(
            key="method",
            system_prompt=DIGEST_METHOD_PROMPT,
            response_format=method_response_format(),
            max_completion_tokens=1400,
            stage_notice_template="正在解析方法与公式：{title}",
            retry_context_template="论文方法：{title}",
            build_prompt=lambda current_paper: build_digest_prompt(
                user_request,
                current_paper,
                related_context_text,
                section_context=contexts["method"],
                stage_label="方法与公式",
            ),
        ),
        StageSpec(
            key="experiments",
            system_prompt=DIGEST_EXPERIMENT_PROMPT,
            response_format=experiment_response_format(),
            max_completion_tokens=1200,
            stage_notice_template="正在整理实验与局限：{title}",
            retry_context_template="论文实验：{title}",
            build_prompt=lambda current_paper: build_digest_prompt(
                user_request,
                current_paper,
                related_context_text,
                section_context=contexts["experiment"],
                stage_label="实验、局限与改进方向",
            ),
        ),
    ]
