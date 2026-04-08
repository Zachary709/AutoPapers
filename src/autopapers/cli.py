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

    if not settings.api_key:
        parser.error("MINIMAX_API_KEY is required. Copy .env.example to .env and fill it in.")

    try:
        result = agent.run(
            args.request,
            max_results=args.max_results,
            refresh_existing=args.refresh_existing,
        )
    except MiniMaxError as exc:
        print(f"MiniMax request failed: {exc}", file=sys.stderr)
        return 2

    print(result.report_markdown)
    print(f"\nSaved report: {result.report_path}")
    return 0
