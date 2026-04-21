from __future__ import annotations

from dataclasses import dataclass, field


class TaskCancelledError(RuntimeError):
    pass


@dataclass(slots=True)
class VenueInfo:
    name: str = ""
    kind: str = ""
    year: int | None = None


@dataclass(slots=True)
class RequestPlan:
    intent: str
    user_goal: str
    search_query: str
    paper_refs: list[str]
    max_results: int
    reuse_local: bool = True
    rationale: str = ""


@dataclass(slots=True)
class Paper:
    paper_id: str
    source_primary: str
    title: str
    abstract: str
    authors: list[str]
    published: str
    updated: str
    entry_id: str = ""
    entry_url: str = ""
    pdf_url: str = ""
    primary_category: str = ""
    categories: list[str] = field(default_factory=list)
    arxiv_id: str = ""
    versioned_id: str = ""
    openreview_id: str = ""
    openreview_forum_id: str = ""
    doi: str = ""
    scholar_url: str = ""
    openreview_url: str = ""
    venue: VenueInfo = field(default_factory=VenueInfo)
    citation_count: int | None = None
    citation_source: str = ""
    citation_updated_at: str = ""


@dataclass(slots=True)
class PaperDigest:
    major_topic: str
    minor_topic: str
    keywords: list[str]
    abstract_zh: str = ""
    one_sentence_takeaway: str = ""
    background: str = ""
    problem: str = ""
    method: str = ""
    experiment_setup: str = ""
    findings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    relevance: str = ""
    improvement_ideas: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StoredPaper:
    paper: Paper
    digest: PaperDigest
    stored_at: str
    pdf_path: str
    md_path: str
    metadata_path: str

    def to_dict(self) -> dict:
        return {
            "paper": {
                "paper_id": self.paper.paper_id,
                "source_primary": self.paper.source_primary,
                "arxiv_id": self.paper.arxiv_id,
                "versioned_id": self.paper.versioned_id,
                "title": self.paper.title,
                "abstract": self.paper.abstract,
                "authors": self.paper.authors,
                "published": self.paper.published,
                "updated": self.paper.updated,
                "entry_id": self.paper.entry_id,
                "entry_url": self.paper.entry_url,
                "pdf_url": self.paper.pdf_url,
                "primary_category": self.paper.primary_category,
                "categories": self.paper.categories,
                "openreview_id": self.paper.openreview_id,
                "openreview_forum_id": self.paper.openreview_forum_id,
                "doi": self.paper.doi,
                "scholar_url": self.paper.scholar_url,
                "openreview_url": self.paper.openreview_url,
                "venue": {
                    "name": self.paper.venue.name,
                    "kind": self.paper.venue.kind,
                    "year": self.paper.venue.year,
                },
                "citation_count": self.paper.citation_count,
                "citation_source": self.paper.citation_source,
                "citation_updated_at": self.paper.citation_updated_at,
            },
            "digest": {
                "major_topic": self.digest.major_topic,
                "minor_topic": self.digest.minor_topic,
                "keywords": self.digest.keywords,
                "abstract_zh": self.digest.abstract_zh,
                "one_sentence_takeaway": self.digest.one_sentence_takeaway,
                "background": self.digest.background,
                "problem": self.digest.problem,
                "method": self.digest.method,
                "experiment_setup": self.digest.experiment_setup,
                "findings": self.digest.findings,
                "limitations": self.digest.limitations,
                "relevance": self.digest.relevance,
                "improvement_ideas": self.digest.improvement_ideas,
            },
            "stored_at": self.stored_at,
            "pdf_path": self.pdf_path,
            "md_path": self.md_path,
            "metadata_path": self.metadata_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StoredPaper":
        paper_data = dict(data["paper"])
        paper_data.setdefault("paper_id", paper_data.get("arxiv_id") or paper_data.get("openreview_id") or paper_data.get("title", "untitled"))
        paper_data.setdefault("source_primary", "arxiv" if paper_data.get("arxiv_id") else ("openreview" if paper_data.get("openreview_id") else "scholar"))
        paper_data.setdefault("entry_url", paper_data.get("entry_id", ""))
        paper_data.setdefault("entry_id", paper_data.get("entry_url", ""))
        paper_data.setdefault("pdf_url", "")
        paper_data.setdefault("primary_category", "")
        paper_data.setdefault("categories", [])
        paper_data.setdefault("arxiv_id", "")
        paper_data.setdefault("versioned_id", "")
        paper_data.setdefault("openreview_id", "")
        paper_data.setdefault("openreview_forum_id", "")
        paper_data.setdefault("doi", "")
        paper_data.setdefault("scholar_url", "")
        paper_data.setdefault("openreview_url", "")
        venue_data = paper_data.get("venue") or {}
        if not isinstance(venue_data, dict):
            venue_data = {}
        paper_data["venue"] = VenueInfo(
            name=str(venue_data.get("name", "") or ""),
            kind=str(venue_data.get("kind", "") or ""),
            year=int(venue_data["year"]) if venue_data.get("year") not in ("", None) else None,
        )
        citation_count = paper_data.get("citation_count")
        try:
            paper_data["citation_count"] = int(citation_count) if citation_count not in ("", None) else None
        except (TypeError, ValueError):
            paper_data["citation_count"] = None
        paper_data.setdefault("citation_source", "")
        paper_data.setdefault("citation_updated_at", "")
        paper = Paper(**paper_data)
        digest_data = data["digest"]
        digest = PaperDigest(
            major_topic=digest_data.get("major_topic", "未分类方向"),
            minor_topic=digest_data.get("minor_topic", "待整理子方向"),
            keywords=list(digest_data.get("keywords", [])),
            abstract_zh=digest_data.get("abstract_zh", ""),
            one_sentence_takeaway=digest_data.get("one_sentence_takeaway", ""),
            background=digest_data.get("background", ""),
            problem=digest_data.get("problem", ""),
            method=digest_data.get("method", ""),
            experiment_setup=digest_data.get("experiment_setup", ""),
            findings=list(digest_data.get("findings", [])),
            limitations=list(digest_data.get("limitations", [])),
            relevance=digest_data.get("relevance", ""),
            improvement_ideas=list(digest_data.get("improvement_ideas", [])),
        )
        return cls(
            paper=paper,
            digest=digest,
            stored_at=data["stored_at"],
            pdf_path=data["pdf_path"],
            md_path=data["md_path"],
            metadata_path=data["metadata_path"],
        )


@dataclass(slots=True)
class RunResult:
    plan: RequestPlan
    new_papers: list[StoredPaper]
    reused_papers: list[StoredPaper]
    related_papers: list[StoredPaper]
    report_markdown: str
    report_path: str
