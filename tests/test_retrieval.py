from __future__ import annotations

import unittest

from autopapers.models import RequestPlan
from autopapers.retrieval import DiscoverySearchPlanner


class RetrievalTests(unittest.TestCase):
    def test_build_specs_expands_llm_uncertainty_queries(self) -> None:
        planner = DiscoverySearchPlanner()
        plan = RequestPlan(
            intent="discover_papers",
            user_goal="查找大语言模型不确定性的最新研究论文",
            search_query="large language model uncertainty LLM",
            paper_refs=[],
            max_results=5,
            reuse_local=True,
            rationale="test",
        )

        specs = planner.build_specs(plan, "帮我找一下新的大模型不确定性的论文")
        queries = [spec.query for spec in specs]

        self.assertIn('all:"large language model" AND all:uncertainty', queries)
        self.assertIn('all:"language model" AND all:uncertainty', queries)
        self.assertIn("all:llm AND all:uncertainty", queries)
        self.assertEqual(specs[0].sort_by, "submittedDate")

    def test_build_specs_keeps_advanced_queries_raw(self) -> None:
        planner = DiscoverySearchPlanner()
        plan = RequestPlan(
            intent="discover_papers",
            user_goal="找语言模型校准论文",
            search_query='all:"language model" AND all:calibration',
            paper_refs=[],
            max_results=5,
            reuse_local=True,
            rationale="test",
        )

        specs = planner.build_specs(plan, "找语言模型校准论文")

        self.assertEqual(specs[0].field, "raw")
        self.assertEqual(specs[0].query, 'all:"language model" AND all:calibration')
