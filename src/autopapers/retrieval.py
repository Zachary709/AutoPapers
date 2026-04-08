from __future__ import annotations

from dataclasses import dataclass
import re

from autopapers.models import RequestPlan
from autopapers.utils import normalize_whitespace


ADVANCED_QUERY_PATTERN = re.compile(
    r"\b(?:ti|au|abs|co|jr|cat|rn|id|all):|\b(?:AND|OR|ANDNOT)\b|[()]",
    re.IGNORECASE,
)
RECENT_MARKERS = ("new", "recent", "latest", "新的", "最新", "最近", "近期")
SEARCH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "help",
    "i",
    "in",
    "is",
    "llms",
    "me",
    "of",
    "on",
    "paper",
    "papers",
    "please",
    "recent",
    "show",
    "the",
    "to",
    "with",
    "帮我",
    "帮忙",
    "找",
    "搜索",
    "检索",
    "论文",
    "新的",
    "最新",
    "最近",
    "一下",
    "关于",
}
CONCEPT_GROUPS = [
    (
        (
            "large language model",
            "large language models",
            "language model",
            "language models",
            "llm",
            "llms",
            "foundation model",
            "foundation models",
            "大模型",
            "大语言模型",
            "基础模型",
        ),
        ["large language model", "language model", "llm"],
    ),
    (
        (
            "multimodal",
            "multi modal",
            "multi-modal",
            "vision language model",
            "vision-language model",
            "vlm",
            "多模态",
            "视觉语言模型",
        ),
        ["multimodal", "vision language model", "vlm"],
    ),
    (
        (
            "uncertainty",
            "uncertain",
            "uncertainties",
            "uncertainty quantification",
            "uq",
            "不确定性",
            "不确定",
        ),
        ["uncertainty", "uncertainty quantification", "calibration", "confidence"],
    ),
    (
        (
            "calibration",
            "confidence",
            "可信度",
            "置信度",
            "校准",
        ),
        ["calibration", "confidence"],
    ),
    (
        (
            "hallucination",
            "hallucinations",
            "faithfulness",
            "factuality",
            "幻觉",
        ),
        ["hallucination", "faithfulness", "factuality"],
    ),
]


@dataclass(frozen=True, slots=True)
class SearchSpec:
    query: str
    field: str = "all"
    sort_by: str = "relevance"
    sort_order: str = "descending"
    label: str = ""


