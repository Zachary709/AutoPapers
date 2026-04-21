from __future__ import annotations

import re

from autopapers.common.text_normalization import normalize_whitespace, truncate_text
from autopapers.models import Paper, PaperDigest, StoredPaper
from autopapers.pdf import ExtractedPaperContent


def build_digest_prompt(
    user_request: str,
    paper: Paper,
    related_context: str,
    *,
    section_context: str,
    stage_label: str,
    taxonomy_context: str = "",
) -> str:
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


def compose_context(extracted_content: ExtractedPaperContent, *, include: tuple[str, ...], max_chars: int) -> str:
    blocks: list[str] = []
    for field_name in include:
        body = normalize_rich_text(getattr(extracted_content, field_name, ""))
        if body:
            blocks.append(f"[{field_name.replace('_', ' ').title()}]\n{body}")
    if "method" in include and extracted_content.equations:
        blocks.append("[Recognizable Equations]\n" + "\n".join(f"- {item}" for item in extracted_content.equations))
    return truncate_text("\n\n".join(blocks), max_chars) if blocks else ""


def normalize_list(value: object, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        normalized = [normalize_whitespace(str(item)) for item in value if normalize_whitespace(str(item))]
        if normalized:
            return normalized[:8]
    return fallback


def normalize_rich_text(value: object) -> str:
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
            rendered = normalize_rich_text(item)
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


def digest_needs_cleanup(digest: PaperDigest) -> bool:
    text_fields = [
        digest.one_sentence_takeaway,
        digest.problem,
        digest.background,
        digest.method,
        digest.experiment_setup,
        digest.relevance,
    ]
    list_fields = [*digest.findings, *digest.limitations, *digest.improvement_ideas]
    return any(field_needs_cleanup(text) for text in [*text_fields, *list_fields] if text)


def collect_cleanup_payload(digest: PaperDigest) -> dict[str, object]:
    payload: dict[str, object] = {}
    for field_name in ("one_sentence_takeaway", "problem", "background", "method", "experiment_setup", "relevance"):
        value = getattr(digest, field_name)
        if field_needs_cleanup(value):
            payload[field_name] = value
    for field_name in ("findings", "limitations", "improvement_ideas"):
        value = getattr(digest, field_name)
        if any(field_needs_cleanup(item) for item in value):
            payload[field_name] = value
    return payload


def field_needs_cleanup(value: str) -> bool:
    return looks_english_dominant(value) or looks_dense_block(value) or looks_dumped_mapping(value)


def looks_english_dominant(text: str) -> bool:
    normalized = normalize_whitespace(text)
    if not normalized:
        return False
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", normalized))
    english_words = len(re.findall(r"[A-Za-z]{3,}", normalized))
    return english_words >= 10 and english_words * 2 > max(cjk_count, 1)


def looks_dense_block(text: str) -> bool:
    raw = str(text or "")
    normalized = normalize_whitespace(raw)
    markers = ("1.", "2.", "3.", "4.", "- **", "$$", "包括：", "如下：", "steps", "phase")
    return bool(normalized) and "\n" not in raw and len(normalized) >= 220 and any(marker in raw or marker in normalized for marker in markers)


def looks_dumped_mapping(text: str) -> bool:
    normalized = normalize_whitespace(str(text or ""))
    return normalized.startswith("{") and normalized.endswith("}") and ":" in normalized


def build_abstract_translation_prompt(paper: Paper) -> str:
    return (
        f"论文标题: {paper.title}\n"
        f"原始摘要(必须忠实翻译):\n{paper.abstract}\n\n"
        "只返回一个 JSON 对象，格式为 {\"abstract_zh\": \"...\"}。"
    )


def abstract_sentences(text: str) -> list[str]:
    normalized = normalize_whitespace(text)
    if not normalized:
        return []
    sentences = [part.strip() for part in re.split(r'(?<=[。！？!?；;])\s+|(?<=[.])\s+(?=[A-Z0-9"“‘\'])', normalized) if part.strip()]
    return sentences or [normalized]


def best_available_sentences(extracted_content: ExtractedPaperContent, abstract: str) -> list[str]:
    for candidate in (
        extracted_content.abstract,
        extracted_content.introduction,
        extracted_content.conclusion,
        extracted_content.raw_body,
        abstract,
    ):
        sentences = abstract_sentences(candidate)
        if sentences:
            return sentences
    return []


def related_context(records: list[StoredPaper]) -> str:
    if not records:
        return "暂无。"
    return "\n".join(
        f"- {record.paper.title} | {record.digest.major_topic}/{record.digest.minor_topic} | "
        f"{record.digest.one_sentence_takeaway} | {record.digest.problem or record.digest.relevance}"
        for record in records[:5]
    )
