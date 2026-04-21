from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock


PROCESS_POLL_INTERVAL_SECONDS = 0.1
PROCESS_TERMINATE_TIMEOUT_SECONDS = 1.0
PROCESS_KILL_TIMEOUT_SECONDS = 1.0
CONFIRMATION_POLL_INTERVAL_SECONDS = 0.05
USER_CANCEL_MESSAGE = "用户手动停止任务。"
PROCESS_CANCELLING_MESSAGE = "已收到停止请求，正在终止任务进程。"
PROCESS_FORCE_KILL_MESSAGE = "任务进程未在 1 秒内退出，已强制结束。"
IPC_ROOT_RELATIVE_PATH = Path(".autopapers") / "job-ipc"
IPC_EVENT_FILENAME = "events.jsonl"
IPC_CONTROL_FILENAME = "control.jsonl"


@dataclass(slots=True)
class TaskProgress:
    stage: str = "queued"
    label: str = "排队中"
    detail: str = "等待执行，即将开始"
    percent: int = 0
    indeterminate: bool = True
    paper_index: int | None = None
    paper_total: int | None = None
    current_title: str | None = None
    queue_position: int | None = 1

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "label": self.label,
            "detail": self.detail,
            "percent": self.percent,
            "indeterminate": self.indeterminate,
            "paper_index": self.paper_index,
            "paper_total": self.paper_total,
            "current_title": self.current_title,
            "queue_position": self.queue_position,
        }


@dataclass(slots=True)
class TaskConfirmation:
    id: str
    prompt: str
    detail: str
    source: str
    requested_title: str
    candidate_title: str
    similarity_score: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "detail": self.detail,
            "source": self.source,
            "requested_title": self.requested_title,
            "candidate_title": self.candidate_title,
            "similarity_score": self.similarity_score,
        }


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
    cancel_requested: bool = False
    notices: list[dict] = field(default_factory=list)
    progress: TaskProgress = field(default_factory=TaskProgress)
    confirmation: TaskConfirmation | None = None

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
            "cancel_requested": self.cancel_requested,
            "notices": list(self.notices),
            "progress": self.progress.to_dict(),
            "confirmation": None if self.confirmation is None else self.confirmation.to_dict(),
        }


@dataclass(slots=True)
class PendingConfirmationState:
    confirmation_id: str
    previous_status: str
    previous_progress: TaskProgress


@dataclass(slots=True)
class WorkerState:
    process: object
    ipc_dir: Path
    event_path: Path
    control_path: Path
    event_offset: int = 0
    event_buffer: str = ""
    command_lock: Lock = field(default_factory=Lock)
    result: dict | None = None
    error: str | None = None
    cancelled_error: str | None = None
    terminate_started: bool = False
