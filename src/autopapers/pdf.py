from __future__ import annotations

from io import BytesIO

from autopapers.utils import normalize_whitespace, truncate_text


class PDFTextExtractor:
    def __init__(self, max_pages: int = 8, max_chars: int = 20_000) -> None:
        self.max_pages = max_pages
        self.max_chars = max_chars

    def extract(self, pdf_bytes: bytes) -> str:
        if not pdf_bytes:
            return ""

        try:
            from pypdf import PdfReader
        except ImportError:
            return ""

        try:
            reader = PdfReader(BytesIO(pdf_bytes))
        except Exception:
            return ""

        text_chunks: list[str] = []
        current_length = 0
        for page in reader.pages[: self.max_pages]:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                continue
            normalized = normalize_whitespace(page_text)
            if not normalized:
                continue
            text_chunks.append(normalized)
            current_length += len(normalized)
            if current_length >= self.max_chars:
                break

        return truncate_text(" ".join(text_chunks), self.max_chars)

