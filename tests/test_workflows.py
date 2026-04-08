from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from autopapers.library import PaperLibrary
from autopapers.models import Paper, PaperDigest, RequestPlan, RunResult
from autopapers.retrieval import SearchSpec
from autopapers.workflows import AutoPapersAgent


def make_paper(identifier: str, title: str) -> Paper:
    return Paper(
        arxiv_id=identifier,
        versioned_id=f"{identifier}v1",
        title=title,
        abstract="test abstract",
        authors=["Alice"],
        published="2026-01-01T00:00:00Z",
        updated="2026-01-02T00:00:00Z",
        entry_id=f"http://arxiv.org/abs/{identifier}v1",
        pdf_url=f"http://arxiv.org/pdf/{identifier}v1",
        primary_category="cs.CL",
        categories=["cs.CL"],
    )


def make_digest() -> PaperDigest:
    return PaperDigest(
        major_topic="CS",
        minor_topic="cs.CL",
        keywords=["agents", "verification"],
        one_sentence_takeaway="A concise takeaway.",
        background="Background",
        problem="Problem",
        method="Method",
        findings=["Finding"],
        limitations=["Limitation"],
        relevance="Relevant",
    )


class FakeArxivClient:
    def __init__(self, results_by_query: dict[str, list[Paper]]) -> None:
        self.results_by_query = results_by_query
        self.calls: list[tuple[str, str, str, str]] = []
        self.resolved_references: list[str] = []
        self.downloaded_ids: list[str] = []

    def search(
        self,
        query: str,
        max_results: int = 5,
        field: str = "all",
        *,
        sort_by: str = "relevance",
        sort_order: str = "descending",
    ) -> list[Paper]:
        self.calls.append((query, field, sort_by, sort_order))
        return self.results_by_query.get(query, [])[:max_results]

    def resolve_reference(self, reference: str) -> Paper:
        self.resolved_references.append(reference)
        raise LookupError(reference)

    def download_pdf_bytes(self, paper: Paper) -> bytes:
        self.downloaded_ids.append(paper.arxiv_id)
        return b"%PDF-1.4 fake content"


class FakeDiscoverySearchPlanner:
    def __init__(self, specs: list[SearchSpec]) -> None:
        self.specs = specs

    def build_specs(self, plan: RequestPlan, user_request: str) -> list[SearchSpec]:
        return list(self.specs)


class FakePlanner:
    def __init__(self, plan: RequestPlan) -> None:
        self.plan = plan

    def plan_request(self, *args, **kwargs) -> RequestPlan:
        return self.plan

    def digest_paper(self, *args, **kwargs) -> PaperDigest:
        return make_digest()


class FakeExtractor:
    def extract(self, pdf_bytes: bytes) -> str:
        return ""


class FakeSettings:
    def __init__(self, root: Path) -> None:
        self.repo_root = root
        self.reports_root = root / "reports"


