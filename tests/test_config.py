from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from autopapers.config import Settings


class ConfigTests(unittest.TestCase):
    def test_from_env_reads_network_proxy_url(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "MINIMAX_API_KEY=test-key",
                        "AUTOPAPERS_HTTP_PROXY=http://127.0.0.1:7890",
                    ]
                ),
                encoding="utf-8",
            )

            settings = Settings.from_env(root)

            self.assertEqual(settings.network_proxy_url, "http://127.0.0.1:7890")

    def test_from_env_uses_expanded_pdf_defaults(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            settings = Settings.from_env(root)

            self.assertEqual(settings.pdf_max_pages, 18)
            self.assertEqual(settings.pdf_max_chars, 45000)
