from __future__ import annotations

import json

from autopapers.common.atomic_io import write_text_atomic
from autopapers.common.text_normalization import utc_now_iso
from autopapers.models import StoredPaper


def load_index(library) -> dict[str, StoredPaper]:
    if not library.index_path.exists():
        return {}
    try:
        data = json.loads(library.index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    papers = data.get("papers", [])
    records: dict[str, StoredPaper] = {}
    for record_data in papers:
        stored = StoredPaper.from_dict(record_data)
        records[stored.paper.paper_id] = stored
    return records


def save_index(library) -> None:
    payload = {
        "updated_at": utc_now_iso(),
        "papers": [record.to_dict() for record in sorted(library._records.values(), key=lambda item: item.paper.paper_id)],
    }
    write_text_atomic(library.index_path, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    library._index_mtime_ns = get_index_mtime_ns(library)


def reload_index_if_changed(library) -> None:
    current_mtime_ns = get_index_mtime_ns(library)
    if current_mtime_ns == library._index_mtime_ns:
        return
    library._records = load_index(library)
    library._index_mtime_ns = current_mtime_ns


def get_index_mtime_ns(library) -> int | None:
    if not library.index_path.exists():
        return None
    return library.index_path.stat().st_mtime_ns
