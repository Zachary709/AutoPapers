from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from autopapers.utils import utc_now_iso


@dataclass(slots=True)
class OpenReviewCredentials:
    username: str
    token: str
    saved_at: str

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "token": self.token,
            "saved_at": self.saved_at,
        }


class OpenReviewAuthStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def load(self) -> OpenReviewCredentials | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        username = str(payload.get("username", "")).strip()
        token = str(payload.get("token", "")).strip()
        saved_at = str(payload.get("saved_at", "")).strip()
        if not username or not token:
            return None
        return OpenReviewCredentials(username=username, token=token, saved_at=saved_at or utc_now_iso())

    def save(self, username: str, token: str) -> OpenReviewCredentials:
        credentials = OpenReviewCredentials(
            username=username.strip(),
            token=token.strip(),
            saved_at=utc_now_iso(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(credentials.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return credentials

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
