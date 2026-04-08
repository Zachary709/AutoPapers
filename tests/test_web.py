from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import json
import unittest
import urllib.request

from autopapers.config import Settings
from autopapers.web.server import build_server


class WebServerTests(unittest.TestCase):
    def test_server_serves_index_and_library_api(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            settings = Settings(
                repo_root=root,
                api_key="",
                model="MiniMax-M2.7",
                api_url="https://api.minimaxi.com/v1/text/chatcompletion_v2",
                library_root=root / "library",
                reports_root=root / "reports",
                default_max_results=5,
                request_timeout=30,
                pdf_max_pages=4,
                pdf_max_chars=4000,
                web_host="127.0.0.1",
                web_port=0,
            )
            server, app = build_server(settings, host="127.0.0.1", port=0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address

            try:
                with urllib.request.urlopen(f"http://{host}:{port}/", timeout=5) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("AutoPapers Studio", html)

                with urllib.request.urlopen(f"http://{host}:{port}/api/library", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("app", payload)
                self.assertIn("library", payload)
                self.assertEqual(payload["library"]["stats"]["paper_count"], 0)
                log_path = settings.reports_root / "web-serve.log"
                self.assertTrue(log_path.exists())
                self.assertIn("Web app initialized", log_path.read_text(encoding="utf-8"))
            finally:
                app.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
