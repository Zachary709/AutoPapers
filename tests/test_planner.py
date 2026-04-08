from __future__ import annotations

import unittest

from autopapers.llm.minimax import MiniMaxError
from autopapers.llm.planner import Planner
from autopapers.models import Paper


class FailingClient:
    def chat_text(self, *args, **kwargs) -> str:
        raise MiniMaxError("overloaded")


class SparseDigestClient:
    def chat_text(self, *args, **kwargs) -> str:
        return '{"major_topic":"CS","minor_topic":"cs.AI","keywords":["agent"]}'


class DiscoverWithExplicitRefsClient:
    def chat_text(self, *args, **kwargs) -> str:
        return (
            '{"intent":"discover_papers","user_goal":"查找8篇test-time scaling相关论文",'
            '"search_query":"test-time scaling LLM inference compute verification ensemble",'
            '"paper_refs":['
            '"ROC-n-reroll: How verifier imperfection affects test-time scaling",'
            '"CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning"'
            '],"max_results":8,"reuse_local":true,"rationale":"test"}'
        )


class PlannerResilienceTests(unittest.TestCase):
    def test_plan_request_falls_back_when_llm_fails(self) -> None:
        planner = Planner(FailingClient(), default_max_results=5)

        plan = planner.plan_request("帮我找一下新的大模型不确定性的论文", "")

        self.assertEqual(plan.intent, "discover_papers")
        self.assertEqual(plan.max_results, 5)
        self.assertIn("大模型不确定性", plan.search_query)

    def test_plan_request_extracts_clean_paper_reference_on_fallback(self) -> None:
        planner = Planner(FailingClient(), default_max_results=5)

        plan = planner.plan_request(
            "详细介绍下这个论文：Trust but Verify! A Survey on Verification Design for Test-time Scaling",
            "",
        )

        self.assertEqual(plan.intent, "explain_paper")
        self.assertEqual(
            plan.paper_refs,
            ["Trust but Verify! A Survey on Verification Design for Test-time Scaling"],
        )

    def test_plan_request_extracts_multiple_paper_references_on_fallback(self) -> None:
        planner = Planner(FailingClient(), default_max_results=5)

        plan = planner.plan_request(
            "请对比这两篇论文：Trust but Verify! A Survey on Verification Design for Test-time Scaling 和 Attention Is All You Need",
            "",
        )

        self.assertEqual(plan.intent, "explain_paper")
        self.assertEqual(
            plan.paper_refs,
            [
                "Trust but Verify! A Survey on Verification Design for Test-time Scaling",
                "Attention Is All You Need",
            ],
        )

    def test_plan_request_treats_explicit_paper_lookup_lists_as_explain_paper(self) -> None:
        planner = Planner(DiscoverWithExplicitRefsClient(), default_max_results=5)

        plan = planner.plan_request(
            "找一下这几篇论文：1. ROC-n-reroll: How verifier imperfection affects test-time scaling "
            "2. CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning",
            "",
        )

        self.assertEqual(plan.intent, "explain_paper")
        self.assertEqual(plan.search_query, "")
        self.assertEqual(
            plan.paper_refs,
            [
                "ROC-n-reroll: How verifier imperfection affects test-time scaling",
                "CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning",
            ],
        )

    def test_fallback_plan_extracts_numbered_paper_lists(self) -> None:
        planner = Planner(FailingClient(), default_max_results=5)

        plan = planner.plan_request(
            "找一下这几篇论文： 1. ROC-n-reroll: How verifier imperfection affects test-time scaling "
            "2. CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning "
            "3. ATTS: Asynchronous Test-Time Scaling via Conformal Prediction",
            "",
        )

        self.assertEqual(plan.intent, "explain_paper")
        self.assertEqual(
            plan.paper_refs,
            [
                "ROC-n-reroll: How verifier imperfection affects test-time scaling",
                "CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning",
                "ATTS: Asynchronous Test-Time Scaling via Conformal Prediction",
            ],
        )

    def test_digest_paper_falls_back_when_llm_fails(self) -> None:
        planner = Planner(FailingClient(), default_max_results=5)
        paper = Paper(
            arxiv_id="2401.12345",
            versioned_id="2401.12345v1",
            title="Test Driven Agents",
            abstract=(
                "Reliable agents benefit from explicit verification loops. "
                "The study evaluates the effect of verification on accuracy under tool failure. "
                "Results show more stable recovery after intermediate mistakes."
            ),
            authors=["Alice"],
            published="2026-01-01T00:00:00Z",
            updated="2026-01-02T00:00:00Z",
            entry_id="http://arxiv.org/abs/2401.12345v1",
            pdf_url="http://arxiv.org/pdf/2401.12345v1",
            primary_category="cs.AI",
            categories=["cs.AI"],
        )

        digest = planner.digest_paper("介绍这篇论文", paper, "", [])

        self.assertEqual(digest.major_topic, "CS")
        self.assertEqual(digest.minor_topic, "cs.AI")
        self.assertEqual(digest.one_sentence_takeaway, "Reliable agents benefit from explicit verification loops.")
        self.assertEqual(
            digest.findings,
            [
                "Reliable agents benefit from explicit verification loops.",
                "The study evaluates the effect of verification on accuracy under tool failure.",
                "Results show more stable recovery after intermediate mistakes.",
            ],
        )
        self.assertNotIn("...", digest.one_sentence_takeaway)
        self.assertFalse(any("..." in finding for finding in digest.findings))

    def test_digest_paper_uses_sentence_based_field_fallbacks_when_response_is_sparse(self) -> None:
        planner = Planner(SparseDigestClient(), default_max_results=5)
        paper = Paper(
            arxiv_id="2401.12346",
            versioned_id="2401.12346v1",
            title="Sparse Digest Recovery",
            abstract=(
                "This paper studies resilient summary generation for paper libraries. "
                "It shows that sentence-based fallbacks preserve note readability better than clipped snippets."
            ),
            authors=["Bob"],
            published="2026-01-03T00:00:00Z",
            updated="2026-01-03T00:00:00Z",
            entry_id="http://arxiv.org/abs/2401.12346v1",
            pdf_url="http://arxiv.org/pdf/2401.12346v1",
            primary_category="cs.CL",
            categories=["cs.CL"],
        )

        digest = planner.digest_paper("介绍这篇论文", paper, "", [])

        self.assertEqual(
            digest.one_sentence_takeaway,
            "This paper studies resilient summary generation for paper libraries.",
        )
        self.assertEqual(
            digest.findings,
            [
                "This paper studies resilient summary generation for paper libraries.",
                "It shows that sentence-based fallbacks preserve note readability better than clipped snippets.",
            ],
        )
        self.assertNotIn("...", digest.one_sentence_takeaway)
        self.assertFalse(any("..." in finding for finding in digest.findings))
