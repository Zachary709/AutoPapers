from __future__ import annotations

from dataclasses import asdict
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from threading import Lock
from typing import Callable
from urllib.parse import quote, unquote, urlparse

from autopapers.config import Settings
from autopapers.utils import utc_now_iso
from autopapers.workflows import AutoPapersAgent
from autopapers.web.jobs import TaskManager


class FileEventLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def info(self, message: str) -> None:
        self._write("INFO", message)

    def error(self, message: str) -> None:
        self._write("ERROR", message)

    def _write(self, level: str, message: str) -> None:
        line = f"[{utc_now_iso()}] {level} {message}\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)


def _serialize_stored_paper(record, repo_root: Path) -> dict:
    pdf_path = repo_root / record.pdf_path
    return {
        "paper_id": record.paper.paper_id,
        "arxiv_id": record.paper.arxiv_id,
        "versioned_id": record.paper.versioned_id,
        "source_primary": record.paper.source_primary,
        "title": record.paper.title,
        "authors": record.paper.authors,
        "published": record.paper.published,
        "stored_at": record.stored_at,
        "major_topic": record.digest.major_topic,
        "minor_topic": record.digest.minor_topic,
        "takeaway": record.digest.one_sentence_takeaway,
        "keywords": record.digest.keywords,
        "pdf_available": pdf_path.exists(),
        "venue": asdict(record.paper.venue),
        "citation_count": record.paper.citation_count,
        "citation_updated_at": record.paper.citation_updated_at,
        "links": {
            "entry": record.paper.entry_url or record.paper.entry_id,
            "scholar": record.paper.scholar_url,
            "openreview": record.paper.openreview_url,
        },
    }


def _run_task_process_entry(
    repo_root: Path,
    prompt: str,
    refresh_existing: bool,
    max_results: int | None,
    reporter,
) -> dict:
    settings = Settings.from_env(repo_root)
    agent = AutoPapersAgent(settings)
    result = agent.run(
        prompt,
        max_results=max_results,
        refresh_existing=refresh_existing,
        notice_callback=reporter.notice,
        timeline_callback=reporter.timeline,
        progress_callback=reporter.progress,
        confirmation_callback=reporter.confirm,
        debug_callback=reporter.debug,
    )
    return {
        "plan": asdict(result.plan),
        "report_markdown": result.report_markdown,
        "report_path": result.report_path,
        "new_papers": [_serialize_stored_paper(item, settings.repo_root) for item in result.new_papers],
        "reused_papers": [_serialize_stored_paper(item, settings.repo_root) for item in result.reused_papers],
        "related_papers": [_serialize_stored_paper(item, settings.repo_root) for item in result.related_papers],
        "library": agent.library.list_tree(),
    }


class AutoPapersWebApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.agent = AutoPapersAgent(settings)
        self.static_root = Path(__file__).resolve().parent / "static"
        self.logger = FileEventLogger(settings.reports_root / "web-serve.log")
        self.logger.info(
            f"Web app initialized | model={settings.model} | host={settings.web_host}:{settings.web_port}"
        )
        self.jobs = TaskManager(
            partial(_run_task_process_entry, settings.repo_root),
            max_workers=1,
            event_callback=self._log_job_event,
        )

    def close(self) -> None:
        self.logger.info("Web app shutting down")
        self.jobs.close()

    def get_library_payload(self) -> dict:
        openreview_status = self.agent.openreview.auth_status()
        library = self.agent.library.list_tree()
        return {
            "app": {
                "api_key_configured": bool(self.settings.api_key),
                "model": self.settings.model,
                "web_host": self.settings.web_host,
                "web_port": self.settings.web_port,
                "openreview": openreview_status,
            },
            "library": library,
        }

    def get_settings_payload(self) -> dict:
        openreview_status = self.agent.openreview.auth_status()
        profiles = self.settings.list_profiles()
        return {
            **profiles,
            "openreview": openreview_status,
        }

    def handle_settings_action(self, payload: dict) -> dict:
        action = str(payload.get("action", "")).strip()
        if action == "save":
            result = self.settings.save_profile(
                payload.get("profile_id") or None,
                payload.get("profile", {}),
            )
        elif action == "delete":
            result = self.settings.delete_profile(
                str(payload.get("profile_id", "")).strip(),
            )
        elif action == "activate":
            result = self.settings.activate_profile(
                str(payload.get("profile_id", "")).strip(),
            )
        else:
            return {"error": "unknown action"}
        self.agent.rebuild_planner()
        return {
            **result,
            "profiles_data": self.settings.list_profiles(),
            "app": self.get_library_payload()["app"],
        }

    def get_paper_detail(self, paper_id: str) -> dict | None:
        detail = self.agent.library.get_paper_detail(paper_id)
        return self._decorate_paper_detail(paper_id, detail)

    def _decorate_paper_detail(self, paper_id: str, detail: dict | None) -> dict | None:
        if detail is None:
            return None
        detail["download_urls"] = {
            "pdf": f"/api/papers/{quote(paper_id, safe='')}/pdf" if detail["flags"]["pdf_exists"] else None,
            "markdown": f"/api/papers/{quote(paper_id, safe='')}/markdown",
        }
        return detail

    def delete_paper(self, paper_id: str) -> dict | None:
        deleted = self.agent.library.delete_paper(paper_id)
        payload = self.get_library_payload() if deleted else None
        return payload

    def refresh_paper_metadata(self, paper_id: str) -> dict | None:
        refreshed = self.agent.refresh_paper_metadata(paper_id)
        if refreshed is None:
            return None
        record = refreshed["record"]
        detail = self.agent.library.get_paper_detail(record.paper.paper_id)
        detail = self._decorate_paper_detail(record.paper.paper_id, detail)
        detail["metadata_refresh"] = refreshed["refresh"]
        library_payload = self.get_library_payload()
        return {
            "detail": detail,
            "library": library_payload["library"],
            "app": library_payload["app"],
        }

    def get_pdf_path(self, paper_id: str) -> Path | None:
        record = self.agent.library.get_by_paper_id(paper_id)
        if record is None:
            return None
        path = self.settings.repo_root / record.pdf_path
        return path if path.exists() else None

    def get_markdown_path(self, paper_id: str) -> Path | None:
        record = self.agent.library.get_by_paper_id(paper_id)
        if record is None:
            return None
        path = self.settings.repo_root / record.md_path
        return path if path.exists() else None

    def enqueue_task(self, prompt: str, *, refresh_existing: bool, max_results: int | None) -> dict:
        return self.jobs.submit(prompt, refresh_existing=refresh_existing, max_results=max_results)

    def get_job(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id)

    def cancel_job(self, job_id: str) -> dict | None:
        return self.jobs.cancel(job_id)

    def login_openreview(self, username: str, password: str) -> dict:
        status = self.agent.openreview.login(username, password)
        payload = self.get_library_payload()
        return {"status": status, "app": payload["app"]}

    def logout_openreview(self) -> dict:
        status = self.agent.openreview.logout()
        payload = self.get_library_payload()
        return {"status": status, "app": payload["app"]}

    def respond_job_confirmation(self, job_id: str, confirmation_id: str, *, approved: bool) -> dict | None:
        return self.jobs.respond_confirmation(job_id, confirmation_id, approved=approved)

    def _log_job_event(self, job_id: str, kind: str, message: str) -> None:
        payload = f"job={job_id} | {kind.upper()} | {message}"
        if kind == "failed":
            self.logger.error(payload)
            return
        self.logger.info(payload)


def build_server(settings: Settings, *, host: str | None = None, port: int | None = None) -> tuple[ThreadingHTTPServer, AutoPapersWebApp]:
    app = AutoPapersWebApp(settings)
    handler = _build_handler(app)
    server = ThreadingHTTPServer((host or settings.web_host, port or settings.web_port), handler)
    return server, app


