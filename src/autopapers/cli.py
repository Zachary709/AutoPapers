from __future__ import annotations

import argparse
import sys

from autopapers.config import Settings
from autopapers.llm.minimax import MiniMaxError
from autopapers.web import serve as serve_web
from autopapers.workflows import AutoPapersAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AutoPapers research harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Handle a research request end-to-end")
    run_parser.add_argument("request", help="Natural-language user request")
    run_parser.add_argument("--max-results", type=int, default=None, help="Override the default arXiv result count")
    run_parser.add_argument(
        "--refresh-existing",
        action="store_true",
        help="Re-download and re-summarize papers that already exist in the local library",
    )

    serve_parser = subparsers.add_parser("serve", help="Launch the local web app")
    serve_parser.add_argument("--host", default=None, help="Bind host for the web server")
    serve_parser.add_argument("--port", type=int, default=None, help="Bind port for the web server")

    subparsers.add_parser("rebuild-summaries", help="Rebuild folder summaries from the local index")
    subparsers.add_parser("normalize-topics", help="Normalize local paper topics into the canonical taxonomy")
    reanalyze_parser = subparsers.add_parser("reanalyze-library", help="Re-analyze papers from local PDFs")
    reanalyze_parser.add_argument("--limit", type=int, default=None, help="Only re-analyze the most recent N papers")
    reanalyze_parser.add_argument("--paper-id", action="append", default=None, help="Restrict re-analysis to specific paper IDs")
    reanalyze_parser.add_argument("--arxiv-id", action="append", default=None, help="Restrict re-analysis to specific arXiv IDs")
    reanalyze_parser.add_argument(
        "--download-missing-pdf",
        action="store_true",
        help="Attempt to download the PDF when the local copy is missing",
    )
    reanalyze_parser.add_argument(
        "--format-only",
        action="store_true",
        help="Only run the final format-tightening step on existing digests",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()

    if args.command == "serve":
        serve_web(settings, host=args.host, port=args.port)
        return 0

    agent = AutoPapersAgent(settings)

    if args.command == "rebuild-summaries":
        agent.rebuild_summaries()
        print("Rebuilt library summaries.")
        return 0

    if args.command == "normalize-topics":
        updated = agent.normalize_library_topics(notice_callback=print)
        print(f"Normalized topics for {len(updated)} paper(s).")
        return 0

    if args.command == "reanalyze-library":
        if not settings.api_key:
            parser.error("MINIMAX_API_KEY is required. Copy .env.example to .env and fill it in.")
        updated = agent.reanalyze_library(
            paper_ids=args.paper_id,
            arxiv_ids=args.arxiv_id,
            limit=args.limit,
            download_missing_pdf=args.download_missing_pdf,
            format_only=args.format_only,
            notice_callback=print,
        )
        action = "Format-updated" if args.format_only else "Re-analyzed"
        print(f"{action} {len(updated)} paper(s).")
        return 0

    if not settings.api_key:
        parser.error("MINIMAX_API_KEY is required. Copy .env.example to .env and fill it in.")

    try:
        result = agent.run(
            args.request,
            max_results=args.max_results,
            refresh_existing=args.refresh_existing,
        )
    except MiniMaxError as exc:
        print(f"LLM request failed: {exc}", file=sys.stderr)
        return 2

    print(result.report_markdown)
    print(f"\nSaved report: {result.report_path}")
    return 0