class WorkflowDiscoveryTests(unittest.TestCase):
    def test_collect_candidates_tries_relaxed_queries_until_results_found(self) -> None:
        strict_query = 'all:"large language model" AND all:uncertainty'
        relaxed_query = 'all:"language model" AND all:uncertainty'
        agent = AutoPapersAgent.__new__(AutoPapersAgent)
        agent.arxiv = FakeArxivClient(
            {
                strict_query: [],
                relaxed_query: [make_paper("2401.12345", "Reliable LLM Uncertainty")],
            }
        )
        agent.discovery_search_planner = FakeDiscoverySearchPlanner(
            [
                SearchSpec(query=strict_query, field="raw", sort_by="submittedDate"),
                SearchSpec(query=relaxed_query, field="raw", sort_by="submittedDate"),
            ]
        )
        plan = RequestPlan(
            intent="discover_papers",
            user_goal="test",
            search_query="large language model uncertainty",
            paper_refs=[],
            max_results=5,
            reuse_local=True,
            rationale="",
        )

        papers = agent._collect_candidates(plan, "帮我找一下新的大模型不确定性的论文")

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].arxiv_id, "2401.12345")
        self.assertEqual(
            agent.arxiv.calls,
            [
                (strict_query, "raw", "submittedDate", "descending"),
                (relaxed_query, "raw", "submittedDate", "descending"),
            ],
        )

    def test_collect_candidates_stops_after_enough_results(self) -> None:
        first_query = "all:uncertainty"
        second_query = "all:llm"
        agent = AutoPapersAgent.__new__(AutoPapersAgent)
        agent.arxiv = FakeArxivClient(
            {
                first_query: [
                    make_paper("2401.12345", "Paper A"),
                    make_paper("2401.12346", "Paper B"),
                ],
                second_query: [make_paper("2401.12347", "Paper C")],
            }
        )
        agent.discovery_search_planner = FakeDiscoverySearchPlanner(
            [
                SearchSpec(query=first_query, field="raw"),
                SearchSpec(query=second_query, field="raw"),
            ]
        )
        plan = RequestPlan(
            intent="discover_papers",
            user_goal="test",
            search_query="uncertainty llm",
            paper_refs=[],
            max_results=2,
            reuse_local=True,
            rationale="",
        )

        papers = agent._collect_candidates(plan, "找大模型不确定性论文")

        self.assertEqual(len(papers), 2)
        self.assertEqual(len(agent.arxiv.calls), 1)

    def test_collect_candidates_for_explain_paper_prefers_local_library_match(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            stored = library.upsert_paper(
                make_paper("2401.12345", "Trust but Verify! A Survey on Verification Design for Test-time Scaling"),
                make_digest(),
                b"%PDF-1.4 fake content",
                [],
            )
            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.library = library
            agent.arxiv = FakeArxivClient({})

            plan = RequestPlan(
                intent="explain_paper",
                user_goal="介绍论文",
                search_query="",
                paper_refs=["详细介绍下这个论文：Trust but Verify! A Survey on Verification Design for Test-time Scaling"],
                max_results=1,
                reuse_local=True,
                rationale="",
            )

            papers = agent._collect_candidates(plan, plan.paper_refs[0])

            self.assertEqual([paper.arxiv_id for paper in papers], [stored.paper.arxiv_id])
            self.assertEqual(agent.arxiv.resolved_references, [])

    def test_collect_candidates_for_multiple_explain_papers_prefers_local_library_matches(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            first = library.upsert_paper(
                make_paper("2401.12345", "Trust but Verify! A Survey on Verification Design for Test-time Scaling"),
                make_digest(),
                b"%PDF-1.4 fake content",
                [],
            )
            second = library.upsert_paper(
                make_paper("1706.03762", "Attention Is All You Need"),
                make_digest(),
                b"%PDF-1.4 fake content",
                [],
            )
            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.library = library
            agent.arxiv = FakeArxivClient({})

            plan = RequestPlan(
                intent="explain_paper",
                user_goal="对比论文",
                search_query="",
                paper_refs=[
                    "请对比这两篇论文：Trust but Verify! A Survey on Verification Design for Test-time Scaling",
                    "Attention Is All You Need",
                ],
                max_results=2,
                reuse_local=True,
                rationale="",
            )

            papers = agent._collect_candidates(plan, "对比这两篇论文")

            self.assertEqual(
                [paper.arxiv_id for paper in papers],
                [first.paper.arxiv_id, second.paper.arxiv_id],
            )
            self.assertEqual(agent.arxiv.resolved_references, [])

    def test_collect_candidates_for_explain_paper_raises_clear_error_when_unresolved(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.library = library
            agent.arxiv = FakeArxivClient({})

            plan = RequestPlan(
                intent="explain_paper",
                user_goal="介绍论文",
                search_query="",
                paper_refs=["Missing Verification Survey"],
                max_results=1,
                reuse_local=True,
                rationale="",
            )

            with self.assertRaisesRegex(LookupError, "未能解析到目标论文：Missing Verification Survey"):
                agent._collect_candidates(plan, "详细介绍 Missing Verification Survey")

            self.assertEqual(agent.arxiv.resolved_references, ["Missing Verification Survey"])

    def test_run_uses_clean_reference_for_related_local_search(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            library.upsert_paper(
                make_paper("2401.12345", "Trust but Verify! A Survey on Verification Design for Test-time Scaling"),
                make_digest(),
                b"%PDF-1.4 fake content",
                [],
            )
            queries: list[str] = []
            original_search = library.search

            def tracking_search(query: str, *, limit: int = 5, exclude_ids: set[str] | None = None):
                queries.append(query)
                return original_search(query, limit=limit, exclude_ids=exclude_ids)

            library.search = tracking_search

            plan = RequestPlan(
                intent="explain_paper",
                user_goal="介绍论文",
                search_query="",
                paper_refs=["详细介绍下这个论文：Trust but Verify! A Survey on Verification Design for Test-time Scaling"],
                max_results=1,
                reuse_local=True,
                rationale="Fallback heuristic plan.",
            )
            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.settings = FakeSettings(root)
            agent.library = library
            agent.planner = FakePlanner(plan)
            agent.arxiv = FakeArxivClient({})
            agent.discovery_search_planner = FakeDiscoverySearchPlanner([])
            agent.extractor = FakeExtractor()

            result = agent.run(plan.paper_refs[0])

            self.assertIsInstance(result, RunResult)
            self.assertEqual(queries[-1], "Trust but Verify! A Survey on Verification Design for Test-time Scaling")

    def test_run_with_multiple_paper_refs_builds_comparison_report(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            library.upsert_paper(
                make_paper("2401.12345", "Trust but Verify! A Survey on Verification Design for Test-time Scaling"),
                make_digest(),
                b"%PDF-1.4 fake content",
                [],
            )
            library.upsert_paper(
                make_paper("1706.03762", "Attention Is All You Need"),
                make_digest(),
                b"%PDF-1.4 fake content",
                [],
            )
            queries: list[str] = []
            original_search = library.search

            def tracking_search(query: str, *, limit: int = 5, exclude_ids: set[str] | None = None):
                queries.append(query)
                return original_search(query, limit=limit, exclude_ids=exclude_ids)

            library.search = tracking_search

            plan = RequestPlan(
                intent="explain_paper",
                user_goal="对比论文",
                search_query="",
                paper_refs=[
                    "Trust but Verify! A Survey on Verification Design for Test-time Scaling",
                    "Attention Is All You Need",
                ],
                max_results=2,
                reuse_local=True,
                rationale="Fallback heuristic plan.",
            )
            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.settings = FakeSettings(root)
            agent.library = library
            agent.planner = FakePlanner(plan)
            agent.arxiv = FakeArxivClient({})
            agent.discovery_search_planner = FakeDiscoverySearchPlanner([])
            agent.extractor = FakeExtractor()

            result = agent.run("请对比这两篇论文")

            self.assertEqual(
                queries[-1],
                "Trust but Verify! A Survey on Verification Design for Test-time Scaling Attention Is All You Need",
            )
            self.assertIn("## Multi-Paper Comparison", result.report_markdown)
            self.assertIn("Suggested reading order", result.report_markdown)

    def test_run_emits_stage_notices_for_progress_tracking(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            plan = RequestPlan(
                intent="discover_papers",
                user_goal="找论文",
                search_query="llm uncertainty",
                paper_refs=[],
                max_results=1,
                reuse_local=True,
                rationale="",
            )
            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.settings = FakeSettings(root)
            agent.library = library
            agent.planner = FakePlanner(plan)
            agent.arxiv = FakeArxivClient({"llm uncertainty": [make_paper("2604.09999", "Progressive Logging for Agents")]})
            agent.discovery_search_planner = FakeDiscoverySearchPlanner([SearchSpec(query="llm uncertainty", field="all")])
            agent.extractor = FakeExtractor()

            notices: list[str] = []
            result = agent.run("帮我找一篇论文", notice_callback=notices.append)

            self.assertIsInstance(result, RunResult)
            joined = "\n".join(notices)
            self.assertIn("开始任务规划", joined)
            self.assertIn("规划完成：discover_papers", joined)
            self.assertIn("开始检索 arXiv 候选论文", joined)
            self.assertIn("检索 arXiv 第 1 轮", joined)
            self.assertIn("处理论文 1/1", joined)
            self.assertIn("已下载 PDF", joined)
            self.assertIn("已写入本地库", joined)
            self.assertIn("任务完成，报告已保存", joined)
