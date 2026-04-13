from __future__ import annotations

import unittest

from autopapers.models import Paper, PaperDigest
from autopapers.taxonomy import TopicTaxonomy


def make_paper(identifier: str, title: str, abstract: str = "test abstract", primary_category: str = "cs.CL") -> Paper:
    return Paper(
        arxiv_id=identifier,
        versioned_id=f"{identifier}v1",
        title=title,
        abstract=abstract,
        authors=["Alice"],
        published="2026-01-01T00:00:00Z",
        updated="2026-01-02T00:00:00Z",
        entry_id=f"http://arxiv.org/abs/{identifier}v1",
        pdf_url=f"http://arxiv.org/pdf/{identifier}v1",
        primary_category=primary_category,
        categories=[primary_category],
    )


class TopicTaxonomyTests(unittest.TestCase):
    def test_canonicalize_digest_merges_test_time_scaling_variants(self) -> None:
        taxonomy = TopicTaxonomy()
        paper = make_paper(
            "2506.12928",
            "Scaling Test-time Compute for LLM Agents",
            abstract="We study test-time scaling methods for language agents.",
        )
        digest = PaperDigest(
            major_topic="大语言模型测试时计算",
            minor_topic="语言代理推理增强",
            keywords=["test-time scaling", "language agents"],
            problem="研究语言代理中的 test-time compute scaling。",
        )

        normalized = taxonomy.canonicalize_digest(paper, digest)

        self.assertEqual(normalized.major_topic, "测试时计算扩展")
        self.assertEqual(normalized.minor_topic, "语言代理与工具使用")

    def test_canonicalize_digest_merges_uncertainty_calibration_variants(self) -> None:
        taxonomy = TopicTaxonomy()
        paper = make_paper(
            "2604.05757",
            "Identifying Influential N-grams in Confidence Calibration via Regression Analysis",
            abstract="We study confidence calibration and uncertainty in LLM reasoning.",
        )
        digest = PaperDigest(
            major_topic="CS",
            minor_topic="cs.CL",
            keywords=["confidence calibration", "uncertainty"],
            problem="研究 LLM 置信度校准。",
        )

        normalized = taxonomy.canonicalize_digest(paper, digest)

        self.assertEqual(normalized.major_topic, "LLM不确定性与校准")
        self.assertEqual(normalized.minor_topic, "置信度校准分析")

    def test_prompt_guidance_lists_canonical_taxonomy(self) -> None:
        guidance = TopicTaxonomy().prompt_guidance()

        self.assertIn("测试时计算扩展", guidance)
        self.assertIn("LLM不确定性与校准", guidance)
        self.assertIn("禁止造近义词", guidance)

    def test_canonicalize_digest_prefers_survey_bucket_for_test_time_scaling_surveys(self) -> None:
        taxonomy = TopicTaxonomy()
        paper = make_paper(
            "2401.12345",
            "Trust but Verify! A Survey on Verification Design for Test-time Scaling",
            abstract="A survey of verification design choices for test-time scaling.",
        )
        digest = PaperDigest(
            major_topic="测试时计算扩展",
            minor_topic="验证器研究",
            keywords=["test-time scaling", "verifier", "survey"],
            problem="总结 test-time scaling 中 verifier 设计。",
        )

        normalized = taxonomy.canonicalize_digest(paper, digest)

        self.assertEqual(normalized.major_topic, "测试时计算扩展")
        self.assertEqual(normalized.minor_topic, "综述与设计分类")

    def test_canonicalize_digest_prefers_human_aligned_uncertainty_bucket(self) -> None:
        taxonomy = TopicTaxonomy()
        paper = make_paper(
            "2503.12528",
            "Investigating Human-Aligned Large Language Model Uncertainty",
            abstract="We study whether LLM uncertainty aligns with human uncertainty.",
        )
        digest = PaperDigest(
            major_topic="LLM不确定性与校准",
            minor_topic="不确定性分析",
            keywords=["uncertainty", "human-aligned"],
            problem="研究 LLM 不确定性是否与人类一致。",
        )

        normalized = taxonomy.canonicalize_digest(paper, digest)

        self.assertEqual(normalized.major_topic, "LLM不确定性与校准")
        self.assertEqual(normalized.minor_topic, "人类对齐不确定性")