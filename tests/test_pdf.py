from __future__ import annotations

import unittest

from autopapers.pdf import PDFTextExtractor


class PDFTextExtractorTests(unittest.TestCase):
    def test_extract_from_text_merges_hyphenated_english_line_breaks(self) -> None:
        raw_text = "\n".join(
            [
                "Abstract",
                "We evaluate to what degree the human and LLM uncerta-",
                "inty measures align under shared tasks.",
                "1 Introduction",
                "The experi-",
                "ments show section-aware cleanup helps readability.",
            ]
        )

        content = PDFTextExtractor().extract_from_text(raw_text)

        self.assertIn("uncertainty measures align", content.abstract)
        self.assertNotIn("uncerta- inty", content.abstract)
        self.assertIn("experiments show section-aware cleanup", content.introduction)
        self.assertNotIn("experi- ments", content.introduction)

    def test_extract_from_text_segments_sections_and_trims_references(self) -> None:
        filler_lines = [f"Body filler line {index}" for index in range(45)]
        raw_text = "\n".join(
            [
                "Conference Header",
                "Abstract",
                "This paper studies verifier-aware test-time scaling for language models.",
                "1 Introduction",
                "The key intuition is that verifier errors shape the benefit of extra test-time compute.",
                *filler_lines,
                "2 Method",
                "We rerank sampled candidates with a verifier score.",
                "The scoring rule is s(y|x)=log p(y|x)+lambda v(y, x).",
                "3 Experiments",
                "We evaluate on GSM8K and code tasks against best-of-N baselines.",
                "Verifier quality changes the slope of scaling gains.",
                "4 Conclusion",
                "Future work should calibrate verifier uncertainty.",
                "References",
                "[1] Some cited paper",
            ]
        )

        content = PDFTextExtractor(max_pages=18, max_chars=45000).extract_from_text(raw_text)

        self.assertIn("verifier-aware test-time scaling", content.abstract)
        self.assertIn("verifier errors shape the benefit", content.introduction)
        self.assertIn("rerank sampled candidates", content.method)
        self.assertIn("GSM8K and code tasks", content.experiments)
        self.assertIn("calibrate verifier uncertainty", content.conclusion)
        self.assertTrue(content.references_trimmed)
        self.assertNotIn("Some cited paper", content.raw_body)
        self.assertTrue(any("s(y|x)=log p(y|x)+lambda v(y, x)" in item for item in content.equations))

    def test_extract_from_text_falls_back_to_raw_body_without_headings(self) -> None:
        raw_text = (
            "This document has no explicit section headings but still contains body text. "
            "It discusses a paper, a method, and some experimental observations."
        )

        content = PDFTextExtractor().extract_from_text(raw_text)

        self.assertEqual(content.abstract, "")
        self.assertEqual(content.method, "")
        self.assertIn("no explicit section headings", content.raw_body)
