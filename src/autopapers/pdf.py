from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import re

from autopapers.utils import normalize_whitespace, truncate_text

SECTION_ALIASES = {
    "abstract": {"abstract"},
    "introduction": {"introduction"},
    "method": {"approach", "approaches", "method", "methods", "methodology", "model", "models", "framework", "frameworks", "algorithm", "algorithms", "technical approach", "problem formulation", "preliminaries", "proposed method"},
    "experiments": {"experiment", "experiments", "experimental setup", "experimental settings", "evaluation", "evaluations", "results", "empirical analysis", "implementation details", "benchmark", "benchmarks", "ablation", "ablations"},
    "conclusion": {"conclusion", "conclusions", "discussion", "discussions", "future work", "limitations"},
    "references": {"acknowledgements", "acknowledgments", "appendix", "appendices", "bibliography", "references", "supplementary material", "supplementary materials"},
}
MATH_LINE_PATTERN = re.compile(r"(?:=|≤|≥|∑|∞|≈|≠|λ|θ|β|α|δ|∇|log|exp|argmax|argmin|softmax|pass@k)", re.IGNORECASE)


@dataclass(slots=True)
class ExtractedPaperContent:
    abstract: str = ""
    introduction: str = ""
    method: str = ""
    experiments: str = ""
    conclusion: str = ""
    raw_body: str = ""
    equations: list[str] = field(default_factory=list)
    references_trimmed: bool = False

    def combined_context(self, max_chars: int) -> str:
        blocks: list[str] = []
        for title, body in (("Abstract", self.abstract), ("Introduction", self.introduction), ("Method", self.method), ("Experiments", self.experiments), ("Conclusion", self.conclusion)):
            normalized = normalize_whitespace(body)
            if normalized:
                blocks.append(f"[{title}]\n{normalized}")
        if self.equations:
            blocks.append("[Recognizable Equations]\n" + "\n".join(f"- {item}" for item in self.equations))
        if not blocks and self.raw_body:
            blocks.append(f"[Body]\n{normalize_whitespace(self.raw_body)}")
        return truncate_text("\n\n".join(blocks), max_chars) if blocks else ""

    def has_substantial_text(self) -> bool:
        return any(normalize_whitespace(value) for value in (self.abstract, self.introduction, self.method, self.experiments, self.conclusion, self.raw_body))


