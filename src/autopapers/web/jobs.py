from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable
import traceback
import uuid

from autopapers.utils import truncate_text, utc_now_iso


@dataclass(slots=True)
class TaskJob:
    id: str
    request: str
    refresh_existing: bool
    max_results: int | None
    status: str
    created_at: str
    updated_at: str
    result: dict | None = None
    error: str | None = None
    notices: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request": self.request,
            "refresh_existing": self.refresh_existing,
            "max_results": self.max_results,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
            "notices": list(self.notices),
        }


class TaskManager:
    def __init__(
        self,
        runner: Callable[[str, bool, int | None, Callable[[str], None]], dict],
        *,
        max_workers: int = 1,
        event_callback: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._runner = runner
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="autopapers-job")
        self._lock = Lock()
        self._jobs: dict[str, TaskJob] = {}
        self._event_callback = event_callback

    def submit(self, request: str, *, refresh_existing: bool = False, max_results: int | None = None) -> dict:
        timestamp = utc_now_iso()
        job = TaskJob(
            id=uuid.uuid4().hex[:12],
            request=request,
            refresh_existing=refresh_existing,
            max_results=max_results,
            status="queued",
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self._lock:
            self._jobs[job.id] = job

        self._emit_event(job.id, "queued", f"任务已排队：{truncate_text(request, 120)}")
        self._executor.submit(self._run_job, job.id)
        return job.to_dict()

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else job.to_dict()

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            request = job.request
            refresh_existing = job.refresh_existing
            max_results = job.max_results

        self._update(job_id, status="running")
        self._emit_event(job_id, "running", f"任务开始执行：{truncate_text(request, 120)}")
        try:

            def notify(message: str) -> None:
                self._append_notice(job_id, message)

            result = self._runner(request, refresh_existing, max_results, notify)
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                error=f"{exc}\n\n{traceback.format_exc(limit=5)}",
            )
            self._emit_event(job_id, "failed", f"任务失败：{truncate_text(str(exc), 240)}")
            return

        self._update(job_id, status="completed", result=result)
        self._emit_event(job_id, "completed", f"任务执行完成：{truncate_text(request, 120)}")

    def _append_notice(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.notices.append(
                {
                    "id": uuid.uuid4().hex[:12],
                    "level": "warning",
                    "message": str(message),
                    "created_at": utc_now_iso(),
                }
            )
            job.updated_at = utc_now_iso()
        self._emit_event(job_id, "notice", str(message))

    def _update(self, job_id: str, **changes: object) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = utc_now_iso()

    def _emit_event(self, job_id: str, kind: str, message: str) -> None:
        if self._event_callback is None:
            return
        try:
            self._event_callback(job_id, kind, message)
        except Exception:
            pass
