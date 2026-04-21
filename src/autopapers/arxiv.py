from __future__ import annotations

from threading import Lock
from typing import Callable
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError

from autopapers.http_client import build_url_opener
from autopapers.models import Paper, VenueInfo
from autopapers.utils import normalize_whitespace, parse_arxiv_id


ATOM_NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
ADVANCED_QUERY_PATTERN = re.compile(
    r"\b(?:ti|au|abs|co|jr|cat|rn|id|all):|\b(?:AND|OR|ANDNOT)\b|[()]",
    re.IGNORECASE,
)


class ArxivError(RuntimeError):
    pass


class ArxivRateLimitError(ArxivError):
    pass


class ArxivRequestError(ArxivError):
    pass


class ArxivClient:
    search_url = "http://export.arxiv.org/api/query"
    user_agent = "AutoPapers/0.1 (https://github.com/Zachary709/AutoPapers)"

    def __init__(
        self,
        timeout: int = 120,
        *,
        min_interval_seconds: float = 3.0,
        retry_backoff_seconds: float = 3.0,
        max_attempts: int = 3,
        sleep_fn: Callable[[float], None] | None = None,
        monotonic_fn: Callable[[], float] | None = None,
        opener: Callable[..., object] | None = None,
    ) -> None:
        self.timeout = timeout
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self._sleep = sleep_fn or time.sleep
        self._monotonic = monotonic_fn or time.monotonic
        self._opener = opener or build_url_opener().open
        self._request_lock = Lock()
        self._next_request_at = 0.0

    def search(
        self,
        query: str,
        max_results: int = 5,
        field: str = "all",
        *,
        sort_by: str = "relevance",
        sort_order: str = "descending",
    ) -> list[Paper]:
        if not query.strip():
            return []
        params = {
            "search_query": self._build_search_query(query, field=field),
            "start": 0,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
        xml_text = self._get_text(f"{self.search_url}?{urllib.parse.urlencode(params)}")
        return parse_feed(xml_text)

    def fetch_by_ids(self, arxiv_ids: list[str]) -> list[Paper]:
        cleaned = [identifier.strip() for identifier in arxiv_ids if identifier.strip()]
        if not cleaned:
            return []
        params = {
            "id_list": ",".join(cleaned),
            "start": 0,
            "max_results": len(cleaned),
        }
        xml_text = self._get_text(f"{self.search_url}?{urllib.parse.urlencode(params)}")
        return parse_feed(xml_text)

    def resolve_reference(self, reference: str) -> Paper:
        arxiv_id = parse_arxiv_id(reference)
        if arxiv_id:
            papers = self.fetch_by_ids([arxiv_id])
            if papers:
                return papers[0]

        papers = self.search(reference, max_results=1, field="ti")
        if papers:
            return papers[0]

        papers = self.search(reference, max_results=1, field="all")
        if papers:
            return papers[0]

        raise LookupError(f"Could not resolve paper reference: {reference}")

    def download_pdf_bytes(self, paper: Paper) -> bytes:
        request = urllib.request.Request(
            paper.pdf_url,
            headers={"User-Agent": self.user_agent},
        )
        with self._opener(request, timeout=self.timeout) as response:
            return response.read()

    def _get_text(self, url: str) -> str:
        for attempt in range(1, self.max_attempts + 1):
            self._wait_for_request_slot()
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with self._opener(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8")
            except HTTPError as exc:
                if exc.code == 429:
                    if attempt >= self.max_attempts:
                        raise ArxivRateLimitError(
                            "arXiv API rate-limited this request after "
                            f"{self.max_attempts} attempts. "
                            f"AutoPapers now waits {self.min_interval_seconds:g}s between API calls, "
                            "but arXiv is still throttling this query. Please retry in a moment."
                        ) from exc
                    self._sleep(self._retry_delay_seconds(exc, attempt))
                    continue
                if self._is_retryable_http_status(exc.code) and attempt < self.max_attempts:
                    self._sleep(self._retry_delay_seconds(exc, attempt))
                    continue
                raise ArxivRequestError(
                    f"arXiv API request failed with HTTP {exc.code}: {exc.reason or 'Unknown Error'}"
                ) from exc
            except URLError as exc:
                if attempt >= self.max_attempts:
                    raise ArxivRequestError(
                        "arXiv API request failed after "
                        f"{self.max_attempts} attempts: {exc.reason}"
                    ) from exc
                self._sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
        raise AssertionError("Unreachable")

    def _wait_for_request_slot(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        while True:
            with self._request_lock:
                now = self._monotonic()
                wait_seconds = self._next_request_at - now
                if wait_seconds <= 0:
                    self._next_request_at = now + self.min_interval_seconds
                    return
            self._sleep(wait_seconds)

    def _retry_delay_seconds(self, error: HTTPError, attempt: int) -> float:
        retry_after = error.headers.get("Retry-After") if error.headers else None
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return self.retry_backoff_seconds * (2 ** (attempt - 1))

    @staticmethod
    def _is_retryable_http_status(status_code: int) -> bool:
        return status_code in {500, 502, 503, 504}

    @staticmethod
    def _build_search_query(query: str, field: str) -> str:
        normalized = normalize_whitespace(query)
        if field == "raw" or ADVANCED_QUERY_PATTERN.search(normalized):
            return normalized

        escaped = normalized.replace('"', '\\"').strip()
        if field == "ti":
            return f'ti:"{escaped}"'
        if field == "au":
            return f'au:"{escaped}"'

        terms = [term for term in re.findall(r"[A-Za-z0-9\-]+", normalized) if term]
        if not terms:
            return f'all:"{escaped}"'
        if len(terms) == 1:
            return f"all:{terms[0]}"
        return " AND ".join(f"all:{term}" for term in terms)


def parse_feed(xml_text: str) -> list[Paper]:
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ATOM_NAMESPACES):
        entry_id = entry.findtext("atom:id", default="", namespaces=ATOM_NAMESPACES).strip()
        versioned_id = entry_id.rstrip("/").rsplit("/", 1)[-1]
        arxiv_id = versioned_id.split("v", 1)[0]
        title = normalize_whitespace(
            entry.findtext("atom:title", default="", namespaces=ATOM_NAMESPACES)
        )
        abstract = normalize_whitespace(
            entry.findtext("atom:summary", default="", namespaces=ATOM_NAMESPACES)
        )
        authors = [
            normalize_whitespace(author.findtext("atom:name", default="", namespaces=ATOM_NAMESPACES))
            for author in entry.findall("atom:author", ATOM_NAMESPACES)
        ]
        published = entry.findtext("atom:published", default="", namespaces=ATOM_NAMESPACES).strip()
        updated = entry.findtext("atom:updated", default="", namespaces=ATOM_NAMESPACES).strip()
        categories = [
            item.attrib.get("term", "").strip()
            for item in entry.findall("atom:category", ATOM_NAMESPACES)
            if item.attrib.get("term")
        ]
        primary = entry.find("arxiv:primary_category", ATOM_NAMESPACES)
        primary_category = primary.attrib.get("term", "").strip() if primary is not None else ""

        pdf_url = ""
        for link in entry.findall("atom:link", ATOM_NAMESPACES):
            title_attr = link.attrib.get("title", "").lower()
            type_attr = link.attrib.get("type", "").lower()
            if title_attr == "pdf" or type_attr == "application/pdf":
                pdf_url = link.attrib.get("href", "").strip()
                break
        if not pdf_url and versioned_id:
            pdf_url = f"https://arxiv.org/pdf/{versioned_id}.pdf"

        papers.append(
            Paper(
                paper_id=arxiv_id,
                source_primary="arxiv",
                title=title,
                abstract=abstract,
                authors=authors,
                published=published,
                updated=updated,
                entry_id=entry_id,
                entry_url=entry_id,
                pdf_url=pdf_url,
                primary_category=primary_category,
                categories=categories,
                arxiv_id=arxiv_id,
                versioned_id=versioned_id or arxiv_id,
                venue=VenueInfo(name="arXiv", kind="preprint"),
            )
        )
    return papers
