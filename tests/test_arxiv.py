from __future__ import annotations

from http.client import HTTPMessage
import os
from pathlib import Path
import unittest
from urllib.error import HTTPError

from autopapers.arxiv import ArxivClient, ArxivRateLimitError, parse_feed
from autopapers.config import Settings
from autopapers.http_client import build_url_opener


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v2</id>
    <updated>2026-01-01T00:00:00Z</updated>
    <published>2025-12-20T00:00:00Z</published>
    <title> Test Driven Agents </title>
    <summary> A paper about reliable agents. </summary>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
    <arxiv:primary_category term="cs.AI" />
    <category term="cs.AI" />
    <category term="cs.LG" />
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/2401.12345v2" />
    <link title="pdf" rel="related" type="application/pdf" href="http://arxiv.org/pdf/2401.12345v2" />
  </entry>
</feed>
"""


def sample_paper():
    return parse_feed(SAMPLE_FEED)[0]


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleep_calls: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += seconds


class FakeResponse:
    def __init__(self, body: str | bytes) -> None:
        self.body = body.encode("utf-8") if isinstance(body, str) else body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


def make_http_error(url: str, status: int, *, retry_after: str | None = None) -> HTTPError:
    headers = HTTPMessage()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(url, status, "Unknown Error", headers, None)


def make_opener(outcomes: list[object], seen_urls: list[str]):
    remaining = list(outcomes)

    def opener(request, timeout=0):
        seen_urls.append(request.full_url)
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    return opener


class ResolveTrackingClient(ArxivClient):
    def __init__(self, *, id_results=None, title_results=None, all_results=None) -> None:
        super().__init__(timeout=10, opener=make_opener([SAMPLE_FEED], []))
        self.calls: list[tuple] = []
        self.id_results = list(id_results or [])
        self.title_results = list(title_results or [])
        self.all_results = list(all_results or [])

    def fetch_by_ids(self, arxiv_ids: list[str]):
        self.calls.append(("fetch_by_ids", list(arxiv_ids)))
        return list(self.id_results)

    def search(self, query: str, max_results: int = 5, field: str = "all"):
        self.calls.append(("search", query, max_results, field))
        if field == "ti":
            return list(self.title_results)
        return list(self.all_results)


class ArxivFeedTests(unittest.TestCase):
    def test_parse_feed_returns_paper_objects(self) -> None:
        papers = parse_feed(SAMPLE_FEED)
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper.arxiv_id, "2401.12345")
        self.assertEqual(paper.versioned_id, "2401.12345v2")
        self.assertEqual(paper.title, "Test Driven Agents")
        self.assertEqual(paper.authors, ["Alice", "Bob"])
        self.assertEqual(paper.primary_category, "cs.AI")
        self.assertEqual(paper.pdf_url, "http://arxiv.org/pdf/2401.12345v2")

    def test_fetch_by_ids_builds_id_list_query(self) -> None:
        seen_urls: list[str] = []
        client = ArxivClient(
            timeout=10,
            max_attempts=1,
            opener=make_opener([SAMPLE_FEED], seen_urls),
        )

        papers = client.fetch_by_ids(["2401.12345", "2402.54321"])

        self.assertEqual(len(papers), 1)
        self.assertEqual(len(seen_urls), 1)
        self.assertIn("id_list=2401.12345%2C2402.54321", seen_urls[0])

    def test_resolve_reference_prefers_direct_arxiv_id_lookup(self) -> None:
        paper = sample_paper()
        client = ResolveTrackingClient(id_results=[paper])

        resolved = client.resolve_reference("arXiv:2401.12345")

        self.assertEqual(resolved.arxiv_id, "2401.12345")
        self.assertEqual(client.calls, [("fetch_by_ids", ["2401.12345"])])

    def test_resolve_reference_falls_back_from_title_to_all_search(self) -> None:
        paper = sample_paper()
        client = ResolveTrackingClient(all_results=[paper])

        resolved = client.resolve_reference("Test Driven Agents")

        self.assertEqual(resolved.arxiv_id, "2401.12345")
        self.assertEqual(
            client.calls,
            [
                ("search", "Test Driven Agents", 1, "ti"),
                ("search", "Test Driven Agents", 1, "all"),
            ],
        )

    def test_search_retries_after_429_and_returns_results(self) -> None:
        clock = FakeClock()
        seen_urls: list[str] = []
        client = ArxivClient(
            timeout=10,
            min_interval_seconds=3.0,
            retry_backoff_seconds=1.0,
            max_attempts=2,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            opener=make_opener(
                [
                    make_http_error(
                        "http://export.arxiv.org/api/query?search_query=all%3A%22agent%22",
                        429,
                        retry_after="7",
                    ),
                    SAMPLE_FEED,
                ],
                seen_urls,
            ),
        )

        papers = client.search("agent", max_results=1)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].arxiv_id, "2401.12345")
        self.assertEqual(len(seen_urls), 2)
        self.assertEqual(clock.sleep_calls, [7.0])

    def test_search_raises_rate_limit_error_after_retry_exhaustion(self) -> None:
        clock = FakeClock()
        seen_urls: list[str] = []
        client = ArxivClient(
            timeout=10,
            min_interval_seconds=3.0,
            retry_backoff_seconds=1.0,
            max_attempts=3,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            opener=make_opener(
                [
                    make_http_error("http://export.arxiv.org/api/query", 429, retry_after="5"),
                    make_http_error("http://export.arxiv.org/api/query", 429, retry_after="5"),
                    make_http_error("http://export.arxiv.org/api/query", 429, retry_after="5"),
                ],
                seen_urls,
            ),
        )

        with self.assertRaises(ArxivRateLimitError) as context:
            client.search("uncertainty", max_results=1)

        self.assertIn("after 3 attempts", str(context.exception))
        self.assertEqual(len(seen_urls), 3)
        self.assertEqual(clock.sleep_calls, [5.0, 5.0])

    def test_search_paces_back_to_back_api_calls(self) -> None:
        clock = FakeClock()
        seen_urls: list[str] = []
        client = ArxivClient(
            timeout=10,
            min_interval_seconds=3.0,
            max_attempts=1,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            opener=make_opener([SAMPLE_FEED, SAMPLE_FEED], seen_urls),
        )

        client.search("agent", max_results=1)
        client.search("uncertainty", max_results=1)

        self.assertEqual(len(seen_urls), 2)
        self.assertEqual(clock.sleep_calls, [3.0])


@unittest.skipUnless(
    os.environ.get("AUTOPAPERS_RUN_LIVE_TESTS") == "1",
    "requires AUTOPAPERS_RUN_LIVE_TESTS=1",
)
class ArxivLiveTests(unittest.TestCase):
    def test_live_search_returns_results(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        settings = Settings.from_env(repo_root)
        client = ArxivClient(
            timeout=min(settings.request_timeout, 30),
            opener=build_url_opener(settings.network_proxy_url).open,
        )
        query = os.environ.get("AUTOPAPERS_TEST_ARXIV_QUERY", "large language model uncertainty")

        papers = client.search(query, max_results=1)

        self.assertGreaterEqual(len(papers), 1)
        self.assertTrue(papers[0].title.strip())
        self.assertTrue(papers[0].arxiv_id.strip())
