from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import uuid


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        values[key.strip()] = raw_value.strip().strip('"').strip("'")
    return values


_WEB_SETTINGS_FILE = "web-settings.json"

_PROFILE_FIELDS = ("api_key", "model", "api_url", "network_proxy_url")


def _mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "********"
    return key[:4] + "****" + key[-4:]


def _new_profile_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass(slots=True)
class Settings:
    repo_root: Path
    api_key: str
    model: str
    api_url: str
    library_root: Path
    reports_root: Path
    default_max_results: int
    request_timeout: int
    pdf_max_pages: int
    pdf_max_chars: int
    web_host: str
    web_port: int
    network_proxy_url: str = ""
    openreview_auth_path: Path | None = None
    _base_profile_values: dict[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._capture_base_profile_values()

    @property
    def web_settings_path(self) -> Path:
        return (self.repo_root / ".autopapers" / _WEB_SETTINGS_FILE).resolve()

    def mask_api_key(self) -> str:
        return _mask_api_key(self.api_key)

    def load_web_settings(self) -> None:
        path = self.web_settings_path
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        profiles = data.get("profiles")
        if isinstance(profiles, dict) and profiles:
            active = data.get("active_profile", "")
            if active in profiles:
                self._apply_profile_values(profiles[active])
            else:
                first_id = next(iter(profiles))
                self._apply_profile_values(profiles[first_id])
            return
        self._apply_profile_values(data)

    def _capture_base_profile_values(self) -> None:
        self._base_profile_values = {
            key: str(getattr(self, key, "") or "").strip()
            for key in _PROFILE_FIELDS
        }

    def _reset_profile_values(self) -> None:
        for key, value in self._base_profile_values.items():
            setattr(self, key, value)

    def _apply_profile_values(self, profile: dict) -> None:
        self._reset_profile_values()
        for key in _PROFILE_FIELDS:
            raw_value = profile.get(key)
            if not isinstance(raw_value, str):
                continue
            normalized = raw_value.strip()
            # Empty profile fields mean "use the base env/default value".
            if normalized:
                setattr(self, key, normalized)

    def _read_stored_data(self) -> dict:
        path = self.web_settings_path
        if not path.exists():
            return {"active_profile": "", "profiles": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"active_profile": "", "profiles": {}}
        if not isinstance(data, dict):
            return {"active_profile": "", "profiles": {}}
        if not isinstance(data.get("profiles"), dict):
            return {"active_profile": "", "profiles": {}}
        return data

    def _persist_data(self, data: dict) -> None:
        path = self.web_settings_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_profiles(self) -> dict:
        data = self._read_stored_data()
        profiles = data.get("profiles", {})
        masked = {}
        for pid, profile in profiles.items():
            masked[pid] = {
                "name": profile.get("name", ""),
                "api_key_masked": _mask_api_key(profile.get("api_key", "")),
                "model": profile.get("model", ""),
                "api_url": profile.get("api_url", ""),
                "network_proxy_url": profile.get("network_proxy_url", ""),
            }
        return {
            "active_profile": data.get("active_profile", ""),
            "profiles": masked,
        }

    def save_profile(self, profile_id: str | None, profile: dict) -> dict:
        data = self._read_stored_data()
        profiles = data.setdefault("profiles", {})
        existing = profiles.get(profile_id or "", {}) if profile_id else {}
        if not profile_id:
            profile_id = _new_profile_id()
        clean = {}
        for key in ("name", "api_key", "model", "api_url", "network_proxy_url"):
            clean[key] = str(profile.get(key, "")).strip()
        if not clean["api_key"] and isinstance(existing.get("api_key"), str):
            clean["api_key"] = existing["api_key"].strip()
        if not clean["name"]:
            clean["name"] = clean["model"] or "Unnamed"
        profiles[profile_id] = clean
        data["active_profile"] = profile_id
        self._persist_data(data)
        self._apply_profile_values(clean)
        return {"active_profile": profile_id, "saved_id": profile_id}

    def activate_profile(self, profile_id: str) -> dict:
        data = self._read_stored_data()
        profiles = data.get("profiles", {})
        if profile_id not in profiles:
            return {"active_profile": data.get("active_profile", "")}
        data["active_profile"] = profile_id
        self._persist_data(data)
        self._apply_profile_values(profiles[profile_id])
        return {"active_profile": profile_id}

    def delete_profile(self, profile_id: str) -> dict:
        data = self._read_stored_data()
        profiles = data.get("profiles", {})
        profiles.pop(profile_id, None)
        was_active = data.get("active_profile") == profile_id
        if was_active:
            if profiles:
                new_active = next(iter(profiles))
                data["active_profile"] = new_active
                self._apply_profile_values(profiles[new_active])
            else:
                data["active_profile"] = ""
                self._reset_profile_values()
        self._persist_data(data)
        return {"active_profile": data.get("active_profile", ""), "deleted": profile_id}

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> "Settings":
        resolved_root = (repo_root or Path.cwd()).resolve()
        file_env = _parse_dotenv(resolved_root / ".env")
        env = {**file_env, **os.environ}

        instance = cls(
            repo_root=resolved_root,
            api_key=env.get("MINIMAX_API_KEY", "").strip(),
            model=env.get("MINIMAX_MODEL", "MiniMax-M2.7").strip(),
            api_url=env.get(
                "MINIMAX_API_URL",
                "https://api.minimaxi.com/v1/text/chatcompletion_v2",
            ).strip(),
            library_root=(resolved_root / env.get("AUTOPAPERS_LIBRARY_ROOT", "library")).resolve(),
            reports_root=(resolved_root / env.get("AUTOPAPERS_REPORTS_ROOT", "reports")).resolve(),
            default_max_results=int(env.get("AUTOPAPERS_DEFAULT_MAX_RESULTS", "5")),
            request_timeout=int(env.get("AUTOPAPERS_REQUEST_TIMEOUT", "120")),
            pdf_max_pages=int(env.get("AUTOPAPERS_PDF_MAX_PAGES", "18")),
            pdf_max_chars=int(env.get("AUTOPAPERS_PDF_MAX_CHARS", "45000")),
            web_host=env.get("AUTOPAPERS_WEB_HOST", "127.0.0.1").strip(),
            web_port=int(env.get("AUTOPAPERS_WEB_PORT", "8765")),
            network_proxy_url=env.get("AUTOPAPERS_HTTP_PROXY", "").strip(),
            openreview_auth_path=(resolved_root / ".autopapers" / "openreview-auth.json").resolve(),
        )
        instance.load_web_settings()
        return instance
