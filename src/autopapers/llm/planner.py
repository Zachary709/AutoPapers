from __future__ import annotations

from typing import Callable

from autopapers.llm.context_builder import (
    abstract_sentences,
    best_available_sentences,
    build_abstract_translation_prompt,
    build_digest_prompt,
    collect_cleanup_payload,
    compose_context,
    digest_needs_cleanup,
    field_needs_cleanup,
    looks_dense_block,
    looks_dumped_mapping,
    looks_english_dominant,
    normalize_list,
    normalize_rich_text,
    related_context,
)
from autopapers.llm.digest_pipeline import (
    accept_formatted_list,
    accept_formatted_text,
    cleanup_digest,
    collect_formatting_payload,
    digest_paper,
    emit_raw_response_debug,
    format_signature,
    is_format_preserving_update,
    merge_cleaned_digest,
    merge_formatted_digest,
    normalize_formatted_list_item,
    raw_response_snapshot,
    run_digest_stage,
    tighten_digest_format,
)
from autopapers.llm.fallbacks import (
    coerce_extracted_content,
    fallback_abstract_zh,
    fallback_background,
    fallback_digest,
    fallback_experiment_setup,
    fallback_findings,
    fallback_improvement_ideas,
    fallback_limitations,
    fallback_major_topic,
    fallback_method,
    fallback_minor_topic,
    fallback_plan,
    fallback_problem,
    fallback_relevance,
    fallback_takeaway,
    looks_like_single_paper_title,
    normalize_intent,
    normalize_paper_refs,
    resolve_request_intent,
    should_lookup_specific_papers,
)
from autopapers.llm.minimax import MiniMaxClient
from autopapers.llm.prompt_specs import (
    DIGEST_ABSTRACT_PROMPT,
    DIGEST_CLEANUP_PROMPT,
    DIGEST_EXPERIMENT_PROMPT,
    DIGEST_FORMAT_PROMPT,
    DIGEST_METADATA_PROMPT,
    DIGEST_METHOD_PROMPT,
    DIGEST_OVERVIEW_PROMPT,
    PLAN_PROMPT,
    STRICT_JSON_OUTPUT_RULES,
)
from autopapers.llm.request_planning import plan_request
from autopapers.llm.response_formats import (
    abstract_translation_response_format,
    experiment_response_format,
    full_digest_response_format,
    json_object_response_format,
    json_string_array_schema,
    json_string_schema,
    json_user_prompt_checklist,
    metadata_response_format,
    method_response_format,
    overview_response_format,
    plan_response_format,
    response_format_field_names,
    single_field_response_format,
)
from autopapers.models import Paper, PaperDigest, RequestPlan, StoredPaper
from autopapers.pdf import ExtractedPaperContent


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
        return plan_request(
            self,
            user_request,
            library_snapshot,
            max_results=max_results,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
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
        return digest_paper(
            self,
            user_request,
            paper,
            extracted_text,
            related_papers,
            taxonomy_context=taxonomy_context,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
        )

    def tighten_digest_format_only(
        self,
        paper: Paper,
        digest: PaperDigest,
        *,
        notice_callback: Callable[[str], None] | None = None,
        debug_callback: Callable[[str], None] | None = None,
    ) -> PaperDigest:
        return tighten_digest_format(self, paper, digest, notice_callback=notice_callback, debug_callback=debug_callback)

    def _cleanup_digest(
        self,
        paper: Paper,
        draft: PaperDigest,
        extracted_content: ExtractedPaperContent,
        *,
        notice_callback: Callable[[str], None] | None = None,
        debug_callback: Callable[[str], None] | None = None,
    ) -> PaperDigest:
        return cleanup_digest(
            self,
            paper,
            draft,
            extracted_content,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
        )

    def _merge_cleaned_digest(self, draft: PaperDigest, cleaned: dict[str, object]) -> PaperDigest:
        return merge_cleaned_digest(draft, cleaned)

    def _tighten_digest_format(
        self,
        paper: Paper,
        digest: PaperDigest,
        *,
        notice_callback: Callable[[str], None] | None = None,
        debug_callback: Callable[[str], None] | None = None,
    ) -> PaperDigest:
        return tighten_digest_format(
            self,
            paper,
            digest,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
        )

    def _merge_formatted_digest(self, draft: PaperDigest, formatted: dict[str, object]) -> PaperDigest:
        return merge_formatted_digest(draft, formatted)

    @staticmethod
    def _collect_formatting_payload(digest: PaperDigest) -> dict[str, object]:
        return collect_formatting_payload(digest)

    @staticmethod
    def _accept_formatted_text(original: str, candidate: object) -> str:
        return accept_formatted_text(original, candidate)

    @staticmethod
    def _accept_formatted_list(original: list[str], candidate: object) -> list[str]:
        return accept_formatted_list(original, candidate)

    @staticmethod
    def _normalize_formatted_list_item(value: object) -> str:
        return normalize_formatted_list_item(value)

    @staticmethod
    def _is_format_preserving_update(before: str, after: str) -> bool:
        return is_format_preserving_update(before, after)

    @staticmethod
    def _format_signature(text: str) -> str:
        return format_signature(text)

    @staticmethod
    def _normalize_intent(raw_value: str) -> str:
        return normalize_intent(raw_value)

    def _fallback_plan(self, user_request: str, max_results: int) -> RequestPlan:
        return fallback_plan(user_request, max_results)

    def _fallback_digest(self, paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> PaperDigest:
        return fallback_digest(paper, extracted_content)

    @staticmethod
    def _fallback_major_topic(paper: Paper) -> str:
        return fallback_major_topic(paper)

    @staticmethod
    def _fallback_minor_topic(paper: Paper) -> str:
        return fallback_minor_topic(paper)

    @staticmethod
    def _coerce_extracted_content(extracted_text: ExtractedPaperContent | str) -> ExtractedPaperContent:
        return coerce_extracted_content(extracted_text)

    @staticmethod
    def _json_string_schema() -> dict[str, object]:
        return json_string_schema()

    @staticmethod
    def _json_string_array_schema() -> dict[str, object]:
        return json_string_array_schema()

    @staticmethod
    def _json_object_response_format(name: str, properties: dict[str, object]) -> dict[str, object]:
        return json_object_response_format(name, properties)

    @staticmethod
    def _plan_response_format() -> dict[str, object]:
        return plan_response_format()

    @staticmethod
    def _abstract_translation_response_format() -> dict[str, object]:
        return abstract_translation_response_format()

    @staticmethod
    def _metadata_response_format() -> dict[str, object]:
        return metadata_response_format()

    @staticmethod
    def _overview_response_format() -> dict[str, object]:
        return overview_response_format()

    @staticmethod
    def _method_response_format() -> dict[str, object]:
        return method_response_format()

    @staticmethod
    def _experiment_response_format() -> dict[str, object]:
        return experiment_response_format()

    @staticmethod
    def _full_digest_response_format() -> dict[str, object]:
        return full_digest_response_format()

    @staticmethod
    def _single_field_response_format(field_name: str, value: object) -> dict[str, object]:
        return single_field_response_format(field_name, value)

    @staticmethod
    def _json_user_prompt_checklist(response_format: dict[str, object]) -> str:
        return json_user_prompt_checklist(response_format)

    @staticmethod
    def _response_format_field_names(response_format: dict[str, object]) -> list[str]:
        return response_format_field_names(response_format)

    @staticmethod
    def _emit_raw_response_debug(
        debug_callback: Callable[[str], None] | None,
        *,
        retry_context: str,
        parse_error: Exception,
        raw_response: str,
    ) -> None:
        emit_raw_response_debug(
            debug_callback,
            retry_context=retry_context,
            parse_error=parse_error,
            raw_response=raw_response,
        )

    @staticmethod
    def _raw_response_snapshot(raw_response: str, max_chars: int = 4000) -> str:
        return raw_response_snapshot(raw_response, max_chars=max_chars)

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
        return run_digest_stage(
            self,
            system_prompt,
            user_prompt,
            retry_context=retry_context,
            max_completion_tokens=max_completion_tokens,
            notice_callback=notice_callback,
            debug_callback=debug_callback,
            stage_notice=stage_notice,
            response_format=response_format,
        )

    @staticmethod
    def _build_digest_prompt(
        user_request: str,
        paper: Paper,
        related_context_text: str,
        *,
        section_context: str,
        stage_label: str,
        taxonomy_context: str = "",
    ) -> str:
        return build_digest_prompt(
            user_request,
            paper,
            related_context_text,
            section_context=section_context,
            stage_label=stage_label,
            taxonomy_context=taxonomy_context,
        )

    @staticmethod
    def _compose_context(extracted_content: ExtractedPaperContent, *, include: tuple[str, ...], max_chars: int) -> str:
        return compose_context(extracted_content, include=include, max_chars=max_chars)

    @staticmethod
    def _normalize_list(value: object, fallback: list[str]) -> list[str]:
        return normalize_list(value, fallback)

    @staticmethod
    def _normalize_rich_text(value: object) -> str:
        return normalize_rich_text(value)

    @staticmethod
    def _digest_needs_cleanup(digest: PaperDigest) -> bool:
        return digest_needs_cleanup(digest)

    @staticmethod
    def _collect_cleanup_payload(digest: PaperDigest) -> dict[str, object]:
        return collect_cleanup_payload(digest)

    @staticmethod
    def _field_needs_cleanup(value: str) -> bool:
        return field_needs_cleanup(value)

    @staticmethod
    def _looks_english_dominant(text: str) -> bool:
        return looks_english_dominant(text)

    @staticmethod
    def _looks_dense_block(text: str) -> bool:
        return looks_dense_block(text)

    @staticmethod
    def _looks_dumped_mapping(text: str) -> bool:
        return looks_dumped_mapping(text)

    @staticmethod
    def _fallback_takeaway(paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> str:
        return fallback_takeaway(paper, extracted_content)

    @staticmethod
    def _fallback_abstract_zh(paper: Paper) -> str:
        return fallback_abstract_zh(paper)

    @staticmethod
    def _build_abstract_translation_prompt(paper: Paper) -> str:
        return build_abstract_translation_prompt(paper)

    @staticmethod
    def _fallback_problem(paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> str:
        return fallback_problem(paper, extracted_content)

    @staticmethod
    def _fallback_background(extracted_content: ExtractedPaperContent) -> str:
        return fallback_background(extracted_content)

    @staticmethod
    def _fallback_method(extracted_content: ExtractedPaperContent) -> str:
        return fallback_method(extracted_content)

    @staticmethod
    def _fallback_experiment_setup(extracted_content: ExtractedPaperContent) -> str:
        return fallback_experiment_setup(extracted_content)

    @staticmethod
    def _fallback_findings(paper: Paper, extracted_content: ExtractedPaperContent | None = None) -> list[str]:
        return fallback_findings(paper, extracted_content)

    @staticmethod
    def _fallback_limitations(extracted_content: ExtractedPaperContent) -> list[str]:
        return fallback_limitations(extracted_content)

    @staticmethod
    def _fallback_relevance(paper: Paper, extracted_content: ExtractedPaperContent, related_papers: list[StoredPaper]) -> str:
        return fallback_relevance(paper, extracted_content, related_papers)

    @staticmethod
    def _fallback_improvement_ideas(extracted_content: ExtractedPaperContent) -> list[str]:
        return fallback_improvement_ideas(extracted_content)

    @staticmethod
    def _abstract_sentences(text: str) -> list[str]:
        return abstract_sentences(text)

    @staticmethod
    def _best_available_sentences(extracted_content: ExtractedPaperContent, abstract: str) -> list[str]:
        return best_available_sentences(extracted_content, abstract)

    @staticmethod
    def _related_context(records: list[StoredPaper]) -> str:
        return related_context(records)

    @staticmethod
    def _normalize_paper_refs(raw_value: object, *, user_request: str, intent: str) -> list[str]:
        return normalize_paper_refs(raw_value, user_request=user_request, intent=intent)

    def _resolve_request_intent(self, raw_intent: str, *, user_request: str, paper_refs: list[str]) -> str:
        return resolve_request_intent(raw_intent, user_request=user_request, paper_refs=paper_refs)

    @staticmethod
    def _should_lookup_specific_papers(user_request: str, paper_refs: list[str]) -> bool:
        return should_lookup_specific_papers(user_request, paper_refs)

    @staticmethod
    def _looks_like_single_paper_title(user_request: str, reference: str) -> bool:
        return looks_like_single_paper_title(user_request, reference)
