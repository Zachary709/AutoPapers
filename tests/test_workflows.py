from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from autopapers.library import PaperLibrary
from autopapers.models import Paper, PaperDigest, RequestPlan, RunResult, TaskCancelledError
from autopapers.pdf import ExtractedPaperContent
from autopapers.retrieval import SearchSpec
from autopapers.taxonomy import TopicTaxonomy
from autopapers.workflows import AutoPapersAgent


def make_paper(identifier: str, title: str) -> Paper:
    return Paper(
        paper_id=identifier,
        source_primary="arxiv",
        arxiv_id=identifier,
        versioned_id=f"{identifier}v1",
        title=title,
        abstract="test abstract",
        authors=["Alice"],
        published="2026-01-01T00:00:00Z",
        updated="2026-01-02T00:00:00Z",
        entry_id=f"http://arxiv.org/abs/{identifier}v1",
        entry_url=f"http://arxiv.org/abs/{identifier}v1",
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
        experiment_setup="Experiment setup",
        findings=["Finding"],
        limitations=["Limitation"],
        relevance="Relevant",
        improvement_ideas=["Improve verifier calibration."],
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


class FakeSourceClient(FakeArxivClient):
    def enrich_metadata(self, paper: Paper) -> Paper:
        return paper


class FakeMetadataClient:
    def __init__(self, updated_paper: Paper | None = None) -> None:
        self.updated_paper = updated_paper

    def enrich_metadata(self, paper: Paper) -> Paper:
        return self.updated_paper or paper


class SuccessfulResolver:
    def __init__(self, paper: Paper) -> None:
        self.paper = paper

    def resolve_reference(self, reference: str) -> Paper:
        return self.paper


class ForbiddenResolver:
    def resolve_reference(self, reference: str) -> Paper:
        raise HTTPError("https://api2.openreview.net/notes/search", 403, "Forbidden", hdrs=None, fp=None)


class FakeDiscoverySearchPlanner:
    def __init__(self, specs: list[SearchSpec]) -> None:
        self.specs = specs

    def build_specs(self, plan: RequestPlan, user_request: str) -> list[SearchSpec]:
        return list(self.specs)


class FakePlanner:
    def __init__(self, plan: RequestPlan) -> None:
        self.plan = plan
        self.last_extracted_text = None
        self.format_only_calls: list[str] = []

    def plan_request(self, *args, **kwargs) -> RequestPlan:
        return self.plan

    def digest_paper(self, *args, **kwargs) -> PaperDigest:
        if len(args) >= 3:
            self.last_extracted_text = args[2]
        return make_digest()

    def tighten_digest_format_only(self, paper: Paper, digest: PaperDigest, *, notice_callback=None) -> PaperDigest:
        self.format_only_calls.append(paper.paper_id)
        return digest


class FakeExtractor:
    def __init__(self, content: ExtractedPaperContent | None = None) -> None:
        self.content = content or ExtractedPaperContent(raw_body="Parsed PDF body")

    def extract(self, pdf_bytes: bytes) -> str:
        return self.content.raw_body

    def extract_structured(self, pdf_bytes: bytes) -> ExtractedPaperContent:
        return self.content


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
        agent.taxonomy = TopicTaxonomy()
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

    def test_save_report_replaces_stale_tmp_file_atomically(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.settings = FakeSettings(root)

            with patch("autopapers.workflows.datetime") as mock_datetime:
                mock_datetime.now.return_value.strftime.return_value = "20260421-123456"
                relative_path = agent._save_report("Atomic Report", "first version")
                report_path = root / relative_path
                tmp_path = report_path.with_name(f"{report_path.name}.tmp")
                tmp_path.write_text("partial report", encoding="utf-8")

                relative_path = agent._save_report("Atomic Report", "second version")
                report_path = root / relative_path

            self.assertEqual(report_path.read_text(encoding="utf-8"), "second version")
            self.assertFalse(tmp_path.exists())

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
        agent.taxonomy = TopicTaxonomy()
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

    def test_collect_candidates_combines_arxiv_openreview_and_scholar_fallback(self) -> None:
        query = "test-time scaling"
        agent = AutoPapersAgent.__new__(AutoPapersAgent)
        agent.arxiv = FakeArxivClient({query: [make_paper("2401.12345", "Paper A")]})
        openreview_paper = make_paper("2401.12346", "Paper B")
        openreview_paper.paper_id = "openreview:forum-b"
        openreview_paper.source_primary = "openreview"
        openreview_paper.arxiv_id = ""
        openreview_paper.versioned_id = ""
        openreview_paper.openreview_id = "note-b"
        openreview_paper.openreview_forum_id = "forum-b"
        openreview_paper.entry_url = "https://openreview.net/forum?id=forum-b"
        openreview_paper.entry_id = openreview_paper.entry_url
        openreview_paper.pdf_url = "https://openreview.net/pdf?id=forum-b"
        agent.openreview = FakeSourceClient({query: [openreview_paper]})
        scholar_paper = make_paper("2401.12347", "Paper C")
        scholar_paper.paper_id = "scholar:paper-c"
        scholar_paper.source_primary = "scholar"
        scholar_paper.arxiv_id = ""
        scholar_paper.versioned_id = ""
        scholar_paper.entry_url = "https://example.com/paper-c"
        scholar_paper.entry_id = scholar_paper.entry_url
        agent.scholar = FakeSourceClient({query: [scholar_paper]})
        agent.discovery_search_planner = FakeDiscoverySearchPlanner([SearchSpec(query=query, field="all")])
        agent.taxonomy = TopicTaxonomy()
        plan = RequestPlan(
            intent="discover_papers",
            user_goal="找论文",
            search_query=query,
            paper_refs=[],
            max_results=3,
            reuse_local=True,
            rationale="",
        )

        papers = agent._collect_candidates(plan, query)

        self.assertEqual(len(papers), 3)
        self.assertEqual([paper.paper_id for paper in papers], ["2401.12345", "openreview:forum-b", "scholar:paper-c"])

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
            agent.taxonomy = TopicTaxonomy()

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
            agent.taxonomy = TopicTaxonomy()

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
            agent.taxonomy = TopicTaxonomy()

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

    def test_collect_candidates_for_explain_paper_continues_after_openreview_403(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            expected = make_paper("2604.00001", "CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning")
            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.library = library
            agent.arxiv = FakeArxivClient({})
            agent.openreview = ForbiddenResolver()
            agent.scholar = SuccessfulResolver(expected)
            agent.taxonomy = TopicTaxonomy()

            plan = RequestPlan(
                intent="explain_paper",
                user_goal="找论文",
                search_query="",
                paper_refs=["CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning"],
                max_results=1,
                reuse_local=True,
                rationale="",
            )
            notices: list[str] = []

            papers = agent._collect_candidates(plan, plan.paper_refs[0], notice_callback=notices.append)

            self.assertEqual([paper.paper_id for paper in papers], [expected.paper_id])
            self.assertTrue(any("OpenReview 解析失败" in notice for notice in notices))

    def test_collect_candidates_requests_confirmation_for_low_similarity_match(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            mismatched = make_paper("2604.00002", "A Totally Different Reasoning Paper")
            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.library = library
            agent.arxiv = FakeArxivClient({})
            agent.scholar = SuccessfulResolver(mismatched)
            agent.taxonomy = TopicTaxonomy()

            plan = RequestPlan(
                intent="explain_paper",
                user_goal="找论文",
                search_query="",
                paper_refs=["CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning"],
                max_results=1,
                reuse_local=True,
                rationale="",
            )
            prompts: list[dict[str, object]] = []

            with self.assertRaisesRegex(TaskCancelledError, "用户拒绝保存和解析低相似度候选论文"):
                agent._collect_candidates(
                    plan,
                    plan.paper_refs[0],
                    confirmation_callback=lambda payload: prompts.append(payload) or False,
                )

            self.assertEqual(len(prompts), 1)
            self.assertEqual(prompts[0]["source"], "Google Scholar")

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
            planner = FakePlanner(plan)
            agent.planner = planner
            agent.arxiv = FakeArxivClient({})
            agent.discovery_search_planner = FakeDiscoverySearchPlanner([])
            agent.extractor = FakeExtractor(ExtractedPaperContent(method="PDF-grounded method text."))
            agent.taxonomy = TopicTaxonomy()

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
            agent.extractor = FakeExtractor(ExtractedPaperContent(method="PDF-grounded comparison text."))
            agent.taxonomy = TopicTaxonomy()

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
            agent.extractor = FakeExtractor(ExtractedPaperContent(method="Method body for notice test."))
            agent.taxonomy = TopicTaxonomy()

            timeline: list[dict[str, object]] = []
            progress_updates: list[dict[str, object]] = []
            result = agent.run(
                "帮我找一篇论文",
                timeline_callback=timeline.append,
                progress_callback=progress_updates.append,
            )

            self.assertIsInstance(result, RunResult)
            timeline_messages = "\n".join(str(item["message"]) for item in timeline)
            self.assertIn("开始任务规划", timeline_messages)
            self.assertIn("规划完成：discover_papers", timeline_messages)
            self.assertIn("开始检索多源候选论文", timeline_messages)
            self.assertIn("开始处理论文：1 篇", timeline_messages)
            self.assertIn("正在生成报告", timeline_messages)
            self.assertIsInstance(agent.planner.last_extracted_text, ExtractedPaperContent)
            self.assertEqual(agent.planner.last_extracted_text.method, "Method body for notice test.")
            self.assertEqual(progress_updates[0]["stage"], "planning")
            self.assertTrue(any(update["stage"] == "searching" for update in progress_updates))
            self.assertTrue(any(update["stage"] == "processing" for update in progress_updates))
            self.assertTrue(any(update["stage"] == "reporting" for update in progress_updates))
            milestone_messages = [item["message"] for item in timeline if item["kind"] == "milestone"]
            self.assertIn("开始任务规划", milestone_messages)
            self.assertIn("开始检索多源候选论文", milestone_messages)
            self.assertIn("开始处理论文：1 篇", milestone_messages)
            self.assertIn("正在生成报告", milestone_messages)

    def test_run_emits_resolving_progress_for_explain_paper(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            library.upsert_paper(
                make_paper("2401.12345", "Trust but Verify! A Survey on Verification Design for Test-time Scaling"),
                make_digest(),
                b"%PDF-1.4 fake content",
                [],
            )
            plan = RequestPlan(
                intent="explain_paper",
                user_goal="介绍论文",
                search_query="",
                paper_refs=["Trust but Verify! A Survey on Verification Design for Test-time Scaling"],
                max_results=1,
                reuse_local=True,
                rationale="",
            )
            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.settings = FakeSettings(root)
            agent.library = library
            agent.planner = FakePlanner(plan)
            agent.arxiv = FakeArxivClient({})
            agent.discovery_search_planner = FakeDiscoverySearchPlanner([])
            agent.extractor = FakeExtractor(ExtractedPaperContent(method="Explain paper method body."))
            agent.taxonomy = TopicTaxonomy()

            progress_updates: list[dict[str, object]] = []
            result = agent.run(
                "详细介绍这篇论文",
                progress_callback=progress_updates.append,
            )

            self.assertIsInstance(result, RunResult)
            stages = [item["stage"] for item in progress_updates]
            self.assertIn("resolving", stages)
            self.assertIn("processing", stages)
            self.assertIn("reporting", stages)

    def test_run_keeps_processing_progress_when_all_candidates_are_reused(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            paper = make_paper("2604.09999", "Progressive Logging for Agents")
            library.upsert_paper(paper, make_digest(), b"%PDF-1.4 fake content", [])
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
            agent.arxiv = FakeArxivClient({"llm uncertainty": [paper]})
            agent.discovery_search_planner = FakeDiscoverySearchPlanner([SearchSpec(query="llm uncertainty", field="all")])
            agent.extractor = FakeExtractor()
            agent.taxonomy = TopicTaxonomy()

            progress_updates: list[dict[str, object]] = []
            result = agent.run("帮我找一篇论文", progress_callback=progress_updates.append)

            self.assertIsInstance(result, RunResult)
            processing_updates = [item for item in progress_updates if item["stage"] == "processing"]
            self.assertTrue(processing_updates)
            self.assertEqual(processing_updates[-1]["paper_index"], 1)
            self.assertEqual(processing_updates[-1]["paper_total"], 1)

    def test_run_refresh_existing_prefers_local_pdf_for_existing_exact_match(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            paper = make_paper("2604.00001", "CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning")
            library.upsert_paper(paper, make_digest(), b"%PDF-1.4 fake content", [])
            plan = RequestPlan(
                intent="explain_paper",
                user_goal="重新整理论文",
                search_query="",
                paper_refs=["CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning"],
                max_results=1,
                reuse_local=True,
                rationale="",
            )
            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.settings = FakeSettings(root)
            agent.library = library
            agent.planner = FakePlanner(plan)
            agent.arxiv = FakeArxivClient({})
            agent.openreview = FakeSourceClient({})
            agent.scholar = FakeSourceClient({})
            agent.discovery_search_planner = FakeDiscoverySearchPlanner([])
            agent.extractor = FakeExtractor(ExtractedPaperContent(method="Method body for refresh test."))
            agent.taxonomy = TopicTaxonomy()

            timeline: list[dict[str, object]] = []
            result = agent.run(
                "CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning",
                refresh_existing=True,
                timeline_callback=timeline.append,
            )

            self.assertIsInstance(result, RunResult)
            self.assertEqual(agent.arxiv.downloaded_ids, [])
            timeline_messages = "\n".join(str(item["message"]) for item in timeline)
            self.assertIn("已复用本地 PDF 重新整理", timeline_messages)
            self.assertIn("规划完成：explain_paper", timeline_messages)

    def test_run_skips_candidate_without_parseable_pdf(self) -> None:
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

            class NoPdfArxiv(FakeArxivClient):
                def download_pdf_bytes(self, paper: Paper) -> bytes:
                    return b""

            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.settings = FakeSettings(root)
            agent.library = library
            agent.planner = FakePlanner(plan)
            agent.arxiv = NoPdfArxiv({"llm uncertainty": [make_paper("2604.09999", "Progressive Logging for Agents")]})
            agent.openreview = FakeSourceClient({})
            agent.scholar = FakeSourceClient({})
            agent.discovery_search_planner = FakeDiscoverySearchPlanner([SearchSpec(query="llm uncertainty", field="all")])
            agent.extractor = FakeExtractor(ExtractedPaperContent())
            agent.taxonomy = TopicTaxonomy()

            timeline: list[dict[str, object]] = []
            result = agent.run("帮我找一篇论文", timeline_callback=timeline.append)

            self.assertEqual(result.new_papers, [])
            self.assertEqual(library.list_tree()["stats"]["paper_count"], 0)
            self.assertIn("已跳过该论文", "\n".join(str(item["message"]) for item in timeline))

    def test_refresh_paper_metadata_updates_cached_venue_and_citations(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            stored = library.upsert_paper(make_paper("2401.12345", "Test Driven Agents"), make_digest(), b"%PDF-1.4 fake", [])
            updated_paper = make_paper("2401.12345", "Test Driven Agents")
            updated_paper.venue.name = "ICLR"
            updated_paper.venue.kind = "conference"
            updated_paper.venue.year = 2026
            updated_paper.citation_count = 42
            updated_paper.citation_source = "google_scholar"
            updated_paper.citation_updated_at = "2026-04-13T00:00:00+00:00"

            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.settings = FakeSettings(root)
            agent.library = library
            agent.openreview = FakeMetadataClient(updated_paper)
            agent.scholar = FakeMetadataClient(updated_paper)

            refreshed = agent.refresh_paper_metadata(stored.paper.paper_id)

            self.assertIsNotNone(refreshed)
            self.assertEqual(refreshed["refresh"]["status"], "updated")
            self.assertIn("引用量", refreshed["refresh"]["changed_fields"])
            detail = library.get_paper_detail(stored.paper.paper_id)
            self.assertEqual(detail["paper"]["venue"]["name"], "ICLR")
            self.assertEqual(detail["paper"]["citation_count"], 42)

    def test_reanalyze_library_updates_existing_records_from_local_pdf(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            library.upsert_paper(
                make_paper("2401.12345", "Trust but Verify! A Survey on Verification Design for Test-time Scaling"),
                make_digest(),
                b"%PDF-1.4 fake content",
                [],
            )
            plan = RequestPlan(
                intent="explain_paper",
                user_goal="重新分析",
                search_query="",
                paper_refs=[],
                max_results=1,
                reuse_local=True,
                rationale="",
            )

            class RefreshPlanner(FakePlanner):
                def digest_paper(self, *args, **kwargs) -> PaperDigest:
                    self.last_extracted_text = args[2]
                    refreshed = make_digest()
                    refreshed.one_sentence_takeaway = "Refreshed from PDF."
                    refreshed.method = "Updated method explanation from the PDF body."
                    refreshed.experiment_setup = "Updated evaluation setup from the PDF body."
                    refreshed.improvement_ideas = ["Collect more challenging evaluation sets."]
                    return refreshed

            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.settings = FakeSettings(root)
            agent.library = library
            planner = RefreshPlanner(plan)
            agent.planner = planner
            agent.arxiv = FakeArxivClient({})
            agent.discovery_search_planner = FakeDiscoverySearchPlanner([])
            agent.extractor = FakeExtractor(
                ExtractedPaperContent(
                    method="Structured method text from PDF.",
                    experiments="Structured experiments text from PDF.",
                )
            )
            agent.taxonomy = TopicTaxonomy()

            notices: list[str] = []
            updated = agent.reanalyze_library(notice_callback=notices.append)

            self.assertEqual(len(updated), 1)
            self.assertEqual(updated[0].digest.one_sentence_takeaway, "Refreshed from PDF.")
            self.assertEqual(updated[0].digest.experiment_setup, "Updated evaluation setup from the PDF body.")
            self.assertIsInstance(planner.last_extracted_text, ExtractedPaperContent)
            self.assertEqual(planner.last_extracted_text.method, "Structured method text from PDF.")
            detail = library.get_paper_detail("2401.12345")
            self.assertEqual(detail["digest"]["one_sentence_takeaway"], "Refreshed from PDF.")
            self.assertIn("重新分析论文 1/1", "\n".join(notices))

    def test_reanalyze_library_format_only_skips_pdf_parse_and_only_tightens_digest_format(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")
            library.upsert_paper(
                make_paper("2401.12345", "Trust but Verify! A Survey on Verification Design for Test-time Scaling"),
                make_digest(),
                b"%PDF-1.4 fake content",
                [],
            )
            plan = RequestPlan(
                intent="explain_paper",
                user_goal="格式更新",
                search_query="",
                paper_refs=[],
                max_results=1,
                reuse_local=True,
                rationale="",
            )

            class FormatOnlyPlanner(FakePlanner):
                def digest_paper(self, *args, **kwargs) -> PaperDigest:
                    raise AssertionError("format-only path should not call digest_paper")

                def tighten_digest_format_only(self, paper: Paper, digest: PaperDigest, *, notice_callback=None) -> PaperDigest:
                    self.format_only_calls.append(paper.paper_id)
                    refreshed = make_digest()
                    refreshed.method = "整个方法分为两步。\n\n1. **生成**：先采样候选答案。\n\n2. **验证**：再统一排序。"
                    refreshed.experiment_setup = "实验分成两个阶段，\n\n先比较候选规模，再比较验证器质量。"
                    return refreshed

            class FailingExtractor:
                def extract(self, pdf_bytes: bytes) -> str:
                    raise AssertionError("format-only path should not extract PDF text")

                def extract_structured(self, pdf_bytes: bytes) -> ExtractedPaperContent:
                    raise AssertionError("format-only path should not extract PDF text")

            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.settings = FakeSettings(root)
            agent.library = library
            planner = FormatOnlyPlanner(plan)
            agent.planner = planner
            agent.extractor = FailingExtractor()
            agent.taxonomy = TopicTaxonomy()

            notices: list[str] = []
            updated = agent.reanalyze_library(format_only=True, notice_callback=notices.append)

            self.assertEqual(len(updated), 1)
            self.assertEqual(planner.format_only_calls, ["2401.12345"])
            self.assertIsNone(planner.last_extracted_text)
            self.assertIn("\n\n1. **生成**", updated[0].digest.method)
            detail = library.get_paper_detail("2401.12345")
            self.assertEqual(detail["digest"]["experiment_setup"], "实验分成两个阶段，\n\n先比较候选规模，再比较验证器质量。")
            self.assertIn("仅更新最终格式 1/1", "\n".join(notices))

    def test_normalize_library_topics_rehomes_same_family_papers(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            library = PaperLibrary(root / "library")

            first_digest = make_digest()
            first_digest.major_topic = "Test-time_Compute_Scaling"
            first_digest.minor_topic = "LLM_Verifier_RL"
            library.upsert_paper(
                make_paper("2505.04842", "Putting the Value Back in RL: Better Test-Time Scaling by Unifying LLM Reasoners With Verifiers"),
                first_digest,
                b"%PDF-1.4 fake content",
                [],
            )

            second_digest = make_digest()
            second_digest.major_topic = "大语言模型测试时计算"
            second_digest.minor_topic = "语言代理推理增强"
            library.upsert_paper(
                make_paper("2506.12928", "Scaling Test-time Compute for LLM Agents"),
                second_digest,
                b"%PDF-1.4 fake content",
                [],
            )

            agent = AutoPapersAgent.__new__(AutoPapersAgent)
            agent.settings = FakeSettings(root)
            agent.library = library
            agent.taxonomy = TopicTaxonomy()

            notices: list[str] = []
            updated = agent.normalize_library_topics(notice_callback=notices.append)

            self.assertEqual(len(updated), 2)
            first = library.get_paper_detail("2505.04842")
            second = library.get_paper_detail("2506.12928")
            self.assertEqual(first["digest"]["major_topic"], "测试时计算扩展")
            self.assertEqual(second["digest"]["major_topic"], "测试时计算扩展")
            self.assertEqual(first["digest"]["minor_topic"], "验证器与判断器")
            self.assertEqual(second["digest"]["minor_topic"], "语言代理与工具使用")
            self.assertIn("规范化主题", "\n".join(notices))