class DiscoverySearchPlanner:
    def build_specs(self, plan: RequestPlan, user_request: str) -> list[SearchSpec]:
        sort_by = "submittedDate" if self._prefer_recent(plan, user_request) else "relevance"
        seeds = [
            normalize_whitespace(plan.search_query),
            normalize_whitespace(plan.user_goal),
            normalize_whitespace(user_request),
        ]

        specs: list[SearchSpec] = []
        seen: set[tuple[str, str, str, str]] = set()

        raw_query = seeds[0]
        if raw_query:
            self._append_spec(
                specs,
                seen,
                SearchSpec(
                    query=raw_query,
                    field="raw" if self.looks_like_advanced_query(raw_query) else "all",
                    sort_by=sort_by,
                    label="planner",
                ),
            )

        concept_groups = self._extract_concept_groups(seeds)
        if len(concept_groups) >= 2:
            preferred_terms = [group[0] for group in concept_groups[:3]]
            self._append_spec(
                specs,
                seen,
                SearchSpec(
                    query=self._build_boolean_query(preferred_terms),
                    field="raw",
                    sort_by=sort_by,
                    label="concept-strict",
                ),
            )

            first_group = concept_groups[0][:3]
            second_group = concept_groups[1][:3]
            for alias in first_group[1:]:
                self._append_spec(
                    specs,
                    seen,
                    SearchSpec(
                        query=self._build_boolean_query([alias, *preferred_terms[1:]]),
                        field="raw",
                        sort_by=sort_by,
                        label="concept-first-alias",
                    ),
                )
            for alias in second_group[1:]:
                self._append_spec(
                    specs,
                    seen,
                    SearchSpec(
                        query=self._build_boolean_query([preferred_terms[0], alias, *preferred_terms[2:]]),
                        field="raw",
                        sort_by=sort_by,
                        label="concept-second-alias",
                    ),
                )

            for alias in first_group:
                self._append_spec(
                    specs,
                    seen,
                    SearchSpec(
                        query=self._build_boolean_query([alias, second_group[0]]),
                        field="raw",
                        sort_by=sort_by,
                        label="concept-pair",
                    ),
                )

        keywords = self._extract_keywords(seeds)
        if len(keywords) >= 3:
            self._append_spec(
                specs,
                seen,
                SearchSpec(
                    query=self._build_boolean_query(keywords[:3]),
                    field="raw",
                    sort_by=sort_by,
                    label="keyword-triple",
                ),
            )
        if len(keywords) >= 2:
            self._append_spec(
                specs,
                seen,
                SearchSpec(
                    query=self._build_boolean_query(keywords[:2]),
                    field="raw",
                    sort_by=sort_by,
                    label="keyword-pair",
                ),
            )
        for keyword in keywords[:2]:
            self._append_spec(
                specs,
                seen,
                SearchSpec(
                    query=self._format_term(keyword),
                    field="raw",
                    sort_by=sort_by,
                    label="keyword-single",
                ),
            )

        return specs[:10]

    @staticmethod
    def looks_like_advanced_query(query: str) -> bool:
        return bool(ADVANCED_QUERY_PATTERN.search(query))

    @staticmethod
    def _prefer_recent(plan: RequestPlan, user_request: str) -> bool:
        haystack = " ".join(
            part.lower()
            for part in (plan.user_goal, plan.search_query, plan.rationale, user_request)
            if part
        )
        return any(marker in haystack for marker in RECENT_MARKERS)

    def _extract_concept_groups(self, seeds: list[str]) -> list[list[str]]:
        combined = " ".join(seed.lower() for seed in seeds if seed)
        groups: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()
        for aliases, canonical_terms in CONCEPT_GROUPS:
            if any(alias in combined for alias in aliases):
                key = tuple(canonical_terms)
                if key not in seen:
                    seen.add(key)
                    groups.append(list(canonical_terms))
        return groups

    def _extract_keywords(self, seeds: list[str]) -> list[str]:
        combined = " ".join(seed.lower() for seed in seeds if seed)
        tokens = re.findall(r"[a-z0-9][a-z0-9\-]{1,}|[\u4e00-\u9fff]{2,}", combined)
        keywords: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            normalized = normalize_whitespace(token).strip("- ")
            if not normalized or normalized in SEARCH_STOPWORDS:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            keywords.append(normalized)
        return keywords[:6]

    @staticmethod
    def _append_spec(
        specs: list[SearchSpec],
        seen: set[tuple[str, str, str, str]],
        spec: SearchSpec,
    ) -> None:
        normalized_query = normalize_whitespace(spec.query)
        if not normalized_query:
            return
        key = (normalized_query, spec.field, spec.sort_by, spec.sort_order)
        if key in seen:
            return
        seen.add(key)
        specs.append(
            SearchSpec(
                query=normalized_query,
                field=spec.field,
                sort_by=spec.sort_by,
                sort_order=spec.sort_order,
                label=spec.label,
            )
        )

    def _build_boolean_query(self, terms: list[str]) -> str:
        formatted_terms = [self._format_term(term) for term in terms if normalize_whitespace(term)]
        if not formatted_terms:
            return ""
        return " AND ".join(formatted_terms)

    @staticmethod
    def _format_term(term: str) -> str:
        normalized = normalize_whitespace(term)
        if not normalized:
            return ""
        if ADVANCED_QUERY_PATTERN.search(normalized):
            return normalized
        escaped = normalized.replace('"', '\\"')
        if " " in normalized:
            return f'all:"{escaped}"'
        return f"all:{escaped}"
