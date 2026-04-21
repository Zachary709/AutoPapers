from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import time
import unittest

from autopapers.library import PaperLibrary
from autopapers.models import Paper, PaperDigest


def make_paper() -> Paper:
    return Paper(
        paper_id="2401.12345",
        source_primary="arxiv",
        arxiv_id="2401.12345",
        versioned_id="2401.12345v1",
        title="Test Driven Agents",
        abstract="Agent reliability through disciplined evaluation.",
        authors=["Alice", "Bob"],
        published="2025-12-20T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        entry_id="http://arxiv.org/abs/2401.12345v1",
        entry_url="http://arxiv.org/abs/2401.12345v1",
        pdf_url="http://arxiv.org/pdf/2401.12345v1",
        primary_category="cs.AI",
        categories=["cs.AI", "cs.LG"],
    )


def make_digest() -> PaperDigest:
    return PaperDigest(
        major_topic="Agents",
        minor_topic="Evaluation",
        keywords=["agents", "evaluation"],
        abstract_zh="本文研究如何通过结构化评测提升智能体系统的可靠性。",
        one_sentence_takeaway="The paper shows evaluation-first agents are more reliable.",
        background="Reliable agents need better benchmarks.",
        problem="How to improve reliability in autonomous agents.",
        method="Benchmarking plus iterative refinement.",
        experiment_setup="Experiments compare structured evaluation against a plain baseline.",
        findings=["Reliability improves under structured evaluation."],
        limitations=["The benchmark is still narrow."],
        relevance="Useful as a baseline for agent harness design.",
        improvement_ideas=["Expand the benchmark to broader tasks."],
    )