def serve(settings: Settings, *, host: str | None = None, port: int | None = None) -> None:
    server, app = build_server(settings, host=host, port=port)
    bind_host, bind_port = server.server_address
    print(f"AutoPapers web app listening on http://{bind_host}:{bind_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()


def _build_handler(app: AutoPapersWebApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AutoPapersWeb/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path

            if path in ("/", "/index.html"):
                self._serve_static("index.html", content_type="text/html; charset=utf-8")
                return
            if path.startswith("/assets/"):
                self._serve_asset(path.removeprefix("/assets/"))
                return
            if path == "/api/library":
                self._json_response(200, app.get_library_payload())
                return
            if path == "/api/settings":
                self._json_response(200, app.get_settings_payload())
                return

            segments = [segment for segment in path.split("/") if segment]
            if len(segments) >= 3 and segments[0] == "api" and segments[1] == "papers":
                paper_id = unquote(segments[2])
                if len(segments) == 3:
                    detail = app.get_paper_detail(paper_id)
                    if detail is None:
                        self._json_response(404, {"error": "Paper not found"})
                        return
                    self._json_response(200, detail)
                    return
                if len(segments) == 4 and segments[3] == "pdf":
                    file_path = app.get_pdf_path(paper_id)
                    if file_path is None:
                        self._json_response(404, {"error": "PDF not found"})
                        return
                    self._serve_file(file_path, "application/pdf")
                    return
                if len(segments) == 4 and segments[3] == "markdown":
                    file_path = app.get_markdown_path(paper_id)
                    if file_path is None:
                        self._json_response(404, {"error": "Markdown not found"})
                        return
                    self._serve_file(file_path, "text/markdown; charset=utf-8")
                    return

            if len(segments) == 3 and segments[0] == "api" and segments[1] == "tasks":
                job = app.get_job(unquote(segments[2]))
                if job is None:
                    self._json_response(404, {"error": "Task not found"})
                    return
                self._json_response(200, {"job": job})
                return

            self._json_response(404, {"error": "Not found"})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            segments = [segment for segment in parsed.path.split("/") if segment]
            if parsed.path == "/api/settings":
                try:
                    payload = self._read_json_body()
                except ValueError:
                    return
                result = app.handle_settings_action(payload)
                if "error" in result:
                    self._json_response(400, result)
                    return
                self._json_response(200, result)
                return
            if parsed.path == "/api/openreview/login":
                try:
                    payload = self._read_json_body()
                except ValueError:
                    return
                username = str(payload.get("username", "")).strip()
                password = str(payload.get("password", ""))
                if not username or not password:
                    self._json_response(400, {"error": "username and password are required"})
                    return
                try:
                    response_payload = app.login_openreview(username, password)
                except Exception as exc:
                    self._json_response(400, {"error": str(exc)})
                    return
                self._json_response(200, response_payload)
                return
            if parsed.path == "/api/openreview/logout":
                self._json_response(200, app.logout_openreview())
                return
            if len(segments) == 4 and segments[0] == "api" and segments[1] == "papers" and segments[3] == "refresh-metadata":
                paper_id = unquote(segments[2])
                payload = app.refresh_paper_metadata(paper_id)
                if payload is None:
                    self._json_response(404, {"error": "Paper not found"})
                    return
                self._json_response(200, payload)
                return
            if len(segments) == 4 and segments[0] == "api" and segments[1] == "tasks" and segments[3] == "confirmation":
                job_id = unquote(segments[2])
                try:
                    payload = self._read_json_body()
                except ValueError:
                    return
                confirmation_id = str(payload.get("confirmation_id", "")).strip()
                if not confirmation_id:
                    self._json_response(400, {"error": "confirmation_id is required"})
                    return
                approved = bool(payload.get("approved"))
                job = app.respond_job_confirmation(job_id, confirmation_id, approved=approved)
                if job is None:
                    self._json_response(404, {"error": "Confirmation not found"})
                    return
                self._json_response(200, {"job": job})
                return
            if len(segments) == 4 and segments[0] == "api" and segments[1] == "tasks" and segments[3] == "cancel":
                job_id = unquote(segments[2])
                job = app.cancel_job(job_id)
                if job is None:
                    self._json_response(404, {"error": "Task not found"})
                    return
                self._json_response(200, {"job": job})
                return
            if parsed.path != "/api/tasks":
                self._json_response(404, {"error": "Not found"})
                return
            try:
                payload = self._read_json_body()
            except ValueError:
                return

            prompt = str(payload.get("prompt", "")).strip()
            if not prompt:
                self._json_response(400, {"error": "Prompt is required"})
                return

            max_results = payload.get("max_results")
            if max_results in ("", None):
                normalized_max_results = None
            else:
                try:
                    normalized_max_results = max(1, min(int(max_results), 20))
                except (TypeError, ValueError):
                    self._json_response(400, {"error": "max_results must be an integer"})
                    return

            job = app.enqueue_task(
                prompt,
                refresh_existing=bool(payload.get("refresh_existing", False)),
                max_results=normalized_max_results,
            )
            self._json_response(202, {"job": job})

        def do_DELETE(self) -> None:
            parsed = urlparse(self.path)
            segments = [segment for segment in parsed.path.split("/") if segment]
            if len(segments) != 3 or segments[0] != "api" or segments[1] != "papers":
                self._json_response(404, {"error": "Not found"})
                return

            paper_id = unquote(segments[2])
            payload = app.delete_paper(paper_id)
            if payload is None:
                self._json_response(404, {"error": "Paper not found"})
                return
            self._json_response(200, payload)

        def log_message(self, format: str, *args) -> None:
            return

        def _serve_asset(self, asset_name: str) -> None:
            if "/" in asset_name or "\\" in asset_name:
                self._json_response(404, {"error": "Asset not found"})
                return
            path = app.static_root / asset_name
            if not path.exists():
                self._json_response(404, {"error": "Asset not found"})
                return
            content_type, _ = mimetypes.guess_type(path.name)
            self._serve_file(path, content_type or "application/octet-stream")

        def _serve_static(self, file_name: str, *, content_type: str) -> None:
            path = app.static_root / file_name
            if not path.exists():
                self._json_response(404, {"error": "Static file not found"})
                return
            self._serve_file(path, content_type)

        def _serve_file(self, path: Path, content_type: str) -> None:
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                decoded = raw_body.decode("utf-8")
                data = json.loads(decoded) if decoded else {}
            except json.JSONDecodeError:
                self._json_response(400, {"error": "Invalid JSON body"})
                raise ValueError("Invalid JSON body")
            if not isinstance(data, dict):
                self._json_response(400, {"error": "JSON body must be an object"})
                raise ValueError("Invalid JSON body")
            return data

        def _json_response(self, status_code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler
