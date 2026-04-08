# AutoPapers Design

## Goal

Build a Python harness that can route research requests, search arXiv, summarize papers, store them in a two-level topic hierarchy, and reuse local papers in future outputs.

## Chosen architecture

The implementation is split into five layers:

1. `cli`: parses commands and loads runtime settings.
2. `llm`: talks to MiniMax and turns free-form requests or papers into structured outputs.
3. `arxiv`: searches arXiv, resolves IDs or URLs, and downloads PDFs.
4. `library`: stores papers, maintains an index, generates Markdown notes, and refreshes folder summaries.
5. `workflows`: orchestrates the end-to-end request lifecycle.

## Key decisions

- The MiniMax key is loaded from `.env` or environment variables, not committed into source code.
- Each paper gets three artifacts: `pdf`, `md`, and `metadata.json`.
- Major-topic and minor-topic folders each keep a `README.md` summary generated from the local index.
- Local paper reuse is handled through lightweight lexical retrieval on titles, abstracts, topics, and keywords.
- PDF extraction is optional. If `pypdf` is not installed or parsing fails, summarization falls back to abstract-driven synthesis.

## Tradeoffs

- Retrieval is intentionally simple and dependency-light. It is easier to maintain and can later be swapped for embeddings.
- Folder summaries are deterministic templates, which keeps them cheap and predictable.
- LLM use is concentrated in request planning and per-paper digestion, which keeps the harness efficient while preserving flexible routing.