class PaperLibraryTests(unittest.TestCase):
    def test_prepare_markdown_section_body_preserves_paragraphs_lists_and_formulas(self) -> None:
        body = (
            "本文通过相关性分析识别关键不确定性度量。包括： 1. **数据集构建**：收集多波次问卷数据。 "
            "2. **实验设计**：统一 query 模板并比较多个指标。 $$NS=|\\{v_i:\\sum_{j=1}^{|V_k|}P(v_j|q_b)\\leq0.95\\}|$$ "
            "- **Vocabulary Entropy (VE)**：衡量词汇分布熵。"
        )

        formatted = PaperLibrary._prepare_markdown_section_body(body)

        self.assertIn("包括：\n\n1. **数据集构建**", formatted)
        self.assertIn("2. **实验设计**", formatted)
        self.assertIn("\n\n$$NS=|\\{v_i:\\sum_{j=1}^{|V_k|}P(v_j|q_b)\\leq0.95\\}|$$\n\n", formatted)
        self.assertIn("- **Vocabulary Entropy (VE)**", formatted)
        self.assertNotIn("\n##\n", formatted)

    def test_prepare_markdown_section_body_splits_bracketed_subsections(self) -> None:
        body = "【模型与数据】使用多种白盒模型并计算token概率。【分析阶段】第一阶段分析相关性，第二阶段评估预测能力。"

        formatted = PaperLibrary._prepare_markdown_section_body(body)

        self.assertIn("【模型与数据】", formatted)
        self.assertIn("\n\n【分析阶段】", formatted)

    def test_prepare_markdown_section_body_promotes_standalone_numbered_headings(self) -> None:
        body = (
            "1. 问题背景\n"
            "当前方法缺乏统一验证器。\n\n"
            "2. 核心方法：RL^V\n"
            "RL^V 通过联合训练统一推理与验证。\n\n"
            "#### 2.1 训练阶段\n"
            "训练阶段包括联合优化。"
        )

        formatted = PaperLibrary._prepare_markdown_section_body(body)

        self.assertIn("### 问题背景", formatted)
        self.assertIn("### 核心方法：RL^V", formatted)
        self.assertIn("#### 训练阶段", formatted)
        self.assertNotIn("#### 2.1 训练阶段", formatted)

    def test_prepare_markdown_section_body_keeps_real_numbered_lists(self) -> None:
        body = (
            "1. **并行采样**：使用策略为同一问题生成多个候选解。\n\n"
            "2. **验证打分**：利用验证器计算每个解的置信度。\n\n"
            "3. **重排序/投票**：选择最终答案。"
        )

        formatted = PaperLibrary._prepare_markdown_section_body(body)

        self.assertIn("1. **并行采样**", formatted)
        self.assertIn("2. **验证打分**", formatted)
        self.assertIn("3. **重排序/投票**", formatted)
        self.assertNotIn("### **并行采样**", formatted)

    def test_prepare_markdown_section_body_keeps_short_adjacent_numbered_items_as_list(self) -> None:
        body = "1. 苹果\n2. 香蕉\n3. 梨"

        formatted = PaperLibrary._prepare_markdown_section_body(body)

        self.assertEqual(formatted, "1. 苹果\n\n2. 香蕉\n\n3. 梨")

    def test_prepare_markdown_section_body_promotes_short_heading_after_numbered_list(self) -> None:
        body = (
            "1. 并行采样\n\n"
            "2. 验证打分\n\n"
            "3. 重排序/投票\n\n"
            "3. 方法优势\n"
            "- 零额外开销"
        )

        formatted = PaperLibrary._prepare_markdown_section_body(body)

        self.assertIn("3. 重排序/投票", formatted)
        self.assertIn("### 方法优势", formatted)
        self.assertNotIn("\n\n3. 方法优势", formatted)

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
            self.assertIn("## 中文摘要", detail["markdown_content"])
            self.assertIn("## English Abstract", detail["markdown_content"])

    def test_upsert_replaces_stale_tmp_files_for_markdown_metadata_and_index(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            library = PaperLibrary(root)
            stored = library.upsert_paper(make_paper(), make_digest(), b"%PDF-1.4 fake content", [])

            markdown_path = Path(tmp_dir) / stored.md_path
            metadata_path = Path(tmp_dir) / stored.metadata_path
            index_path = root / "index.json"
            tmp_paths = [
                markdown_path.with_name(f"{markdown_path.name}.tmp"),
                metadata_path.with_name(f"{metadata_path.name}.tmp"),
                index_path.with_name(f"{index_path.name}.tmp"),
            ]
            for tmp_path in tmp_paths:
                tmp_path.write_text("partial content from interrupted write", encoding="utf-8")

            updated_digest = make_digest()
            updated_digest.one_sentence_takeaway = "Updated takeaway after atomic rewrite."
            library.upsert_paper(make_paper(), updated_digest, b"%PDF-1.4 fake content", [])

            self.assertIn("Updated takeaway after atomic rewrite.", markdown_path.read_text(encoding="utf-8"))
            metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            index_payload = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(
                metadata_payload["digest"]["one_sentence_takeaway"],
                "Updated takeaway after atomic rewrite.",
            )
            self.assertEqual(
                index_payload["papers"][0]["digest"]["one_sentence_takeaway"],
                "Updated takeaway after atomic rewrite.",
            )
            for tmp_path in tmp_paths:
                self.assertFalse(tmp_path.exists())

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

    def test_library_migrates_legacy_index_records_to_paper_id_model(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            root.mkdir(parents=True, exist_ok=True)
            legacy_payload = {
                "updated_at": "2026-04-13T00:00:00+00:00",
                "papers": [
                    {
                        "paper": {
                            "arxiv_id": "2401.12345",
                            "versioned_id": "2401.12345v1",
                            "title": "Legacy Agents",
                            "abstract": "Legacy abstract",
                            "authors": ["Alice"],
                            "published": "2026-01-01T00:00:00Z",
                            "updated": "2026-01-02T00:00:00Z",
                            "entry_id": "http://arxiv.org/abs/2401.12345v1",
                            "pdf_url": "http://arxiv.org/pdf/2401.12345v1",
                            "primary_category": "cs.AI",
                            "categories": ["cs.AI"],
                        },
                        "digest": {
                            "major_topic": "Agents",
                            "minor_topic": "Evaluation",
                            "keywords": ["agents"],
                            "one_sentence_takeaway": "Legacy note.",
                            "background": "",
                            "problem": "",
                            "method": "",
                            "experiment_setup": "",
                            "findings": [],
                            "limitations": [],
                            "relevance": "",
                            "improvement_ideas": [],
                        },
                        "stored_at": "2026-04-13T00:00:00+00:00",
                        "pdf_path": "library/Agents/Evaluation/2401.12345_Legacy_Agents.pdf",
                        "md_path": "library/Agents/Evaluation/2401.12345_Legacy_Agents.md",
                        "metadata_path": "library/Agents/Evaluation/2401.12345_Legacy_Agents.metadata.json",
                    }
                ],
            }
            (root / "index.json").write_text(json.dumps(legacy_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            library = PaperLibrary(root)
            record = library.get_by_paper_id("2401.12345")

            self.assertIsNotNone(record)
            self.assertEqual(record.paper.paper_id, "2401.12345")
            self.assertEqual(record.paper.source_primary, "arxiv")

    def test_markdown_omits_empty_optional_sections(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            library = PaperLibrary(root)
            digest = make_digest()
            digest.abstract_zh = ""
            digest.experiment_setup = ""
            digest.findings = []
            digest.limitations = []
            digest.improvement_ideas = []

            stored = library.upsert_paper(make_paper(), digest, b"%PDF-1.4 fake content", [])
            markdown = (Path(tmp_dir) / stored.md_path).read_text(encoding="utf-8")

            self.assertIn("## 一句话概括", markdown)
            self.assertIn("暂无中文摘要。", markdown)
            self.assertIn("## 方法怎么理解", markdown)
            self.assertNotIn("## 实验怎么设置", markdown)
            self.assertNotIn("## 实验里最值得关注的点", markdown)
            self.assertNotIn("## 局限", markdown)
            self.assertNotIn("## 可以怎么优化", markdown)

    def test_markdown_groups_front_matter_into_snapshot_sections(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "library"
            library = PaperLibrary(root)
            stored = library.upsert_paper(make_paper(), make_digest(), b"%PDF-1.4 fake content", [])

            markdown = (Path(tmp_dir) / stored.md_path).read_text(encoding="utf-8")

            self.assertIn("## Paper Snapshot", markdown)
            self.assertIn("### Identity", markdown)
            self.assertIn("### Publication", markdown)
            self.assertIn("### Research Context", markdown)
            self.assertIn("## 中文摘要", markdown)
            self.assertIn("## English Abstract", markdown)
            self.assertNotIn("- Google Scholar: unavailable", markdown)
