from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from autopapers.config import Settings


class ConfigTests(unittest.TestCase):
    def test_from_env_reads_network_proxy_url(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "MINIMAX_API_KEY=test-key",
                        "AUTOPAPERS_HTTP_PROXY=http://127.0.0.1:7890",
                    ]
                ),
                encoding="utf-8",
            )

            settings = Settings.from_env(root)

            self.assertEqual(settings.network_proxy_url, "http://127.0.0.1:7890")

    def test_from_env_keeps_base_values_when_active_profile_fields_are_blank(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "MINIMAX_API_KEY=test-key",
                        "MINIMAX_MODEL=MiniMax-M2.7",
                        "AUTOPAPERS_HTTP_PROXY=http://127.0.0.1:7890",
                    ]
                ),
                encoding="utf-8",
            )
            (root / ".autopapers").mkdir(parents=True, exist_ok=True)
            (root / ".autopapers" / "web-settings.json").write_text(
                (
                    "{\n"
                    '  "active_profile": "blank",\n'
                    '  "profiles": {\n'
                    '    "blank": {\n'
                    '      "name": "Blank Override",\n'
                    '      "api_key": "",\n'
                    '      "model": "",\n'
                    '      "api_url": "",\n'
                    '      "network_proxy_url": ""\n'
                    "    }\n"
                    "  }\n"
                    "}\n"
                ),
                encoding="utf-8",
            )

            settings = Settings.from_env(root)

            self.assertEqual(settings.api_key, "test-key")
            self.assertEqual(settings.model, "MiniMax-M2.7")
            self.assertEqual(settings.network_proxy_url, "http://127.0.0.1:7890")

    def test_activate_profile_resets_to_base_values_before_overlay(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            settings = Settings(
                repo_root=root,
                api_key="base-key",
                model="BaseModel",
                api_url="https://api.base.test/v1",
                library_root=root / "library",
                reports_root=root / "reports",
                default_max_results=5,
                request_timeout=30,
                pdf_max_pages=18,
                pdf_max_chars=45000,
                web_host="127.0.0.1",
                web_port=8765,
                network_proxy_url="http://127.0.0.1:7890",
            )

            first = settings.save_profile(
                None,
                {
                    "name": "First",
                    "api_key": "first-key",
                    "model": "FirstModel",
                    "api_url": "https://api.first.test/v1",
                    "network_proxy_url": "http://127.0.0.1:9000",
                },
            )
            self.assertEqual(settings.model, "FirstModel")
            self.assertEqual(settings.network_proxy_url, "http://127.0.0.1:9000")

            second = settings.save_profile(
                None,
                {
                    "name": "Fallback",
                    "api_key": "",
                    "model": "",
                    "api_url": "",
                    "network_proxy_url": "",
                },
            )
            self.assertEqual(second["active_profile"], second["saved_id"])
            self.assertEqual(settings.api_key, "base-key")
            self.assertEqual(settings.model, "BaseModel")
            self.assertEqual(settings.api_url, "https://api.base.test/v1")
            self.assertEqual(settings.network_proxy_url, "http://127.0.0.1:7890")

            settings.activate_profile(first["saved_id"])
            self.assertEqual(settings.model, "FirstModel")
            self.assertEqual(settings.network_proxy_url, "http://127.0.0.1:9000")

            settings.activate_profile(second["saved_id"])
            self.assertEqual(settings.api_key, "base-key")
            self.assertEqual(settings.model, "BaseModel")
            self.assertEqual(settings.api_url, "https://api.base.test/v1")
            self.assertEqual(settings.network_proxy_url, "http://127.0.0.1:7890")

    def test_save_profile_preserves_existing_api_key_when_blank_on_update(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            settings = Settings(
                repo_root=root,
                api_key="",
                model="MiniMax-M2.7",
                api_url="https://api.minimaxi.com/v1/text/chatcompletion_v2",
                library_root=root / "library",
                reports_root=root / "reports",
                default_max_results=5,
                request_timeout=30,
                pdf_max_pages=18,
                pdf_max_chars=45000,
                web_host="127.0.0.1",
                web_port=8765,
            )

            created = settings.save_profile(
                None,
                {
                    "name": "Primary",
                    "api_key": "sk-test-12345678",
                    "model": "TestModel",
                    "api_url": "https://api.test.com/v1",
                    "network_proxy_url": "",
                },
            )

            settings.save_profile(
                created["saved_id"],
                {
                    "name": "Primary Updated",
                    "api_key": "",
                    "model": "TestModelV2",
                    "api_url": "https://api.test.com/v2",
                    "network_proxy_url": "http://127.0.0.1:7890",
                },
            )

            profiles = settings._read_stored_data()["profiles"]
            self.assertEqual(profiles[created["saved_id"]]["api_key"], "sk-test-12345678")
            self.assertEqual(settings.api_key, "sk-test-12345678")
            self.assertEqual(settings.model, "TestModelV2")
            self.assertEqual(settings.api_url, "https://api.test.com/v2")
            self.assertEqual(settings.network_proxy_url, "http://127.0.0.1:7890")

    def test_from_env_uses_expanded_pdf_defaults(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            settings = Settings.from_env(root)

            self.assertEqual(settings.pdf_max_pages, 18)
            self.assertEqual(settings.pdf_max_chars, 45000)
