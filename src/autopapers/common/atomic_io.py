from __future__ import annotations

import os
from pathlib import Path


def write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    _write_atomic(path, content.encode(encoding))


def write_bytes_atomic(path: Path, content: bytes) -> None:
    _write_atomic(path, content)


def _write_atomic(path: Path, content: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.name}.tmp")
    with tmp_path.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, target)
