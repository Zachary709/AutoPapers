from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import json
import time
import unittest
import urllib.request

from autopapers.config import Settings
from autopapers.models import Paper, PaperDigest
from autopapers.web.jobs import TaskManager
from autopapers.web.server import build_server
from autopapers.web.test_workers import job_test_worker


def make_paper() -> Paper:
    return Paper(
        paper_id="2401.12345",
        source_primary="arxiv",
        arxiv_id="2401.12345",
        versioned_id="2401.12345v1",
        title="Web Test Paper",
        abstract="A test paper.",
        authors=["Alice"],
        published="2026-01-01T00:00:00Z",
        updated="2026-01-02T00:00:00Z",
        entry_id="http://arxiv.org/abs/2401.12345v1",
        entry_url="http://arxiv.org/abs/2401.12345v1",
        pdf_url="http://arxiv.org/pdf/2401.12345v1",
        primary_category="cs.AI",
        categories=["cs.AI"],
    )


def make_digest() -> PaperDigest:
    return PaperDigest(
        major_topic="Agents",
        minor_topic="Evaluation",
        keywords=["agents"],
        one_sentence_takeaway="A concise takeaway.",
    )


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
                self.assertIn("katex.min.css", html)
                self.assertIn("auto-render.min.js", html)
                self.assertIn('id="jumpLatestButton"', html)
                self.assertIn('id="chatComposerSplitter"', html)
                self.assertIn('id="composerCollapseButton"', html)
                self.assertIn('id="settingsButton"', html)
                self.assertIn('id="settingsModal"', html)
                self.assertIn('id="settingsForm"', html)
                self.assertIn('id="profileList"', html)
                self.assertIn('id="settingsProfileName"', html)
                self.assertIn('id="directorySearchToggle"', html)
                self.assertIn('id="directorySearchPanel"', html)
                self.assertIn('/assets/js/bootstrap.js', html)
                self.assertNotIn("左侧切一级方向，上方切二级方向，下方像文件列表一样浏览论文。", html)

                with urllib.request.urlopen(f"http://{host}:{port}/assets/js/bootstrap.js", timeout=5) as response:
                    bootstrap_js = response.read().decode("utf-8")
                self.assertIn('from "./api.js"', bootstrap_js)
                self.assertIn("DOMContentLoaded", bootstrap_js)

                with urllib.request.urlopen(f"http://{host}:{port}/api/library", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("app", payload)
                self.assertIn("library", payload)
                self.assertIn("openreview", payload["app"])
                self.assertEqual(payload["library"]["stats"]["paper_count"], 0)
                log_path = settings.reports_root / "web-serve.log"
                self.assertTrue(log_path.exists())
                self.assertIn("Web app initialized", log_path.read_text(encoding="utf-8"))
            finally:
                app.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_refresh_metadata_endpoint_returns_updated_detail(self) -> None:
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
            app.agent.library.upsert_paper(make_paper(), make_digest(), b"%PDF-1.4 fake", [])

            def refresh_metadata(paper_id: str):
                paper = make_paper()
                paper.venue.name = "ICLR"
                paper.venue.kind = "conference"
                paper.venue.year = 2026
                paper.citation_count = 42
                paper.citation_source = "google_scholar"
                paper.citation_updated_at = "2026-04-13T00:00:00+00:00"
                record = app.agent.library.upsert_paper(paper, make_digest(), b"%PDF-1.4 fake", [])
                return {
                    "record": record,
                    "refresh": {
                        "status": "updated",
                        "message": "已刷新元数据：收录信息、引用量。",
                        "changed_fields": ["收录信息", "引用量"],
                        "updated_at": "2026-04-13T00:00:00+00:00",
                        "sources": [
                            {"source": "OpenReview", "status": "unchanged", "message": "未返回新的收录或链接信息。"},
                            {"source": "Google Scholar", "status": "updated", "message": "补充了收录信息、引用量。"},
                        ],
                    },
                }

            app.agent.refresh_paper_metadata = refresh_metadata

            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address

            try:
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/papers/2401.12345/refresh-metadata",
                    method="POST",
                    data=b"",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["detail"]["summary"]["paper_id"], "2401.12345")
                self.assertEqual(payload["detail"]["summary"]["venue"]["name"], "ICLR")
                self.assertEqual(payload["detail"]["summary"]["citation_count"], 42)
                self.assertEqual(payload["detail"]["metadata_refresh"]["status"], "updated")
            finally:
                app.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_library_api_stays_responsive_while_task_is_running(self) -> None:
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
            app.jobs.close()
            app.jobs = TaskManager(job_test_worker, max_workers=1, event_callback=app._log_job_event)

            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address

            try:
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/tasks",
                    method="POST",
                    data=json.dumps({"prompt": "sleep"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    job_payload = json.loads(response.read().decode("utf-8"))
                job_id = job_payload["job"]["id"]
                for _ in range(100):
                    with urllib.request.urlopen(f"http://{host}:{port}/api/tasks/{job_id}", timeout=5) as response:
                        current = json.loads(response.read().decode("utf-8"))["job"]
                    if current["status"] == "running":
                        break
                    time.sleep(0.02)
                self.assertEqual(current["status"], "running")

                start = time.monotonic()
                with urllib.request.urlopen(f"http://{host}:{port}/api/library", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                elapsed = time.monotonic() - start
                self.assertLess(elapsed, 1.0)
                self.assertIn("library", payload)
            finally:
                app.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_task_cancel_endpoint_stops_running_job(self) -> None:
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
            app.jobs.close()
            app.jobs = TaskManager(job_test_worker, max_workers=1, event_callback=app._log_job_event)

            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address

            try:
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/tasks",
                    method="POST",
                    data=json.dumps({"prompt": "blocking-progress"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    job_payload = json.loads(response.read().decode("utf-8"))
                job_id = job_payload["job"]["id"]

                for _ in range(100):
                    with urllib.request.urlopen(f"http://{host}:{port}/api/tasks/{job_id}", timeout=5) as response:
                        current = json.loads(response.read().decode("utf-8"))["job"]
                    if current["status"] == "running":
                        break
                    time.sleep(0.02)
                self.assertEqual(current["status"], "running")

                cancel_request = urllib.request.Request(
                    f"http://{host}:{port}/api/tasks/{job_id}/cancel",
                    method="POST",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(cancel_request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["job"]["id"], job_id)
                self.assertTrue(payload["job"]["cancel_requested"])

                for _ in range(100):
                    with urllib.request.urlopen(f"http://{host}:{port}/api/tasks/{job_id}", timeout=5) as response:
                        current = json.loads(response.read().decode("utf-8"))["job"]
                    if current["status"] == "cancelled":
                        break
                    time.sleep(0.02)
                else:
                    self.fail("job did not cancel in time")

                self.assertEqual(current["error"], "用户手动停止任务。")
            finally:
                app.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_settings_api_profile_crud(self) -> None:
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
                base = f"http://{host}:{port}"

                # GET settings returns empty profiles
                with urllib.request.urlopen(f"{base}/api/settings", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("profiles", payload)
                self.assertEqual(len(payload["profiles"]), 0)

                # POST save a profile
                save_body = json.dumps({
                    "action": "save",
                    "profile": {
                        "name": "Test Config",
                        "api_key": "sk-test-12345678",
                        "model": "TestModel",
                        "api_url": "https://api.test.com/v1",
                        "network_proxy_url": "",
                    },
                }).encode("utf-8")
                request = urllib.request.Request(
                    f"{base}/api/settings", method="POST",
                    data=save_body, headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("saved_id", payload)
                saved_id = payload["saved_id"]
                self.assertTrue(saved_id)
                self.assertEqual(payload["profiles_data"]["active_profile"], saved_id)
                self.assertTrue(payload["app"]["api_key_configured"])

                # GET settings shows the saved profile
                with urllib.request.urlopen(f"{base}/api/settings", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertIn(saved_id, payload["profiles"])
                self.assertEqual(payload["profiles"][saved_id]["model"], "TestModel")
                self.assertNotEqual(payload["profiles"][saved_id]["api_key_masked"], "sk-test-12345678")

                # Update the same profile without re-entering API key
                update_body = json.dumps({
                    "action": "save",
                    "profile_id": saved_id,
                    "profile": {
                        "name": "Test Config Updated",
                        "api_key": "",
                        "model": "TestModelV2",
                        "api_url": "https://api.test.com/v2",
                        "network_proxy_url": "http://127.0.0.1:7890",
                    },
                }).encode("utf-8")
                update_request = urllib.request.Request(
                    f"{base}/api/settings", method="POST",
                    data=update_body, headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(update_request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["saved_id"], saved_id)
                self.assertEqual(payload["app"]["model"], "TestModelV2")

                # Save a second profile
                save_body2 = json.dumps({
                    "action": "save",
                    "profile": {
                        "name": "Other Config",
                        "api_key": "sk-other-key",
                        "model": "OtherModel",
                        "api_url": "https://api.other.com/v1",
                    },
                }).encode("utf-8")
                request2 = urllib.request.Request(
                    f"{base}/api/settings", method="POST",
                    data=save_body2, headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request2, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                second_id = payload["saved_id"]
                self.assertNotEqual(saved_id, second_id)

                # Activate the first profile
                activate_body = json.dumps({
                    "action": "activate",
                    "profile_id": saved_id,
                }).encode("utf-8")
                request3 = urllib.request.Request(
                    f"{base}/api/settings", method="POST",
                    data=activate_body, headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request3, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["active_profile"], saved_id)
                self.assertEqual(payload["app"]["model"], "TestModelV2")
                self.assertNotEqual(
                    payload["profiles_data"]["profiles"][saved_id]["api_key_masked"],
                    "",
                )
                self.assertEqual(
                    payload["profiles_data"]["profiles"][saved_id]["network_proxy_url"],
                    "http://127.0.0.1:7890",
                )

                # Delete the second profile
                delete_body = json.dumps({
                    "action": "delete",
                    "profile_id": second_id,
                }).encode("utf-8")
                request4 = urllib.request.Request(
                    f"{base}/api/settings", method="POST",
                    data=delete_body, headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request4, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("profiles_data", payload)
                self.assertNotIn(second_id, payload["profiles_data"]["profiles"])

                # Unknown action returns 400
                bad_body = json.dumps({"action": "bogus"}).encode("utf-8")
                bad_request = urllib.request.Request(
                    f"{base}/api/settings", method="POST",
                    data=bad_body, headers={"Content-Type": "application/json"},
                )
                try:
                    urllib.request.urlopen(bad_request, timeout=5)
                    self.fail("Expected 400 for unknown action")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 400)
            finally:
                app.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
