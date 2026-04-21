from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from autopapers.models import Paper, VenueInfo
from autopapers.openreview_auth import OpenReviewAuthStore
from autopapers.utils import normalize_whitespace, parse_openreview_id, title_similarity


class OpenReviewClientUnavailableError(RuntimeError):
    pass


class OpenReviewAuthError(RuntimeError):
    pass


class OpenReviewClient:
    api_base_url = "https://api2.openreview.net"
    web_base_url = "https://openreview.net"

    def __init__(
        self,
        timeout: int = 120,
        *,
        auth_store: OpenReviewAuthStore | None = None,
        client_factory: Callable[..., object] | None = None,
        proxy_url: str = "",
    ) -> None:
        self.timeout = timeout
        self.auth_store = auth_store
        self._client_factory = client_factory or self._default_client_factory
        self.proxy_url = normalize_whitespace(proxy_url)

    def auth_status(self) -> dict[str, object]:
        credentials = self.auth_store.load() if self.auth_store is not None else None
        return {
            "available": self._is_client_available(),
            "authenticated": credentials is not None,
            "username": credentials.username if credentials is not None else "",
            "saved_at": credentials.saved_at if credentials is not None else "",
        }

    def login(self, username: str, password: str) -> dict[str, object]:
        if not self._is_client_available():
            raise OpenReviewClientUnavailableError("openreview-py 未安装，当前环境无法启用 OpenReview 登录。")
        normalized_username = normalize_whitespace(username)
        if not normalized_username or not password:
            raise OpenReviewAuthError("OpenReview 用户名和密码不能为空。")
        client = self._build_sdk_client()
        self._login_user(client, normalized_username, password)
        token = normalize_whitespace(str(getattr(client, "token", "") or ""))
        if not token:
            raise OpenReviewAuthError("OpenReview 登录失败，未返回可用 token。")
        if self.auth_store is None:
            raise OpenReviewAuthError("未配置本地认证存储路径，无法保存 OpenReview 登录信息。")
        credentials = self.auth_store.save(normalized_username, token)
        return {
            "authenticated": True,
            "username": credentials.username,
            "saved_at": credentials.saved_at,
        }

    def logout(self) -> dict[str, object]:
        if self.auth_store is not None:
            self.auth_store.clear()
        return {
            "authenticated": False,
            "username": "",
            "saved_at": "",
        }

    def search(self, query: str, max_results: int = 5) -> list[Paper]:
        client = self._authenticated_client()
        normalized = normalize_whitespace(query)
        if not normalized:
            return []
        notes = client.search_notes(term=normalized, content="title", source="all", limit=max_results)
        return [paper for paper in (self._parse_note(note) for note in notes) if paper is not None][:max_results]

    def resolve_reference(self, reference: str) -> Paper:
        client = self._authenticated_client()
        note_id = parse_openreview_id(reference) if "openreview" in reference.lower() or "forum?id=" in reference.lower() or "pdf?id=" in reference.lower() or " " not in reference.strip() else None
        if note_id:
            paper = self.fetch_note(note_id, client=client)
            if paper is not None:
                return paper

        candidates = self.search(reference, max_results=5)
        if not candidates:
            raise LookupError(f"Could not resolve OpenReview reference: {reference}")
        best = max(candidates, key=lambda item: title_similarity(reference, item.title))
        if title_similarity(reference, best.title) < 0.72:
            raise LookupError(f"Could not resolve OpenReview reference: {reference}")
        return best

    def fetch_note(self, note_id: str, *, client=None) -> Paper | None:
        active_client = client or self._authenticated_client()
        notes = active_client.get_notes(id=note_id)
        if not notes:
            return None
        return self._parse_note(notes[0])

    def download_pdf_bytes(self, paper: Paper) -> bytes:
        active_client = self._authenticated_client()
        note_id = paper.openreview_forum_id or paper.openreview_id
        if not note_id:
            raise ValueError(f"No OpenReview note id available for {paper.title}")
        return active_client.get_attachment("pdf", id=note_id)

    def enrich_metadata(self, paper: Paper) -> Paper:
        note_id = paper.openreview_id or paper.openreview_forum_id or ""
        resolved = self.fetch_note(note_id) if note_id else None
        if resolved is None:
            try:
                resolved = self.resolve_reference(paper.title)
            except LookupError:
                return paper
        return resolved

    def _authenticated_client(self):
        if not self._is_client_available():
            raise OpenReviewClientUnavailableError("openreview-py 未安装，无法访问 OpenReview。")
        credentials = self.auth_store.load() if self.auth_store is not None else None
        if credentials is None:
            raise OpenReviewAuthError("OpenReview 未登录，已跳过该来源。")
        client = self._build_sdk_client()
        self._attach_token(client, credentials.token)
        return client

    @staticmethod
    def _is_client_available() -> bool:
        try:
            import openreview  # noqa: F401
        except Exception:
            return False
        return True

    @staticmethod
    def _default_client_factory(**kwargs):
        import openreview

        return openreview.api.OpenReviewClient(**kwargs)

    def _build_sdk_client(self):
        client = self._client_factory(baseurl=self.api_base_url)
        self._configure_client_session(client)
        return client

    def _configure_client_session(self, client: object) -> None:
        session = getattr(client, "session", None)
        if session is None:
            return
        if hasattr(session, "trust_env"):
            session.trust_env = False
        if not hasattr(session, "proxies"):
            return
        session.proxies.clear()
        if not self.proxy_url:
            return
        session.proxies.update({
            "http": self.proxy_url,
            "https": self.proxy_url,
        })

    @staticmethod
    def _attach_token(client: object, token: str) -> None:
        normalized_token = normalize_whitespace(token).removeprefix("Bearer ").strip()
        if not normalized_token:
            raise OpenReviewAuthError("本地保存的 OpenReview token 为空，请重新登录。")
        setattr(client, "token", normalized_token)
        headers = getattr(client, "headers", None)
        if isinstance(headers, dict):
            headers["Authorization"] = "Bearer " + normalized_token

    @staticmethod
    def _login_user(client: object, username: str, password: str) -> None:
        login_user = getattr(client, "login_user", None)
        if not callable(login_user):
            raise OpenReviewAuthError("当前 OpenReview 客户端不支持登录。")
        login_user(username, password)

    def _parse_note(self, note: object) -> Paper | None:
        content = self._note_content(note)
        note_id = normalize_whitespace(self._get_value(note, "id"))
        forum_id = normalize_whitespace(self._get_value(note, "forum")) or note_id
        title = self._unwrap(content.get("title"))
        if not title:
            return None
        abstract = self._unwrap(content.get("abstract"))
        authors = self._unwrap_list(content.get("authors"))
        venue_name = self._unwrap(content.get("venue")) or self._unwrap(content.get("venueid"))
        venue_year = self._extract_year(venue_name) or self._timestamp_year(self._get_value(note, "cdate")) or self._timestamp_year(self._get_value(note, "pdate"))
        venue = VenueInfo(name=venue_name, kind=self._guess_venue_kind(venue_name), year=venue_year)
        categories = self._unwrap_list(content.get("keywords"))
        pdf_target = forum_id or note_id
        paper_url = f"{self.web_base_url}/forum?id={forum_id or note_id}"
        pdf_url = f"{self.web_base_url}/pdf?id={pdf_target}" if pdf_target else ""
        published = self._format_timestamp(self._get_value(note, "pdate") or self._get_value(note, "cdate"))
        updated = self._format_timestamp(self._get_value(note, "mdate") or self._get_value(note, "tcdate") or self._get_value(note, "cdate"))
        doi = self._extract_doi(content)
        return Paper(
            paper_id=f"openreview:{forum_id or note_id}",
            source_primary="openreview",
            title=title,
            abstract=abstract,
            authors=authors,
            published=published,
            updated=updated,
            entry_id=paper_url,
            entry_url=paper_url,
            pdf_url=pdf_url,
            primary_category="openreview",
            categories=categories,
            openreview_id=note_id,
            openreview_forum_id=forum_id,
            doi=doi,
            openreview_url=paper_url,
            venue=venue,
        )

    @staticmethod
    def _note_content(note: object) -> dict:
        content = getattr(note, "content", None)
        if isinstance(content, dict):
            return content
        return {}

    @staticmethod
    def _get_value(note: object, field_name: str) -> object:
        return getattr(note, field_name, None)

    @staticmethod
    def _unwrap(value: object) -> str:
        if isinstance(value, dict):
            if "value" in value:
                return OpenReviewClient._unwrap(value["value"])
            return ""
        if isinstance(value, list):
            return normalize_whitespace(" ".join(str(item) for item in value))
        return normalize_whitespace(str(value or ""))

    @staticmethod
    def _unwrap_list(value: object) -> list[str]:
        if isinstance(value, dict) and "value" in value:
            return OpenReviewClient._unwrap_list(value["value"])
        if isinstance(value, list):
            return [normalize_whitespace(str(item)) for item in value if normalize_whitespace(str(item))]
        if normalize_whitespace(str(value or "")):
            return [normalize_whitespace(str(value))]
        return []

    @staticmethod
    def _extract_year(text: str) -> int | None:
        import re

        match = re.search(r"(19|20)\d{2}", text or "")
        return int(match.group(0)) if match else None

    @staticmethod
    def _guess_venue_kind(venue_name: str) -> str:
        lowered = normalize_whitespace(venue_name).casefold()
        if not lowered:
            return ""
        if any(token in lowered for token in ("journal", "transactions", "letters", "revue")):
            return "journal"
        if any(token in lowered for token in ("conference", "workshop", "symposium", "iclr", "neurips", "icml", "acl", "emnlp", "cvpr")):
            return "conference"
        return "venue"

    @staticmethod
    def _timestamp_year(value: object) -> int | None:
        iso = OpenReviewClient._format_timestamp(value)
        if len(iso) >= 4 and iso[:4].isdigit():
            return int(iso[:4])
        return None

    @staticmethod
    def _format_timestamp(value: object) -> str:
        if value in (None, ""):
            return ""
        try:
            timestamp = int(value) / 1000
        except (TypeError, ValueError):
            return normalize_whitespace(str(value))
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def _extract_doi(content: dict) -> str:
        candidates = [
            OpenReviewClient._unwrap(content.get("doi")),
            OpenReviewClient._unwrap(content.get("paperhash")),
        ]
        for candidate in candidates:
            if candidate.startswith("10."):
                return candidate
        return ""
