from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from autopapers.openreview import OpenReviewAuthError, OpenReviewClient
from autopapers.openreview_auth import OpenReviewAuthStore


class FakeNote:
    def __init__(self) -> None:
        self.id = "note123"
        self.forum = "forum123"
        self.cdate = 1711929600000
        self.mdate = 1712016000000
        self.pdate = 1711929600000
        self.content = {
            "title": {"value": "Calibrated Test-Time Scaling"},
            "abstract": {"value": "We study verifier-aware scaling on OpenReview."},
            "authors": {"value": ["Alice", "Bob"]},
            "venue": {"value": "ICLR 2026"},
            "keywords": {"value": ["test-time scaling", "verifier"]},
            "doi": {"value": "10.5555/test-time-scaling"},
        }


class FakeOpenReviewSDKClient:
    def __init__(self, *, token: str = "", notes: list[FakeNote] | None = None, **kwargs) -> None:
        self.token = token
        self._notes = notes or []
        self.session = type("Session", (), {"proxies": {}, "trust_env": True})()
        self.headers = {}

    def search_notes(self, **kwargs):
        return list(self._notes)

    def get_notes(self, **kwargs):
        return list(self._notes)

    def get_attachment(self, field_name: str, id: str | None = None):
        return b"%PDF-1.4 fake"

    def login_user(self, username=None, password=None, expiresIn=None):
        if username and password:
            self.token = "token-abc"
            self.headers["Authorization"] = "Bearer token-abc"
            return {"token": self.token}
        raise AssertionError("unexpected credentials")


class OpenReviewClientTests(unittest.TestCase):
    def test_auth_status_reflects_saved_credentials(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = OpenReviewAuthStore(Path(tmp_dir) / ".autopapers" / "openreview-auth.json")
            store.save("alice@example.com", "token-123")
            client = OpenReviewClient(auth_store=store, client_factory=lambda **kwargs: FakeOpenReviewSDKClient(**kwargs))

            status = client.auth_status()

            self.assertTrue(status["authenticated"])
            self.assertEqual(status["username"], "alice@example.com")

    def test_login_saves_token_locally(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = OpenReviewAuthStore(Path(tmp_dir) / ".autopapers" / "openreview-auth.json")

            def factory(**kwargs):
                return FakeOpenReviewSDKClient(**kwargs)

            client = OpenReviewClient(auth_store=store, client_factory=factory)

            payload = client.login("alice@example.com", "secret")

            self.assertTrue(payload["authenticated"])
            self.assertEqual(store.load().token, "token-abc")

    def test_search_requires_authentication(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = OpenReviewAuthStore(Path(tmp_dir) / ".autopapers" / "openreview-auth.json")
            client = OpenReviewClient(auth_store=store, client_factory=lambda **kwargs: FakeOpenReviewSDKClient(**kwargs))

            with self.assertRaises(OpenReviewAuthError):
                client.search("cats", max_results=5)

    def test_search_maps_openreview_note_into_canonical_paper(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = OpenReviewAuthStore(Path(tmp_dir) / ".autopapers" / "openreview-auth.json")
            store.save("alice@example.com", "token-123")
            note = FakeNote()
            client = OpenReviewClient(
                auth_store=store,
                client_factory=lambda **kwargs: FakeOpenReviewSDKClient(token=kwargs.get("token", ""), notes=[note]),
            )

            papers = client.search("test-time scaling", max_results=5)

            self.assertEqual(len(papers), 1)
            paper = papers[0]
            self.assertEqual(paper.paper_id, "openreview:forum123")
            self.assertEqual(paper.source_primary, "openreview")
            self.assertEqual(paper.openreview_id, "note123")
            self.assertEqual(paper.openreview_forum_id, "forum123")
            self.assertEqual(paper.venue.name, "ICLR 2026")
            self.assertEqual(paper.venue.kind, "conference")
            self.assertEqual(paper.venue.year, 2026)
            self.assertEqual(paper.doi, "10.5555/test-time-scaling")
            self.assertIn("/pdf?id=forum123", paper.pdf_url)
