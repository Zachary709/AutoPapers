from __future__ import annotations

from typing import Callable


def processing_percent(index: int, step: int, total: int) -> int:
    if total <= 0:
        return 30
    completed_steps = max(0, ((index - 1) * 4) + step)
    return min(88, 30 + round((completed_steps / (total * 4)) * 58))


def emit_progress(
    progress_callback: Callable[[dict[str, object]], None] | None,
    *,
    stage: str,
    label: str,
    detail: str,
    percent: int,
    indeterminate: bool = False,
    paper_index: int | None = None,
    paper_total: int | None = None,
    current_title: str | None = None,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        {
            "stage": stage,
            "label": label,
            "detail": detail,
            "percent": percent,
            "indeterminate": indeterminate,
            "paper_index": paper_index,
            "paper_total": paper_total,
            "current_title": current_title,
        }
    )
