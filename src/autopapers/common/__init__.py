from autopapers.common.atomic_io import write_bytes_atomic, write_text_atomic
from autopapers.common.paper_identity import (
    make_scholar_paper_id,
    paper_identity_key,
    title_similarity,
    unique_by_arxiv_id,
    unique_by_paper_identity,
    venue_or_published_year,
    word_similarity,
)
from autopapers.common.reference_parsing import (
    extract_paper_reference_text,
    extract_paper_reference_texts,
    parse_arxiv_id,
    parse_openreview_id,
)
from autopapers.common.text_normalization import (
    normalize_title_key,
    normalize_whitespace,
    sanitize_path_component,
    tokenize,
    truncate_text,
    utc_now_iso,
)

__all__ = [
    "extract_paper_reference_text",
    "extract_paper_reference_texts",
    "make_scholar_paper_id",
    "normalize_title_key",
    "normalize_whitespace",
    "paper_identity_key",
    "parse_arxiv_id",
    "parse_openreview_id",
    "sanitize_path_component",
    "title_similarity",
    "tokenize",
    "truncate_text",
    "unique_by_arxiv_id",
    "unique_by_paper_identity",
    "utc_now_iso",
    "venue_or_published_year",
    "word_similarity",
    "write_bytes_atomic",
    "write_text_atomic",
]
