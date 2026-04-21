from __future__ import annotations

import json
from pathlib import Path


def append_ipc_message(path: Path, message: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(message, ensure_ascii=False) + "\n")
        handle.flush()


def read_ipc_messages(path: Path, offset: int, buffer: str) -> tuple[list[dict[str, object]], int, str]:
    if not path.exists():
        return [], offset, buffer

    with path.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        chunk = handle.read()
        next_offset = handle.tell()

    if not chunk:
        return [], next_offset, buffer

    combined = buffer + chunk
    lines = combined.splitlines(keepends=True)
    next_buffer = ""
    if lines and not lines[-1].endswith("\n"):
        next_buffer = lines.pop()

    messages: list[dict[str, object]] = []
    for line in lines:
        payload = line.strip()
        if not payload:
            continue
        try:
            message = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            messages.append(message)
    return messages, next_offset, next_buffer