class PDFTextExtractor:
    def __init__(self, max_pages: int = 18, max_chars: int = 45_000) -> None:
        self.max_pages = max_pages
        self.max_chars = max_chars

    def extract(self, pdf_bytes: bytes) -> str:
        return self.extract_structured(pdf_bytes).combined_context(self.max_chars)

    def extract_structured(self, pdf_bytes: bytes) -> ExtractedPaperContent:
        if not pdf_bytes:
            return ExtractedPaperContent()
        try:
            from pypdf import PdfReader
        except ImportError:
            return ExtractedPaperContent()
        try:
            reader = PdfReader(BytesIO(pdf_bytes))
        except Exception:
            return ExtractedPaperContent()

        page_lines: list[list[str]] = []
        for page in reader.pages[: self.max_pages]:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                continue
            lines = self._clean_page_lines(page_text)
            if lines:
                page_lines.append(lines)
        return self._build_content_from_pages(page_lines) if page_lines else ExtractedPaperContent()

    def extract_from_text(self, raw_text: str) -> ExtractedPaperContent:
        lines = self._clean_page_lines(raw_text)
        return self._build_content_from_pages([lines]) if lines else ExtractedPaperContent()
    def _build_content_from_pages(self, page_lines: list[list[str]]) -> ExtractedPaperContent:
        filtered_pages = self._strip_repeated_headers_and_footers(page_lines)
        flat_lines = [line for page in filtered_pages for line in page]
        if not flat_lines:
            return ExtractedPaperContent()
        flat_lines, references_trimmed = self._trim_back_matter(flat_lines)
        flat_lines = self._merge_hyphenated_lines(flat_lines)
        sections = self._segment_sections(flat_lines)
        equations = self._extract_equations(sections.get("method", "") or sections.get("raw_body", ""))
        return ExtractedPaperContent(
            abstract=truncate_text(sections.get("abstract", ""), 4_000),
            introduction=truncate_text(sections.get("introduction", ""), 8_000),
            method=truncate_text(sections.get("method", ""), 16_000),
            experiments=truncate_text(sections.get("experiments", ""), 14_000),
            conclusion=truncate_text(sections.get("conclusion", ""), 5_000),
            raw_body=truncate_text(sections.get("raw_body", ""), self.max_chars),
            equations=equations[:8],
            references_trimmed=references_trimmed,
        )

    @staticmethod
    def _merge_hyphenated_lines(lines: list[str]) -> list[str]:
        merged: list[str] = []
        for line in lines:
            if merged and re.search(r"[A-Za-z]-$", merged[-1]) and re.match(r"^[a-z][A-Za-z-]*\b", line):
                merged[-1] = merged[-1][:-1] + line
                continue
            merged.append(line)
        return merged

    @staticmethod
    def _clean_page_lines(page_text: str) -> list[str]:
        lines: list[str] = []
        for raw_line in page_text.splitlines():
            normalized = normalize_whitespace(raw_line)
            if not normalized or PDFTextExtractor._is_noise_line(normalized):
                continue
            lines.append(normalized)
        return lines

    @staticmethod
    def _is_noise_line(line: str) -> bool:
        if len(line) <= 2 and not any(ch.isalpha() for ch in line):
            return True
        if re.fullmatch(r"\d+", line):
            return True
        if line.lower().startswith("arxiv:"):
            return True
        if len(line) < 5 and sum(ch.isdigit() for ch in line) >= 2:
            return True
        return False

    @staticmethod
    def _strip_repeated_headers_and_footers(page_lines: list[list[str]]) -> list[list[str]]:
        header_counts: dict[str, int] = {}
        footer_counts: dict[str, int] = {}
        for lines in page_lines:
            for candidate in lines[:2]:
                header_counts[candidate] = header_counts.get(candidate, 0) + 1
            for candidate in lines[-2:]:
                footer_counts[candidate] = footer_counts.get(candidate, 0) + 1
        repeated_headers = {line for line, count in header_counts.items() if count >= 3}
        repeated_footers = {line for line, count in footer_counts.items() if count >= 3}
        filtered_pages: list[list[str]] = []
        for lines in page_lines:
            filtered_pages.append([line for index, line in enumerate(lines) if not ((index < 2 and line in repeated_headers) or (index >= len(lines) - 2 and line in repeated_footers))])
        return filtered_pages

    @staticmethod
    def _trim_back_matter(lines: list[str]) -> tuple[list[str], bool]:
        for index, line in enumerate(lines):
            heading = PDFTextExtractor._match_section_heading(line)
            if heading == "references" and index > 40:
                return lines[:index], True
        return lines, False

    @staticmethod
    def _segment_sections(lines: list[str]) -> dict[str, str]:
        sections: dict[str, list[str]] = {"abstract": [], "introduction": [], "method": [], "experiments": [], "conclusion": [], "raw_body": []}
        current_section = "raw_body"
        seen_any_heading = False
        for line in lines:
            heading = PDFTextExtractor._match_section_heading(line)
            if heading in {"abstract", "introduction", "method", "experiments", "conclusion"}:
                current_section = heading
                seen_any_heading = True
                continue
            sections[current_section].append(line)
            sections["raw_body"].append(line)
        if not seen_any_heading:
            joined = normalize_whitespace(" ".join(lines))
            return {"abstract": "", "introduction": "", "method": "", "experiments": "", "conclusion": "", "raw_body": joined}
        return {key: normalize_whitespace(" ".join(value)) for key, value in sections.items()}

    @staticmethod
    def _match_section_heading(line: str) -> str | None:
        normalized = normalize_whitespace(line)
        if not normalized:
            return None
        candidate = re.sub(r"^(?:\d+(?:\.\d+)*\s*[.)]?\s*)", "", normalized).strip(":- ")
        lowered = candidate.casefold()
        if len(lowered) > 60:
            return None
        for section, aliases in SECTION_ALIASES.items():
            if lowered in aliases:
                return section
        return None

    @staticmethod
    def _extract_equations(text: str) -> list[str]:
        equations: list[str] = []
        seen: set[str] = set()
        for raw_line in text.split(". "):
            candidate = normalize_whitespace(raw_line)
            if len(candidate) < 12 or len(candidate) > 220 or not MATH_LINE_PATTERN.search(candidate) or candidate in seen:
                continue
            seen.add(candidate)
            equations.append(candidate)
        return equations
