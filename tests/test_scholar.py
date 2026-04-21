from __future__ import annotations

from io import BytesIO
import json
import unittest

from autopapers.models import Paper
from autopapers.scholar import ScholarClient


SCHOLAR_HTML = """
<html><body>
  <div class="gs_r gs_or gs_scl">
    <div class="gs_or_ggsm"><a href="https://arxiv.org/pdf/2501.12345.pdf">[PDF]</a></div>
    <h3 class="gs_rt"><a href="https://arxiv.org/abs/2501.12345">Calibrated Test-Time Scaling for Efficient LLM Reasoning</a></h3>
    <div class="gs_a">A. Researcher, B. Author - ICLR, 2026</div>
    <div class="gs_rs">We present a calibrated test-time scaling framework for reasoning models.</div>
    <div class="gs_fl"><a href="/scholar?cites=1234567890">Cited by 42</a></div>
  </div>
</body></html>
"""


class FakeHTTPResponse:
    def __init__(self, payload: bytes) -> None:
        self._buffer = BytesIO(payload)

    def read(self) -> bytes:
        return self._buffer.read()

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class ScholarClientTests(unittest.TestCase):
    def test_search_parses_title_venue_and_citations_from_html(self) -> None:
        opener = lambda request, timeout=0: FakeHTTPResponse(SCHOLAR_HTML.encode("utf-8"))
        client = ScholarClient(opener=opener)

        papers = client.search("calibrated test-time scaling", max_results=5)

        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper.title, "Calibrated Test-Time Scaling for Efficient LLM Reasoning")
        self.assertEqual(paper.paper_id, "2501.12345")
        self.assertEqual(paper.arxiv_id, "2501.12345")
        self.assertEqual(paper.venue.name, "ICLR")
        self.assertEqual(paper.venue.year, 2026)
        self.assertEqual(paper.citation_count, 42)
        self.assertEqual(paper.citation_source, "google_scholar")
        self.assertIn("scholar?cites=1234567890", paper.scholar_url)

    def test_enrich_metadata_report_falls_back_to_semantic_scholar_when_google_scholar_is_blocked(self) -> None:
        captcha_html = """
        <html><body><div id="gs_captcha_ccl"><h1>Please show you're not a robot</h1></div></body></html>
        """
        semantic_payload = {
            "title": "Attention is All you Need",
            "venue": "Neural Information Processing Systems",
            "year": 2017,
            "citationCount": 172536,
            "externalIds": {"ArXiv": "1706.03762"},
            "url": "https://www.semanticscholar.org/paper/204e3073870fae3d05bcbc2f6a8e263d9b72e776",
        }

        def opener(request, timeout=0):
            url = request.full_url
            if "api.semanticscholar.org" in url:
                return FakeHTTPResponse(json.dumps(semantic_payload).encode("utf-8"))
            return FakeHTTPResponse(captcha_html.encode("utf-8"))

        client = ScholarClient(opener=opener)
        base = Paper(
            paper_id="1706.03762",
            source_primary="arxiv",
            arxiv_id="1706.03762",
            versioned_id="1706.03762v7",
            title="Attention Is All You Need",
            abstract="",
            authors=[],
            published="2017-06-13T00:00:00Z",
            updated="2017-06-13T00:00:00Z",
            entry_id="http://arxiv.org/abs/1706.03762v7",
            entry_url="http://arxiv.org/abs/1706.03762v7",
            pdf_url="http://arxiv.org/pdf/1706.03762v7",
            primary_category="cs.CL",
            categories=["cs.CL", "cs.LG"],
        )

        report = client.enrich_metadata_report(base)

        self.assertEqual(report["status"], "updated")
        self.assertEqual(report["fallback_used"], "semantic_scholar")
        enriched = report["paper"]
        self.assertEqual(enriched.venue.name, "Neural Information Processing Systems")
        self.assertEqual(enriched.citation_count, 172536)
        self.assertEqual(enriched.citation_source, "semantic_scholar")

    def test_enrich_metadata_report_falls_back_to_dblp_when_scholar_is_blocked_and_semantic_scholar_is_rate_limited(self) -> None:
        captcha_html = """
        <html><body><div id="gs_captcha_ccl"><h1>Please show you're not a robot</h1></div></body></html>
        """
        dblp_payload = {
            "result": {
                "hits": {
                    "hit": [
                        {
                            "info": {
                                "title": "Attention Is All You Need.",
                                "venue": "CoRR",
                                "year": "2017",
                                "doi": "",
                            }
                        }
                    ]
                }
            }
        }

        def opener(request, timeout=0):
            url = request.full_url
            if "api.semanticscholar.org" in url:
                raise __import__("urllib.error").error.HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)
            if "dblp.org/search/publ/api" in url:
                return FakeHTTPResponse(json.dumps(dblp_payload).encode("utf-8"))
            return FakeHTTPResponse(captcha_html.encode("utf-8"))

        client = ScholarClient(opener=opener, sleep_fn=lambda _: None)
        base = Paper(
            paper_id="1706.03762",
            source_primary="arxiv",
            arxiv_id="1706.03762",
            versioned_id="1706.03762v7",
            title="Attention Is All You Need",
            abstract="",
            authors=[],
            published="2017-06-13T00:00:00Z",
            updated="2017-06-13T00:00:00Z",
            entry_id="http://arxiv.org/abs/1706.03762v7",
            entry_url="http://arxiv.org/abs/1706.03762v7",
            pdf_url="http://arxiv.org/pdf/1706.03762v7",
            primary_category="cs.CL",
            categories=["cs.CL", "cs.LG"],
        )

        report = client.enrich_metadata_report(base)

        self.assertEqual(report["status"], "updated")
        self.assertEqual(report["fallback_used"], "dblp")
        enriched = report["paper"]
        self.assertEqual(enriched.venue.name, "CoRR")
        self.assertEqual(enriched.venue.year, 2017)
        self.assertIsNone(enriched.citation_count)
