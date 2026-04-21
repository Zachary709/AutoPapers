from __future__ import annotations

from dataclasses import asdict
from functools import partial
from pathlib import Path
from threading import Lock
from urllib.parse import quote

from autopapers.config import Settings
from autopapers.common.text_normalization import utc_now_iso
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


def serialize_stored_paper(record, repo_root: Path) -> dict:
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


def run_task_process_entry(
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
        "new_papers": [serialize_stored_paper(item, settings.repo_root) for item in result.new_papers],
        "reused_papers": [serialize_stored_paper(item, settings.repo_root) for item in result.reused_papers],
        "related_papers": [serialize_stored_paper(item, settings.repo_root) for item in result.related_papers],
        "library": agent.library.list_tree(),
    }


class AutoPapersWebApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.agent = AutoPapersAgent(settings)
        self.static_root = Path(__file__).resolve().parent / "static"
        self.logger = FileEventLogger(settings.reports_root / "web-serve.log")
        self.logger.info(f"Web app initialized | model={settings.model} | host={settings.web_host}:{settings.web_port}")
        self.jobs = TaskManager(
            partial(run_task_process_entry, settings.repo_root),
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
        return {**profiles, "openreview": openreview_status}

    def handle_settings_action(self, payload: dict) -> dict:
        action = str(payload.get("action", "")).strip()
        if action == "save":
            result = self.settings.save_profile(payload.get("profile_id") or None, payload.get("profile", {}))
        elif action == "delete":
            result = self.settings.delete_profile(str(payload.get("profile_id", "")).strip())
        elif action == "activate":
            result = self.settings.activate_profile(str(payload.get("profile_id", "")).strip())
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
