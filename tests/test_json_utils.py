from __future__ import annotations

import unittest

from autopapers.json_utils import extract_json_object


class JsonUtilsTests(unittest.TestCase):
    def test_extracts_object_from_markdown_fence(self) -> None:
        payload = """```json
{"intent":"discover_papers","search_query":"agent", "paper_refs":[]}
```"""
        data = extract_json_object(payload)
        self.assertEqual(data["intent"], "discover_papers")

    def test_extracts_first_balanced_object(self) -> None:
        payload = 'Answer: {"intent":"explain_paper","paper_refs":["arXiv:2401.12345"]} trailing text'
        data = extract_json_object(payload)
        self.assertEqual(data["intent"], "explain_paper")

