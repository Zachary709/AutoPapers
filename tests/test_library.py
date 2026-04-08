from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from autopapers.library import PaperLibrary
from autopapers.models import Paper, PaperDigest


def make_paper() -> Paper:
    return Paper(
        arxiv_id="2401.12345",
        versioned_id="2401.12345v1",
        title="Test Driven Agents",
        abstract="Agent reliability through disciplined evaluation.",
        authors=["Alice", "Bob"],
        published="2025-12-20T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        entry_id="http://arxiv.org/abs/2401.12345v1",
        pdf_url="http://arxiv.org/pdf/2401.12345v1",
        primary_category="cs.AI",
        categories=["cs.AI", "cs.LG"],
    )


def make_digest() -> PaperDigest:
    return PaperDigest(
        major_topic="Agents",
        minor_topic="Evaluation",
        keywords=["agents", "evaluation"],
        one_sentence_takeaway="The paper shows evaluation-first agents are more reliable.",
        background="Reliable agents need better benchmarks.",
        problem="How to improve reliability in autonomous agents.",
        method="Benchmarking plus iterative refinement.",
        findings=["Reliability improves under structured evaluation."],
        limitations=["The benchmark is still narrow."],
        relevance="Useful as a baseline for agent harness design.",
    )


class PaperLibraryTests(unittest.TestCase):
    def test_upsert_writes_files_index_and_tree_payload(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            library = PaperLibrary(root)
            stored = library.upsert_paper(make_paper(), make_digest(), b"%PDF-1.4 fake content", [])

            self.assertTrue((Path(tmp_dir) / stored.md_path).exists())
            self.assertTrue((Path(tmp_dir) / stored.metadata_path).exists())
            self.assertTrue((Path(tmp_dir) / stored.pdf_path).exists())
            self.assertTrue((root / "index.json").exists())
            self.assertTrue((root / "README.md").exists())
            self.assertTrue((root / "Agents" / "README.md").exists())
            self.assertTrue((root / "Agents" / "Evaluation" / "README.md").exists())

            tree = library.list_tree()
            self.assertEqual(tree["stats"]["paper_count"], 1)
            self.assertEqual(tree["major_topics"][0]["name"], "Agents")
            self.assertEqual(tree["major_topics"][0]["minor_topics"][0]["papers"][0]["arxiv_id"], "2401.12345")

            detail = library.get_paper_detail("2401.12345")
            self.assertIsNotNone(detail)
            self.assertEqual(detail["paper"]["title"], "Test Driven Agents")
            self.assertTrue(detail["flags"]["pdf_exists"])

    def test_find_by_title_matches_clean_reference_text(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            library = PaperLibrary(root)
            library.upsert_paper(make_paper(), make_digest(), b"%PDF-1.4 fake content", [])

            record = library.find_by_title("详细介绍下这个论文：Test Driven Agents")

            self.assertIsNotNone(record)
            self.assertEqual(record.paper.arxiv_id, "2401.12345")

    def test_find_best_title_match_handles_fuzzy_reference(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            library = PaperLibrary(root)
            library.upsert_paper(make_paper(), make_digest(), b"%PDF-1.4 fake content", [])

            record = library.find_best_title_match("Test Driven Agent")

            self.assertIsNotNone(record)
            self.assertEqual(record.paper.arxiv_id, "2401.12345")

    def test_delete_paper_prunes_library_contents(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            library = PaperLibrary(root)
            library.upsert_paper(make_paper(), make_digest(), b"%PDF-1.4 fake content", [])

            deleted = library.delete_paper("2401.12345")
            self.assertTrue(deleted)
            self.assertIsNone(library.get_by_arxiv_id("2401.12345"))
            self.assertEqual(library.list_tree()["stats"]["paper_count"], 0)
            self.assertFalse((root / "Agents").exists())

    def test_library_reloads_index_when_external_reorganization_changes_paths(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            library = PaperLibrary(root)
            library.upsert_paper(make_paper(), make_digest(), b"%PDF-1.4 fake content", [])

            external_library = PaperLibrary(root)
            updated_digest = make_digest()
            updated_digest.major_topic = "Updated Agents"
            updated_digest.minor_topic = "New Evaluation"
            updated_digest.one_sentence_takeaway = "The refreshed note moved to a new topic path."

            time.sleep(0.01)
            external_library.upsert_paper(make_paper(), updated_digest, b"%PDF-1.4 fake content", [])

            detail = library.get_paper_detail("2401.12345")

            self.assertIsNotNone(detail)
            self.assertEqual(detail["digest"]["major_topic"], "Updated Agents")
            self.assertEqual(detail["digest"]["minor_topic"], "New Evaluation")
            self.assertIn("Updated_Agents/New_Evaluation", detail["paths"]["markdown"])
            self.assertTrue(detail["flags"]["markdown_exists"])
            self.assertTrue(detail["flags"]["pdf_exists"])
