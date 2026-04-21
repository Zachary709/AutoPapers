from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from threading import Lock, Thread
from typing import Callable
import shutil
import tempfile
import time
import traceback
import uuid

from autopapers.common.text_normalization import truncate_text, utc_now_iso
from autopapers.web.tasks.ipc import append_ipc_message, read_ipc_messages
from autopapers.web.tasks.models import (
    IPC_CONTROL_FILENAME,
    IPC_EVENT_FILENAME,
    IPC_ROOT_RELATIVE_PATH,
    PROCESS_CANCELLING_MESSAGE,
    PROCESS_FORCE_KILL_MESSAGE,
    PROCESS_KILL_TIMEOUT_SECONDS,
    PROCESS_POLL_INTERVAL_SECONDS,
    PROCESS_TERMINATE_TIMEOUT_SECONDS,
    USER_CANCEL_MESSAGE,
    PendingConfirmationState,
    TaskConfirmation,
    TaskJob,
    TaskProgress,
    WorkerState,
)
from autopapers.web.tasks.reporter import TaskReporter, worker_main


class TaskManager:
    def __init__(
        self,
        runner: Callable[[str, bool, int | None, TaskReporter], dict],
        *,
        max_workers: int = 1,
        event_callback: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._runner = runner
        self._context = get_context("spawn")
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="autopapers-job")
        self._lock = Lock()
        self._jobs: dict[str, TaskJob] = {}
        self._workers: dict[str, WorkerState] = {}
        self._confirmations: dict[str, PendingConfirmationState] = {}
        self._event_callback = event_callback
        self._ipc_root = (Path.cwd() / IPC_ROOT_RELATIVE_PATH).resolve()
        self._ipc_root.mkdir(parents=True, exist_ok=True)

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
            self._refresh_queue_positions_locked()

        self._emit_event(job.id, "queued", f"任务已排队：{truncate_text(request, 120)}")
        self._executor.submit(self._run_job, job.id)
        return job.to_dict()

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else job.to_dict()

    def cancel(self, job_id: str) -> dict | None:
        terminal_statuses = {"completed", "failed", "cancelled"}
        emit_kind = "notice"
        emit_message = PROCESS_CANCELLING_MESSAGE
        worker_to_stop: WorkerState | None = None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in terminal_statuses:
                return job.to_dict()
            if job.status == "queued":
                job.status = "cancelled"
                job.cancel_requested = True
                job.error = USER_CANCEL_MESSAGE
                job.confirmation = None
                job.progress = TaskProgress(
                    stage="cancelled",
                    label="任务已终止",
                    detail=USER_CANCEL_MESSAGE,
                    percent=0,
                    indeterminate=False,
                )
                job.updated_at = utc_now_iso()
                self._confirmations.pop(job_id, None)
                self._refresh_queue_positions_locked()
                payload = job.to_dict()
                emit_kind = "cancelled"
                emit_message = f"任务终止：{USER_CANCEL_MESSAGE}"
            else:
                job.cancel_requested = True
                job.confirmation = None
                job.updated_at = utc_now_iso()
                job.notices.append(
                    {
                        "id": uuid.uuid4().hex[:12],
                        "level": "warning",
                        "kind": "warning",
                        "stage": job.progress.stage,
                        "message": PROCESS_CANCELLING_MESSAGE,
                        "created_at": utc_now_iso(),
                    }
                )
                job.progress = TaskProgress(
                    stage=job.progress.stage,
                    label=job.progress.label,
                    detail=PROCESS_CANCELLING_MESSAGE,
                    percent=job.progress.percent,
                    indeterminate=job.progress.indeterminate,
                    paper_index=job.progress.paper_index,
                    paper_total=job.progress.paper_total,
                    current_title=job.progress.current_title,
                    queue_position=job.progress.queue_position,
                )
                self._confirmations.pop(job_id, None)
                payload = job.to_dict()
                worker_to_stop = self._workers.get(job_id)
        if worker_to_stop is not None:
            self._ensure_worker_termination(job_id, worker_to_stop)
        self._emit_event(job_id, emit_kind, emit_message)
        return payload

    def respond_confirmation(self, job_id: str, confirmation_id: str, *, approved: bool) -> dict | None:
        worker_state: WorkerState | None = None
        with self._lock:
            job = self._jobs.get(job_id)
            pending = self._confirmations.get(job_id)
            if job is None or pending is None or job.confirmation is None:
                return None
            if pending.confirmation_id != confirmation_id or job.confirmation.id != confirmation_id:
                return None
            worker_state = self._workers.get(job_id)
            if worker_state is None:
                return None
            message = "用户确认继续解析候选论文。" if approved else "用户拒绝解析低相似度候选论文，任务将终止。"
            job.notices.append(
                {
                    "id": uuid.uuid4().hex[:12],
                    "level": "info",
                    "kind": "milestone",
                    "stage": "confirmation",
                    "message": message,
                    "created_at": utc_now_iso(),
                }
            )
            job.status = pending.previous_status
            if approved:
                job.progress = pending.previous_progress
            else:
                job.progress = TaskProgress(
                    stage=pending.previous_progress.stage,
                    label=pending.previous_progress.label,
                    detail="用户已拒绝继续，任务将终止。",
                    percent=pending.previous_progress.percent,
                    indeterminate=pending.previous_progress.indeterminate,
                    paper_index=pending.previous_progress.paper_index,
                    paper_total=pending.previous_progress.paper_total,
                    current_title=pending.previous_progress.current_title,
                    queue_position=pending.previous_progress.queue_position,
                )
            job.confirmation = None
            job.updated_at = utc_now_iso()
            self._confirmations.pop(job_id, None)
            payload = job.to_dict()
        with worker_state.command_lock:
            append_ipc_message(
                worker_state.control_path,
                {
                    "type": "confirmation_response",
                    "confirmation_id": confirmation_id,
                    "approved": bool(approved),
                },
            )
        self._emit_event(job_id, "confirmation", "用户已确认继续" if approved else "用户拒绝继续")
        return payload

    def close(self) -> None:
        with self._lock:
            workers = list(self._workers.items())
        for job_id, worker_state in workers:
            self._terminate_worker_process(job_id, worker_state, force_notice=False)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run_job(self, job_id: str) -> None:
        ipc_dir = Path(tempfile.mkdtemp(prefix=f"{job_id}-", dir=self._ipc_root))
        event_path = ipc_dir / IPC_EVENT_FILENAME
        control_path = ipc_dir / IPC_CONTROL_FILENAME
        event_path.write_text("", encoding="utf-8")
        control_path.write_text("", encoding="utf-8")

        with self._lock:
            job = self._jobs[job_id]
            if job.status == "cancelled":
                self._cleanup_worker_ipc(ipc_dir)
                return
            request = job.request
            refresh_existing = job.refresh_existing
            max_results = job.max_results
            job.status = "running"
            job.updated_at = utc_now_iso()
            job.progress = TaskProgress(
                stage="planning",
                label="任务规划",
                detail="正在理解任务并生成执行方案",
                percent=5,
                indeterminate=False,
            )
            self._refresh_queue_positions_locked()

        self._emit_event(job_id, "running", f"任务开始执行：{truncate_text(request, 120)}")
        try:
            process = self._context.Process(
                target=worker_main,
                args=(self._runner, request, refresh_existing, max_results, event_path, control_path),
                name=f"autopapers-job-{job_id}",
            )
            process.start()
        except Exception as exc:
            self._cleanup_worker_ipc(ipc_dir)
            self._mark_job_failed(job_id, f"{exc}\n\n{traceback.format_exc(limit=5)}")
            self._emit_event(job_id, "failed", f"任务失败：{truncate_text(str(exc), 240)}")
            return

        worker_state = WorkerState(
            process=process,
            ipc_dir=ipc_dir,
            event_path=event_path,
            control_path=control_path,
        )
        with self._lock:
            self._workers[job_id] = worker_state
            cancel_requested = self._jobs[job_id].cancel_requested

        self._emit_event(job_id, "worker", f"任务进程已启动 pid={process.pid}")
        if cancel_requested:
            self._ensure_worker_termination(job_id, worker_state)
        self._supervise_worker(job_id, worker_state)

    def _supervise_worker(self, job_id: str, worker_state: WorkerState) -> None:
        process = worker_state.process
        try:
            while True:
                messages, worker_state.event_offset, worker_state.event_buffer = read_ipc_messages(
                    worker_state.event_path,
                    worker_state.event_offset,
                    worker_state.event_buffer,
                )
                for message in messages:
                    self._handle_worker_message(job_id, worker_state, message)
                if not process.is_alive():
                    break
                if not messages:
                    time.sleep(PROCESS_POLL_INTERVAL_SECONDS)

            messages, worker_state.event_offset, worker_state.event_buffer = read_ipc_messages(
                worker_state.event_path,
                worker_state.event_offset,
                worker_state.event_buffer,
            )
            for message in messages:
                self._handle_worker_message(job_id, worker_state, message)
        finally:
            try:
                process.join(timeout=PROCESS_POLL_INTERVAL_SECONDS)
            except Exception:
                pass
            self._finalize_worker(job_id, worker_state)

    def _handle_worker_message(self, job_id: str, worker_state: WorkerState, message: object) -> None:
        if not isinstance(message, dict):
            return
        message_type = str(message.get("type") or "")
        if message_type == "result":
            worker_state.result = message.get("result") if isinstance(message.get("result"), dict) else None
            return
        if message_type == "cancelled":
            worker_state.cancelled_error = str(message.get("error") or "任务已终止。")
            return
        if message_type == "error":
            error_text = str(message.get("error") or "任务失败。")
            traceback_text = str(message.get("traceback") or "").strip()
            worker_state.error = error_text if not traceback_text else f"{error_text}\n\n{traceback_text}"
            return

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.cancel_requested:
                return

        if message_type == "progress":
            payload = message.get("payload")
            if isinstance(payload, dict):
                self._set_progress(job_id, payload)
            return

        if message_type == "notice":
            self._append_notice(
                job_id,
                str(message.get("message", "")),
                kind=str(message.get("kind")) if message.get("kind") else None,
                stage=str(message.get("stage")) if message.get("stage") else None,
                level=str(message.get("level")) if message.get("level") else None,
            )
            return

        if message_type == "debug":
            self._emit_event(job_id, "debug", str(message.get("message", "")))
            return

        if message_type == "confirmation_request":
            payload = message.get("payload")
            if isinstance(payload, dict):
                self._set_confirmation_request(job_id, payload)

    def _set_confirmation_request(self, job_id: str, payload: dict[str, object]) -> None:
        confirmation = TaskConfirmation(
            id=str(payload.get("id") or uuid.uuid4().hex[:12]),
            prompt=str(payload.get("prompt") or "找到的论文与输入标题差异较大，是否仍然继续？"),
            detail=str(payload.get("detail") or ""),
            source=str(payload.get("source") or ""),
            requested_title=str(payload.get("requested_title") or ""),
            candidate_title=str(payload.get("candidate_title") or ""),
            similarity_score=float(payload.get("similarity_score") or 0.0),
        )
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.cancel_requested:
                return
            self._confirmations[job_id] = PendingConfirmationState(
                confirmation_id=confirmation.id,
                previous_status=job.status,
                previous_progress=job.progress,
            )
            job.status = "awaiting_confirmation"
            job.confirmation = confirmation
            job.progress = TaskProgress(
                stage="confirmation",
                label="等待确认",
                detail=confirmation.detail or confirmation.prompt,
                percent=max(job.progress.percent, 15),
                indeterminate=False,
                paper_index=job.progress.paper_index,
                paper_total=job.progress.paper_total,
                current_title=confirmation.candidate_title or job.progress.current_title,
            )
            job.updated_at = utc_now_iso()
        self._emit_event(job_id, "confirmation", confirmation.detail or confirmation.prompt)

    def _finalize_worker(self, job_id: str, worker_state: WorkerState) -> None:
        process = worker_state.process
        exit_code = process.exitcode
        emit_kind = "failed"
        emit_message = "任务失败"
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                self._cleanup_worker_ipc(worker_state.ipc_dir)
                return
            request = current.request
            self._workers.pop(job_id, None)
            self._confirmations.pop(job_id, None)
            current.confirmation = None
            current.updated_at = utc_now_iso()

            if current.cancel_requested:
                current.status = "cancelled"
                current.error = USER_CANCEL_MESSAGE
                current.progress = TaskProgress(
                    stage="cancelled",
                    label="任务已终止",
                    detail=USER_CANCEL_MESSAGE,
                    percent=max(current.progress.percent, 5),
                    indeterminate=False,
                    paper_index=current.progress.paper_index,
                    paper_total=current.progress.paper_total,
                    current_title=current.progress.current_title,
                )
                self._refresh_queue_positions_locked()
                emit_kind = "cancelled"
                emit_message = f"任务终止：{USER_CANCEL_MESSAGE}"
            elif worker_state.cancelled_error is not None:
                current.status = "cancelled"
                current.error = worker_state.cancelled_error
                current.progress = TaskProgress(
                    stage="cancelled",
                    label="任务已终止",
                    detail=truncate_text(worker_state.cancelled_error, 180),
                    percent=max(current.progress.percent, 5),
                    indeterminate=False,
                    paper_index=current.progress.paper_index,
                    paper_total=current.progress.paper_total,
                    current_title=current.progress.current_title,
                )
                self._refresh_queue_positions_locked()
                emit_kind = "cancelled"
                emit_message = f"任务终止：{truncate_text(worker_state.cancelled_error, 240)}"
            elif worker_state.error is not None:
                current.status = "failed"
                current.error = worker_state.error
                current.progress = TaskProgress(
                    stage="failed",
                    label="任务失败",
                    detail=truncate_text(worker_state.error.splitlines()[0], 180),
                    percent=max(current.progress.percent, 5),
                    indeterminate=False,
                    paper_index=current.progress.paper_index,
                    paper_total=current.progress.paper_total,
                    current_title=current.progress.current_title,
                )
                self._refresh_queue_positions_locked()
                emit_kind = "failed"
                emit_message = f"任务失败：{truncate_text(worker_state.error.splitlines()[0], 240)}"
            elif worker_state.result is not None and exit_code == 0:
                current.status = "completed"
                current.result = worker_state.result
                current.progress = TaskProgress(
                    stage="completed",
                    label="任务完成",
                    detail="报告与目录已更新",
                    percent=100,
                    indeterminate=False,
                    paper_index=current.progress.paper_index,
                    paper_total=current.progress.paper_total,
                    current_title=current.progress.current_title,
                )
                self._refresh_queue_positions_locked()
                emit_kind = "completed"
                emit_message = f"任务执行完成：{truncate_text(request, 120)}"
            else:
                current.status = "failed"
                current.error = (
                    f"任务进程异常退出，exit_code={exit_code}" if exit_code not in (None, 0) else "任务进程已退出，但未返回结果。"
                )
                current.progress = TaskProgress(
                    stage="failed",
                    label="任务失败",
                    detail=truncate_text(current.error, 180),
                    percent=max(current.progress.percent, 5),
                    indeterminate=False,
                    paper_index=current.progress.paper_index,
                    paper_total=current.progress.paper_total,
                    current_title=current.progress.current_title,
                )
                self._refresh_queue_positions_locked()
                emit_kind = "failed"
                emit_message = f"任务失败：{truncate_text(current.error, 240)}"

        self._cleanup_worker_ipc(worker_state.ipc_dir)
        self._emit_event(job_id, emit_kind, emit_message)

    def _mark_job_failed(self, job_id: str, error_text: str) -> None:
        with self._lock:
            current = self._jobs[job_id]
            current.status = "failed"
            current.error = error_text
            current.confirmation = None
            current.progress = TaskProgress(
                stage="failed",
                label="任务失败",
                detail=truncate_text(error_text.splitlines()[0], 180),
                percent=max(current.progress.percent, 5),
                indeterminate=False,
                paper_index=current.progress.paper_index,
                paper_total=current.progress.paper_total,
                current_title=current.progress.current_title,
            )
            current.updated_at = utc_now_iso()
            self._confirmations.pop(job_id, None)
            self._refresh_queue_positions_locked()

    def _ensure_worker_termination(self, job_id: str, worker_state: WorkerState) -> None:
        with self._lock:
            active_state = self._workers.get(job_id)
            if active_state is None or active_state is not worker_state or worker_state.terminate_started:
                return
            worker_state.terminate_started = True
        termination_thread = Thread(
            target=self._terminate_worker_process,
            args=(job_id, worker_state),
            daemon=True,
            name=f"autopapers-job-cancel-{job_id}",
        )
        termination_thread.start()

    def _terminate_worker_process(self, job_id: str, worker_state: WorkerState, *, force_notice: bool = True) -> None:
        process = worker_state.process
        pid = process.pid
        if pid is not None:
            self._emit_event(job_id, "worker", f"正在终止任务进程 pid={pid}")
        try:
            if process.is_alive():
                process.terminate()
                process.join(timeout=PROCESS_TERMINATE_TIMEOUT_SECONDS)
        except Exception as exc:
            self._emit_event(job_id, "worker", f"终止任务进程失败：{truncate_text(str(exc), 180)}")
            return

        if process.is_alive():
            if force_notice:
                self._append_notice(job_id, PROCESS_FORCE_KILL_MESSAGE, kind="warning", level="warning")
            self._emit_event(job_id, "worker", f"任务进程未及时退出，升级为 kill pid={pid}")
            try:
                process.kill()
                process.join(timeout=PROCESS_KILL_TIMEOUT_SECONDS)
            except Exception as exc:
                self._emit_event(job_id, "worker", f"强制结束任务进程失败：{truncate_text(str(exc), 180)}")
                return

        self._emit_event(job_id, "worker", f"任务进程已退出 pid={pid} exit_code={process.exitcode}")

    def _append_notice(
        self,
        job_id: str,
        message: str,
        *,
        kind: str | None = None,
        stage: str | None = None,
        level: str | None = None,
    ) -> None:
        normalized_kind = kind or self._infer_notice_kind(message)
        normalized_level = level or self._level_for_kind(normalized_kind)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.notices.append(
                {
                    "id": uuid.uuid4().hex[:12],
                    "level": normalized_level,
                    "kind": normalized_kind,
                    "stage": stage or job.progress.stage,
                    "message": str(message),
                    "created_at": utc_now_iso(),
                }
            )
            job.updated_at = utc_now_iso()
        self._emit_event(job_id, "notice", str(message))

    def _set_progress(self, job_id: str, payload: dict[str, object]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            current = job.progress
            stage = str(payload.get("stage") or current.stage)
            detail = str(payload.get("detail") or current.detail)
            label = str(payload.get("label") or current.label)
            indeterminate = bool(payload.get("indeterminate", current.indeterminate))
            requested_percent = int(payload.get("percent", current.percent) or 0)
            if not indeterminate:
                baseline = 0 if current.indeterminate else current.percent
                percent = max(baseline, min(100, requested_percent))
            else:
                percent = max(0, min(100, requested_percent))
            progress = TaskProgress(
                stage=stage,
                label=label,
                detail=detail,
                percent=percent,
                indeterminate=indeterminate,
                paper_index=self._coerce_optional_int(payload.get("paper_index"), current.paper_index),
                paper_total=self._coerce_optional_int(payload.get("paper_total"), current.paper_total),
                current_title=self._coerce_optional_str(payload.get("current_title"), current.current_title),
                queue_position=self._coerce_optional_int(payload.get("queue_position"), current.queue_position),
            )
            if stage != "queued":
                progress.queue_position = None
            job.progress = progress
            job.updated_at = utc_now_iso()
        self._emit_event(job_id, "progress", f"{label} | {detail}")

    def _refresh_queue_positions_locked(self) -> None:
        queued_jobs = [job for job in self._jobs.values() if job.status == "queued"]
        for index, job in enumerate(queued_jobs, start=1):
            waiting_detail = "等待执行，即将开始" if index == 1 else f"等待执行，前方还有 {index - 1} 个任务"
            job.progress = TaskProgress(
                stage="queued",
                label="排队中",
                detail=waiting_detail,
                percent=0,
                indeterminate=True,
                queue_position=index,
            )
            job.updated_at = utc_now_iso()

    @staticmethod
    def _cleanup_worker_ipc(ipc_dir: Path) -> None:
        if ipc_dir.exists():
            shutil.rmtree(ipc_dir, ignore_errors=True)

    @staticmethod
    def _coerce_optional_int(value: object, fallback: int | None) -> int | None:
        if value is None:
            return fallback
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _coerce_optional_str(value: object, fallback: str | None) -> str | None:
        if value is None:
            return fallback
        text = str(value).strip()
        return text or fallback

    @staticmethod
    def _infer_notice_kind(message: str) -> str:
        if any(token in message for token in ("连续失败", "响应解析失败", "检索失败", "重试")):
            return "retry"
        if any(token in message for token in ("失败", "跳过", "未能解析", "缺失 PDF", "改用")):
            return "warning"
        return "info"

    @staticmethod
    def _level_for_kind(kind: str) -> str:
        if kind in {"retry", "warning"}:
            return "warning"
        return "info"

    def _emit_event(self, job_id: str, kind: str, message: str) -> None:
        if self._event_callback is None:
            return
        try:
            self._event_callback(job_id, kind, message)
        except Exception:
            pass
