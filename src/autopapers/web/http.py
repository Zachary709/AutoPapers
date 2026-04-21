from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

from autopapers.config import Settings
from autopapers.web.app import AutoPapersWebApp


def build_server(settings: Settings, *, host: str | None = None, port: int | None = None) -> tuple[ThreadingHTTPServer, AutoPapersWebApp]:
    app = AutoPapersWebApp(settings)
    handler = build_handler(app)
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


def build_handler(app: AutoPapersWebApp):
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
            path = self._resolve_static_path(asset_name)
            if path is None or not path.exists() or not path.is_file():
                self._json_response(404, {"error": "Asset not found"})
                return
            content_type, _ = mimetypes.guess_type(path.name)
            self._serve_file(path, content_type or "application/octet-stream")

        def _serve_static(self, file_name: str, *, content_type: str) -> None:
            path = self._resolve_static_path(file_name)
            if path is None or not path.exists() or not path.is_file():
                self._json_response(404, {"error": "Static file not found"})
                return
            self._serve_file(path, content_type)

        def _resolve_static_path(self, relative_name: str) -> Path | None:
            try:
                root = app.static_root.resolve()
                candidate = (root / relative_name).resolve()
            except (RuntimeError, OSError):
                return None
            if candidate == root or root not in candidate.parents:
                return None
            return candidate

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
