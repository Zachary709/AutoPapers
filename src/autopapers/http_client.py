from __future__ import annotations

import urllib.request


def build_url_opener(proxy_url: str = "") -> urllib.request.OpenerDirector:
    normalized = proxy_url.strip()
    proxies = {}
    if normalized:
        proxies = {
            "http": normalized,
            "https": normalized,
        }
    return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
