from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from autopapers.openreview_auth import OpenReviewAuthStore


class OpenReviewAuthStoreTests(unittest.TestCase):
    def test_save_load_and_clear_credentials(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / ".autopapers" / "openreview-auth.json"
            store = OpenReviewAuthStore(path)

            saved = store.save("alice@example.com", "token-123")
            loaded = store.load()

            self.assertEqual(saved.username, "alice@example.com")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.token, "token-123")

            store.clear()
            self.assertIsNone(store.load())
