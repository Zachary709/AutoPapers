from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import json
import re
import time
from typing import Callable
import urllib.parse
import urllib.request
from urllib.error import HTTPError

from autopapers.http_client import build_url_opener
from autopapers.models import Paper, VenueInfo
from autopapers.utils import make_scholar_paper_id, normalize_whitespace, parse_arxiv_id, title_similarity, utc_now_iso


@dataclass(slots=True)
class ScholarSearchResult:
    title: str = ""
    entry_url: str = ""
    pdf_url: str = ""
    meta_line: str = ""
    snippet: str = ""
    cited_by_url: str = ""
    citation_count: int | None = None


class ScholarBlockedError(RuntimeError):
    pass


class ScholarHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url.rstrip("/")
        self.results: list[ScholarSearchResult] = []
        self._depth = 0
        self._current: ScholarSearchResult | None = None
        self._result_depth = 0
        self._field_stack: list[tuple[str, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._depth += 1
        attrs_dict = {key: value or "" for key, value in attrs}
        class_attr = attrs_dict.get("class", "")
        classes = set(class_attr.split())

        if tag == "div" and {"gs_r", "gs_or"} <= classes:
            self._current = ScholarSearchResult()
            self._result_depth = self._depth
            self.results.append(self._current)
            return

        if self._current is None:
            return

        if tag == "div" and "gs_a" in classes:
            self._field_stack.append(("meta", self._depth))
            return
        if tag == "div" and "gs_rs" in classes:
            self._field_stack.append(("snippet", self._depth))
            return
        if tag == "div" and "gs_or_ggsm" in classes:
            self._field_stack.append(("pdf", self._depth))
            return
        if tag == "h3" and "gs_rt" in classes:
            self._field_stack.append(("title", self._depth))
            return

        if tag == "a":
            href = attrs_dict.get("href", "")
            active_field = self._field_stack[-1][0] if self._field_stack else ""
            if active_field == "title" and href:
                self._current.entry_url = self._absolute_url(href)
            elif active_field == "pdf" and href and not self._current.pdf_url:
                self._current.pdf_url = self._absolute_url(href)
            elif "cites=" in href and not self._current.cited_by_url:
                self._current.cited_by_url = self._absolute_url(href)

    def handle_endtag(self, tag: str) -> None:
        if self._current is not None and self._depth == self._result_depth and tag == "div":
            self._current = None
            self._result_depth = 0
            self._field_stack.clear()
        while self._field_stack and self._field_stack[-1][1] >= self._depth:
            self._field_stack.pop()
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        text = normalize_whitespace(unescape(data))
        if not text:
            return
        cited_match = re.search(r"Cited by\s+(\d+)", text, flags=re.IGNORECASE)
        if cited_match:
            self._current.citation_count = int(cited_match.group(1))
        if not self._field_stack:
            return
        field = self._field_stack[-1][0]
        if field == "title":
            self._current.title = normalize_whitespace(f"{self._current.title} {text}")
        elif field == "meta":
            self._current.meta_line = normalize_whitespace(f"{self._current.meta_line} {text}")
        elif field == "snippet":
            self._current.snippet = normalize_whitespace(f"{self._current.snippet} {text}")

    def _absolute_url(self, href: str) -> str:
        if href.startswith("http://") or href.startswith("https://"):
            return href
        return f"{self.base_url}{href}"


class ScholarClient:
    base_url = "https://scholar.google.com"
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        timeout: int = 120,
        *,
        opener: Callable[..., object] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.timeout = timeout
        self._opener = opener or build_url_opener().open
        self._sleep = sleep_fn or time.sleep

    def search(self, query: str, max_results: int = 5) -> list[Paper]:
        normalized = normalize_whitespace(query)
        if not normalized:
            return []
        params = urllib.parse.urlencode({"hl": "en", "q": normalized})
        html_text = self._get_text(f"{self.base_url}/scholar?{params}")
        if self._is_blocked_html(html_text):
            raise ScholarBlockedError("Google Scholar 返回验证码页面")
        return self._parse_results(html_text)[:max_results]

    def resolve_reference(self, reference: str) -> Paper:
        candidates = self.search(reference, max_results=5)
        if not candidates:
            raise LookupError(f"Could not resolve Scholar reference: {reference}")
        best = max(candidates, key=lambda item: title_similarity(reference, item.title))
        if title_similarity(reference, best.title) < 0.72:
            raise LookupError(f"Could not resolve Scholar reference: {reference}")
        return best

    def enrich_metadata(self, paper: Paper) -> Paper:
        blocked = False
        try:
            resolved = self.resolve_reference(paper.title)
        except ScholarBlockedError:
            blocked = True
            resolved = None
        except LookupError:
            resolved = None
        if resolved is not None:
            return resolved
        fallback = self._semantic_scholar_enrich(paper)
        if fallback is not None:
            return fallback
        return paper

    def download_pdf_bytes(self, paper: Paper) -> bytes:
        if not paper.pdf_url:
            raise ValueError(f"No Scholar PDF URL available for {paper.title}")
        request = urllib.request.Request(paper.pdf_url, headers={"User-Agent": self.user_agent})
        with self._opener(request, timeout=self.timeout) as response:
            return response.read()

    def _get_text(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with self._opener(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def enrich_metadata_report(self, paper: Paper) -> dict[str, object]:
        try:
            resolved = self.resolve_reference(paper.title)
        except ScholarBlockedError:
            fallback = self._semantic_scholar_enrich(paper)
            if fallback is not None:
                return {
                    "paper": fallback,
                    "status": "updated",
                    "message": "Google Scholar 返回验证码页面，已改用 Semantic Scholar 精确补充元数据。",
                    "fallback_used": "semantic_scholar",
                }
            dblp_fallback = self._dblp_enrich(paper)
            if dblp_fallback is not None:
                return {
                    "paper": dblp_fallback,
                    "status": "updated",
                    "message": "Google Scholar 返回验证码页面，Semantic Scholar 暂时被限流，已改用 DBLP 补充收录信息；引用量暂不可用。",
                    "fallback_used": "dblp",
                }
            return {
                "paper": paper,
                "status": "error",
                "message": "Google Scholar 返回验证码页面，且后备来源未命中。",
                "fallback_used": "",
            }
        except LookupError:
            fallback = self._semantic_scholar_enrich(paper)
            if fallback is not None:
                return {
                    "paper": fallback,
                    "status": "updated",
                    "message": "Google Scholar 未命中，已改用 Semantic Scholar 精确补充元数据。",
                    "fallback_used": "semantic_scholar",
                }
            dblp_fallback = self._dblp_enrich(paper)
            if dblp_fallback is not None:
                return {
                    "paper": dblp_fallback,
                    "status": "updated",
                    "message": "Google Scholar 未命中，已改用 DBLP 补充收录信息；引用量暂不可用。",
                    "fallback_used": "dblp",
                }
            return {
                "paper": paper,
                "status": "unchanged",
                "message": "未返回新的收录或引用信息。",
                "fallback_used": "",
            }
        return {
            "paper": resolved,
            "status": "updated" if resolved != paper else "unchanged",
            "message": "已从 Google Scholar 获取元数据。" if resolved != paper else "未返回新的收录或引用信息。",
            "fallback_used": "",
        }

    def _semantic_scholar_enrich(self, paper: Paper) -> Paper | None:
        payload = None
        if paper.arxiv_id:
            payload = self._semantic_scholar_lookup(f"ARXIV:{paper.arxiv_id}")
        if payload is None and paper.doi:
            payload = self._semantic_scholar_lookup(f"DOI:{paper.doi}")
        if payload is None:
            return None
        venue_name = normalize_whitespace(str(payload.get("venue") or ""))
        year = payload.get("year")
        try:
            venue_year = int(year) if year not in (None, "") else None
        except (TypeError, ValueError):
            venue_year = None
        citation_count = payload.get("citationCount")
        try:
            normalized_citation_count = int(citation_count) if citation_count not in (None, "") else None
        except (TypeError, ValueError):
            normalized_citation_count = None
        external_ids = payload.get("externalIds") or {}
        doi = normalize_whitespace(str(external_ids.get("DOI") or paper.doi or ""))
        return Paper(
            paper_id=paper.paper_id,
            source_primary=paper.source_primary,
            title=normalize_whitespace(str(payload.get("title") or paper.title)),
            abstract=paper.abstract,
            authors=paper.authors,
            published=paper.published,
            updated=paper.updated,
            entry_id=paper.entry_id,
            entry_url=paper.entry_url or normalize_whitespace(str(payload.get("url") or "")),
            pdf_url=paper.pdf_url,
            primary_category=paper.primary_category,
            categories=paper.categories,
            arxiv_id=paper.arxiv_id,
            versioned_id=paper.versioned_id,
            openreview_id=paper.openreview_id,
            openreview_forum_id=paper.openreview_forum_id,
            doi=doi,
            scholar_url=paper.scholar_url,
            openreview_url=paper.openreview_url,
            venue=VenueInfo(name=venue_name, kind=self._guess_venue_kind(venue_name), year=venue_year),
            citation_count=normalized_citation_count,
            citation_source="semantic_scholar" if normalized_citation_count is not None else "",
            citation_updated_at=utc_now_iso() if normalized_citation_count is not None else "",
        )

    def _semantic_scholar_lookup(self, identifier: str) -> dict | None:
        normalized = normalize_whitespace(identifier)
        if not normalized:
            return None
        fields = "title,venue,year,citationCount,externalIds,url"
        url = f"https://api.semanticscholar.org/graph/v1/paper/{urllib.parse.quote(normalized, safe=':')}?fields={fields}"
        for attempt in range(1, 4):
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with self._opener(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code == 429 and attempt < 3:
                    self._sleep(float(attempt))
                    continue
                return None
        return None

    def _dblp_enrich(self, paper: Paper) -> Paper | None:
        query = paper.arxiv_id or paper.doi or paper.title
        normalized_query = normalize_whitespace(query)
        if not normalized_query:
            return None
        url = f"https://dblp.org/search/publ/api?q={urllib.parse.quote(normalized_query)}&format=json&h=10"
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with self._opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError:
            return None
        hits = (((payload.get("result") or {}).get("hits") or {}).get("hit")) or []
        if isinstance(hits, dict):
            hits = [hits]
        best_info = None
        best_score = 0.0
        for hit in hits:
            info = hit.get("info") or {}
            title = normalize_whitespace(str(info.get("title") or "")).rstrip(".")
            if not title:
                continue
            score = title_similarity(paper.title, title)
            if normalized_query == paper.arxiv_id and title.casefold() == paper.title.casefold():
                score = max(score, 0.99)
            if score > best_score:
                best_score = score
                best_info = info
        if best_info is None or best_score < 0.9:
            return None
        venue_name = normalize_whitespace(str(best_info.get("venue") or ""))
        year = best_info.get("year")
        try:
            venue_year = int(year) if year not in (None, "") else None
        except (TypeError, ValueError):
            venue_year = None
        doi = normalize_whitespace(str(best_info.get("doi") or paper.doi or ""))
        return Paper(
            paper_id=paper.paper_id,
            source_primary=paper.source_primary,
            title=paper.title,
            abstract=paper.abstract,
            authors=paper.authors,
            published=paper.published,
            updated=paper.updated,
            entry_id=paper.entry_id,
            entry_url=paper.entry_url,
            pdf_url=paper.pdf_url,
            primary_category=paper.primary_category,
            categories=paper.categories,
            arxiv_id=paper.arxiv_id,
            versioned_id=paper.versioned_id,
            openreview_id=paper.openreview_id,
            openreview_forum_id=paper.openreview_forum_id,
            doi=doi,
            scholar_url=paper.scholar_url,
            openreview_url=paper.openreview_url,
            venue=VenueInfo(name=venue_name, kind=self._guess_venue_kind(venue_name), year=venue_year),
            citation_count=paper.citation_count,
            citation_source=paper.citation_source,
            citation_updated_at=paper.citation_updated_at,
        )

    def _parse_results(self, html_text: str) -> list[Paper]:
        parser = ScholarHTMLParser(self.base_url)
        parser.feed(html_text)
        captured_at = utc_now_iso()
        papers: list[Paper] = []
        for result in parser.results:
            title = normalize_whitespace(result.title)
            if not title:
                continue
            authors, venue_name, year = self._parse_meta_line(result.meta_line)
            scholar_url = result.cited_by_url or self._query_url(title)
            arxiv_id = parse_arxiv_id(result.entry_url) or parse_arxiv_id(result.pdf_url)
            if arxiv_id:
                paper_id = arxiv_id
            else:
                paper_id = make_scholar_paper_id(title, scholar_url)
            venue = VenueInfo(name=venue_name, kind=self._guess_venue_kind(venue_name), year=year)
            published = f"{year}-01-01T00:00:00Z" if year else ""
            papers.append(
                Paper(
                    paper_id=paper_id,
                    source_primary="scholar",
                    title=title,
                    abstract=result.snippet,
                    authors=authors,
                    published=published,
                    updated=published,
                    entry_id=result.entry_url,
                    entry_url=result.entry_url,
                    pdf_url=result.pdf_url,
                    primary_category="",
                    categories=[],
                    arxiv_id=arxiv_id or "",
                    versioned_id=arxiv_id or "",
                    scholar_url=scholar_url,
                    venue=venue,
                    citation_count=result.citation_count,
                    citation_source="google_scholar" if result.citation_count is not None else "",
                    citation_updated_at=captured_at if result.citation_count is not None else "",
                )
            )
        return papers

    def _query_url(self, title: str) -> str:
        return f"{self.base_url}/scholar?{urllib.parse.urlencode({'hl': 'en', 'q': title})}"

    @staticmethod
    def _is_blocked_html(html_text: str) -> bool:
        return "Please show you&#39;re not a robot" in html_text or 'id="gs_captcha_ccl"' in html_text

    @staticmethod
    def _parse_meta_line(meta_line: str) -> tuple[list[str], str, int | None]:
        cleaned = normalize_whitespace(meta_line)
        if not cleaned:
            return [], "", None
        parts = [normalize_whitespace(part) for part in cleaned.split(" - ") if normalize_whitespace(part)]
        authors = [item.strip() for item in parts[0].split(",") if item.strip()] if parts else []
        venue_candidate = parts[1] if len(parts) >= 2 else ""
        year = ScholarClient._extract_year(cleaned)
        venue_name = re.sub(r"\b(19|20)\d{2}\b", "", venue_candidate).strip(" ,")
        return authors, venue_name, year

    @staticmethod
    def _extract_year(text: str) -> int | None:
        match = re.search(r"\b(19|20)\d{2}\b", text or "")
        return int(match.group(0)) if match else None

    @staticmethod
    def _guess_venue_kind(venue_name: str) -> str:
        lowered = normalize_whitespace(venue_name).casefold()
        if not lowered:
            return ""
        if any(token in lowered for token in ("journal", "transactions", "review", "letters")):
            return "journal"
        if any(token in lowered for token in ("conference", "workshop", "symposium", "iclr", "neurips", "icml", "acl", "emnlp", "cvpr")):
            return "conference"
        return "venue"
