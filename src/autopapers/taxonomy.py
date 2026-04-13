from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from autopapers.models import Paper, PaperDigest, StoredPaper
from autopapers.utils import normalize_title_key, normalize_whitespace, title_similarity


class TopicTaxonomy:
    MAJOR_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "测试时计算扩展",
            (
                "test-time scaling",
                "test time scaling",
                "test-time compute",
                "test time compute",
                "inference scaling",
                "sleep-time compute",
                "best-of",
                "best of n",
                "pass@k",
                "pass@$k$",
                "mode-conditioning",
                "speculative decoding",
                "asynchronous",
                "verifier",
                "verification design",
                "测试时计算",
                "测试时扩展",
                "推理预算",
                "推理加速",
                "推测解码",
                "验证器",
                "候选融合",
                "语言代理",
            ),
        ),
        (
            "LLM不确定性与校准",
            (
                "uncertainty",
                "confidence calibration",
                "calibration",
                "entropy",
                "i don't know",
                "knowledge-weighted",
                "halluc",
                "不确定性",
                "校准",
                "置信度",
                "熵",
                "幻觉",
                "拒答",
                "知识感知",
            ),
        ),
        (
            "LLM评估与对齐",
            (
                "llm-as-a-judge",
                "judge bias",
                "trust assessment",
                "label effects",
                "评估偏差",
                "标签效应",
                "信任评估",
                "judge",
            ),
        ),
        (
            "基础模型架构",
            (
                "attention is all you need",
                "transformer",
                "self-attention",
                "attention mechanism",
                "注意力机制",
                "transformer架构",
            ),
        ),
        (
            "医疗NLP",
            (
                "clinical",
                "ehr",
                "health record",
                "clinical note",
                "substance use disorder",
                "医疗",
                "临床",
                "病历",
                "电子健康",
            ),
        ),
        (
            "序列决策与Bandit",
            (
                "bandit",
                "contextual multi-armed bandit",
                "multi-armed bandit",
                "ucb",
                "上下文多臂老虎机",
                "多臂老虎机",
                "序列决策",
            ),
        ),
    )

    MINOR_RULES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
        "测试时计算扩展": (
            ("综述与设计分类", ("survey", "taxonomy", "overview", "综述", "分类", "design")),
            ("代码生成与验证", ("code generation", "代码生成")),
            ("预计算与离线推理", ("sleep-time compute", "offline", "pre-comput", "预计算", "离线推理")),
            ("测试时学习与发现", ("discover at test time", "test-time discover", "科学发现", "发现")),
            ("推理加速", ("speculative decoding", "asynchronous", "acceleration", "speeding up", "异步", "推测解码", "加速")),
            ("语言代理与工具使用", ("language agent", "language agents", "llm agent", "llm agents", "代理")),
            ("推理预算与策略优化", ("bandit", "budget", "allocation", "optimal", "预算", "分配", "策略")),
            ("候选生成与结果聚合", ("best-of", "best of n", "pass@k", "pass@$k$", "majority", "ensemble", "fusion", "mode-conditioning", "候选", "多数投票", "集成")),
            ("验证器与判断器", ("verifier", "judge", "validation", "reroll", "验证器", "judge")),
        ),
        "LLM不确定性与校准": (
            ("人类对齐不确定性", ("human-aligned", "human aligned", "人类对齐")),
            ("知识校准与拒答能力", ("i don't know", "knowledge-weighted", "knowledge", "拒答", "知识")),
            ("置信度校准分析", ("confidence calibration", "calibration", "n-gram", "置信度校准", "校准")),
            ("不确定性估计", ("uncertainty", "entropy", "bayesian", "不确定性", "熵")),
        ),
        "LLM评估与对齐": (
            ("LLM-as-a-Judge偏差", ("label effects", "judge", "trust assessment", "标签效应", "信任评估")),
        ),
        "基础模型架构": (
            ("Transformer与注意力机制", ("transformer", "attention", "注意力")),
        ),
        "医疗NLP": (
            ("临床信息提取与验证", ("clinical", "validation", "提取", "验证", "health")),
        ),
        "序列决策与Bandit": (
            ("上下文Bandit诊断", ("bandit", "diagnostic", "上下文", "诊断", "ucb")),
        ),
    }

    def prompt_guidance(self) -> str:
        lines = [
            "归档时优先复用以下稳定主题体系，禁止造近义词、禁止中英混写、禁止使用下划线风格目录名：",
        ]
        for major_topic, minor_rules in self.MINOR_RULES.items():
            minor_topics = "、".join(minor for minor, _patterns in minor_rules)
            lines.append(f"- {major_topic}: {minor_topics}")
        lines.append("如果确实不属于上述体系，再新增主题，但仍应保持中文、宽口径、稳定命名。")
        return "\n".join(lines)

    def canonicalize_digest(
        self,
        paper: Paper,
        digest: PaperDigest,
        existing_records: Iterable[StoredPaper] | None = None,
    ) -> PaperDigest:
        records = list(existing_records or [])
        existing_majors = self._existing_major_topics(records)
        text_blob = self._build_text_blob(paper, digest)
        major_topic = self._canonicalize_major_topic(
            digest.major_topic,
            text_blob=text_blob,
            existing_majors=existing_majors,
            paper=paper,
        )
        existing_minors = self._existing_minor_topics(records, major_topic)
        minor_topic = self._canonicalize_minor_topic(
            major_topic,
            digest.minor_topic,
            text_blob=text_blob,
            existing_minors=existing_minors,
            paper=paper,
        )

        payload = asdict(digest)
        payload["major_topic"] = major_topic
        payload["minor_topic"] = minor_topic
        return PaperDigest(**payload)

    def _canonicalize_major_topic(
        self,
        raw_major_topic: str,
        *,
        text_blob: str,
        existing_majors: list[str],
        paper: Paper,
    ) -> str:
        normalized_major = self._clean_label(raw_major_topic)
        scored_candidates = [
            (self._score_patterns(text_blob, patterns, normalized_major), canonical)
            for canonical, patterns in self.MAJOR_RULES
        ]
        best_score, best_major = max(scored_candidates, key=lambda item: item[0], default=(0, ""))
        if best_score > 0:
            return best_major

        reused_major = self._closest_existing_topic(normalized_major, existing_majors)
        if reused_major:
            return reused_major

        if normalized_major and normalized_major not in {"CS", "cs.CL", "cs.AI", "cs.LG"}:
            return normalized_major

        fallback_text = self._build_text_blob(
            paper,
            PaperDigest(
                major_topic="",
                minor_topic="",
                keywords=[],
                one_sentence_takeaway="",
                background="",
                problem="",
                method="",
                experiment_setup="",
                findings=[],
                limitations=[],
                relevance="",
                improvement_ideas=[],
            ),
        )
        best_score, best_major = max(
            ((self._score_patterns(fallback_text, patterns, ""), canonical) for canonical, patterns in self.MAJOR_RULES),
            key=lambda item: item[0],
            default=(0, ""),
        )
        if best_score > 0:
            return best_major
        return normalized_major or "未分类方向"

    def _canonicalize_minor_topic(
        self,
        major_topic: str,
        raw_minor_topic: str,
        *,
        text_blob: str,
        existing_minors: list[str],
        paper: Paper,
    ) -> str:
        normalized_minor = self._clean_label(raw_minor_topic)
        title_key = normalize_title_key(paper.title)
        if major_topic == "测试时计算扩展" and any(marker in title_key for marker in ("survey", "taxonomy", "overview", "综述")):
            return "综述与设计分类"
        if major_topic == "LLM不确定性与校准" and any(marker in title_key for marker in ("human aligned", "human aligned large language model uncertainty", "人类对齐")):
            return "人类对齐不确定性"
        if major_topic == "LLM不确定性与校准" and any(marker in title_key for marker in ("confidence calibration", "置信度校准")):
            return "置信度校准分析"
        minor_rules = self.MINOR_RULES.get(major_topic, ())
        if minor_rules:
            scored_candidates = [
                (self._score_patterns(text_blob, patterns, normalized_minor), canonical)
                for canonical, patterns in minor_rules
            ]
            best_score, best_minor = max(scored_candidates, key=lambda item: item[0], default=(0, ""))
            if best_score > 0:
                return best_minor

        reused_minor = self._closest_existing_topic(normalized_minor, existing_minors)
        if reused_minor:
            return reused_minor

        if normalized_minor and normalized_minor not in {"cs.CL", "cs.AI", "cs.LG"}:
            return normalized_minor

        if major_topic == "基础模型架构":
            return "Transformer与注意力机制"
        if major_topic == "LLM不确定性与校准":
            return "不确定性估计"
        if major_topic == "LLM评估与对齐":
            return "LLM-as-a-Judge偏差"
        if major_topic == "医疗NLP":
            return "临床信息提取与验证"
        if major_topic == "序列决策与Bandit":
            return "上下文Bandit诊断"
        if major_topic == "测试时计算扩展":
            if "agent" in title_key:
                return "语言代理与工具使用"
            return "通用方法与实证"
        return normalized_minor or paper.primary_category or "待整理子方向"

    @staticmethod
    def _clean_label(label: str) -> str:
        normalized = normalize_whitespace(str(label or ""))
        normalized = normalized.replace("_", " ")
        normalized = normalized.replace(" / ", "/")
        normalized = normalized.replace("/", " / ")
        normalized = normalize_whitespace(normalized)
        return normalized.strip(" -")

    @staticmethod
    def _score_patterns(text_blob: str, patterns: Iterable[str], raw_label: str) -> int:
        haystack = f"{text_blob} {normalize_whitespace(raw_label).casefold()}".strip()
        score = 0
        for pattern in patterns:
            needle = pattern.casefold()
            if needle in haystack:
                score += max(1, len(needle.split()))
        return score

    @staticmethod
    def _build_text_blob(paper: Paper, digest: PaperDigest) -> str:
        parts = [
            paper.title,
            paper.abstract,
            paper.primary_category,
            " ".join(paper.categories),
            digest.major_topic,
            digest.minor_topic,
            " ".join(digest.keywords),
            digest.problem,
            digest.method,
            digest.relevance,
            " ".join(digest.findings),
        ]
        return normalize_whitespace(" ".join(part for part in parts if part)).casefold()

    @staticmethod
    def _closest_existing_topic(raw_label: str, existing_topics: list[str]) -> str | None:
        if not raw_label or not existing_topics:
            return None
        best_match = ""
        best_score = 0.0
        for candidate in existing_topics:
            score = title_similarity(raw_label, candidate)
            if score > best_score:
                best_score = score
                best_match = candidate
        if best_score >= 0.84:
            return best_match
        return None

    @staticmethod
    def _existing_major_topics(records: Iterable[StoredPaper]) -> list[str]:
        seen: set[str] = set()
        majors: list[str] = []
        for record in records:
            major_topic = normalize_whitespace(record.digest.major_topic)
            if not major_topic or major_topic in seen:
                continue
            seen.add(major_topic)
            majors.append(major_topic)
        return majors

    @staticmethod
    def _existing_minor_topics(records: Iterable[StoredPaper], major_topic: str) -> list[str]:
        seen: set[str] = set()
        minors: list[str] = []
        for record in records:
            if normalize_whitespace(record.digest.major_topic) != major_topic:
                continue
            minor_topic = normalize_whitespace(record.digest.minor_topic)
            if not minor_topic or minor_topic in seen:
                continue
            seen.add(minor_topic)
            minors.append(minor_topic)
        return minors
