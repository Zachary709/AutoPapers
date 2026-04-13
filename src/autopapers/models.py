from __future__ import annotations

from dataclasses import dataclass, field


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
    arxiv_id: str
    versioned_id: str
    title: str
    abstract: str
    authors: list[str]
    published: str
    updated: str
    entry_id: str
    pdf_url: str
    primary_category: str
    categories: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PaperDigest:
    major_topic: str
    minor_topic: str
    keywords: list[str]
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
                "arxiv_id": self.paper.arxiv_id,
                "versioned_id": self.paper.versioned_id,
                "title": self.paper.title,
                "abstract": self.paper.abstract,
                "authors": self.paper.authors,
                "published": self.paper.published,
                "updated": self.paper.updated,
                "entry_id": self.paper.entry_id,
                "pdf_url": self.paper.pdf_url,
                "primary_category": self.paper.primary_category,
                "categories": self.paper.categories,
            },
            "digest": {
                "major_topic": self.digest.major_topic,
                "minor_topic": self.digest.minor_topic,
                "keywords": self.digest.keywords,
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
        paper = Paper(**data["paper"])
        digest_data = data["digest"]
        digest = PaperDigest(
            major_topic=digest_data.get("major_topic", "未分类方向"),
            minor_topic=digest_data.get("minor_topic", "待整理子方向"),
            keywords=list(digest_data.get("keywords", [])),
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
