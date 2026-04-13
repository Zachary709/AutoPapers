from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


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

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> "Settings":
        resolved_root = (repo_root or Path.cwd()).resolve()
        file_env = _parse_dotenv(resolved_root / ".env")
        env = {**file_env, **os.environ}

        return cls(
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
        )
