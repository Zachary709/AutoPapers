from __future__ import annotations

import unittest
import urllib.request

from autopapers.http_client import build_url_opener


class HttpClientTests(unittest.TestCase):
    def test_build_url_opener_disables_env_proxies_by_default(self) -> None:
        opener = build_url_opener()
        self.assertFalse(
            any(isinstance(handler, urllib.request.ProxyHandler) for handler in opener.handlers)
        )

    def test_build_url_opener_applies_same_proxy_to_http_and_https(self) -> None:
        opener = build_url_opener("http://127.0.0.1:7890")
        proxy_handler = next(
            handler for handler in opener.handlers if isinstance(handler, urllib.request.ProxyHandler)
        )
        self.assertEqual(
            proxy_handler.proxies,
            {
                "http": "http://127.0.0.1:7890",
                "https": "http://127.0.0.1:7890",
            },
        )
