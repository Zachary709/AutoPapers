from __future__ import annotations

import time
import traceback
import uuid
from pathlib import Path
from typing import Callable

from autopapers.models import TaskCancelledError
from autopapers.web.tasks.ipc import append_ipc_message, read_ipc_messages
from autopapers.web.tasks.models import CONFIRMATION_POLL_INTERVAL_SECONDS, TaskConfirmation


class TaskReporter:
    def __init__(self, event_path: Path, control_path: Path) -> None:
        self._event_path = event_path
        self._control_path = control_path
        self._control_offset = 0
        self._control_buffer = ""

    def progress(self, payload: dict[str, object]) -> None:
        self._emit({"type": "progress", "payload": dict(payload)})

    def notice(
        self,
        message: str,
        *,
        kind: str | None = None,
        stage: str | None = None,
        level: str | None = None,
    ) -> None:
        self._emit(
            {
                "type": "notice",
                "message": str(message),
                "kind": kind,
                "stage": stage,
                "level": level,
            }
        )

    def timeline(self, payload: dict[str, object]) -> None:
        self.notice(
            str(payload.get("message", "")),
            kind=str(payload.get("kind") or "info"),
            stage=str(payload.get("stage")) if payload.get("stage") else None,
            level=str(payload.get("level")) if payload.get("level") else None,
        )

    def debug(self, message: str) -> None:
        self._emit({"type": "debug", "message": str(message)})

    def confirm(self, payload: dict[str, object]) -> bool:
        confirmation = TaskConfirmation(
            id=str(payload.get("id") or uuid.uuid4().hex[:12]),
            prompt=str(payload.get("prompt") or "找到的论文与输入标题差异较大，是否仍然继续？"),
            detail=str(payload.get("detail") or ""),
            source=str(payload.get("source") or ""),
            requested_title=str(payload.get("requested_title") or ""),
            candidate_title=str(payload.get("candidate_title") or ""),
            similarity_score=float(payload.get("similarity_score") or 0.0),
        )
        self._emit({"type": "confirmation_request", "payload": confirmation.to_dict()})
        while True:
            responses, self._control_offset, self._control_buffer = read_ipc_messages(
                self._control_path,
                self._control_offset,
                self._control_buffer,
            )
            for response in responses:
                if str(response.get("type") or "") != "confirmation_response":
                    continue
                if str(response.get("confirmation_id") or "") != confirmation.id:
                    continue
                return bool(response.get("approved"))
            time.sleep(CONFIRMATION_POLL_INTERVAL_SECONDS)

    def check_cancelled(self) -> None:
        return

    def _emit(self, message: dict[str, object]) -> None:
        try:
            append_ipc_message(self._event_path, message)
        except Exception:
            pass


def worker_main(
    runner: Callable[[str, bool, int | None, TaskReporter], dict],
    request: str,
    refresh_existing: bool,
    max_results: int | None,
    event_path: Path,
    control_path: Path,
) -> None:
    reporter = TaskReporter(event_path, control_path)
    try:
        result = runner(request, refresh_existing, max_results, reporter)
    except TaskCancelledError as exc:
        reporter._emit({"type": "cancelled", "error": str(exc)})
    except Exception as exc:
        reporter._emit(
            {
                "type": "error",
                "error": str(exc),
                "traceback": traceback.format_exc(limit=8),
            }
        )
    else:
        reporter._emit({"type": "result", "result": result})
