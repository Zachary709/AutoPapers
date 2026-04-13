from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autopapers.config import Settings
from autopapers.workflows import AutoPapersAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Re-analyze local AutoPapers library entries from PDFs.")
    parser.add_argument("--limit", type=int, default=None, help="Only re-analyze the most recent N papers")
    parser.add_argument("--arxiv-id", action="append", default=None, help="Restrict re-analysis to specific arXiv IDs")
    parser.add_argument(
        "--download-missing-pdf",
        action="store_true",
        help="Attempt to download the PDF when the local copy is missing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env(REPO_ROOT)

    if not settings.api_key:
        parser.error("MINIMAX_API_KEY is required. Copy .env.example to .env and fill it in.")

    agent = AutoPapersAgent(settings)
    updated = agent.reanalyze_library(
        arxiv_ids=args.arxiv_id,
        limit=args.limit,
        download_missing_pdf=args.download_missing_pdf,
        notice_callback=print,
    )
    print(f"Re-analyzed {len(updated)} paper(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
