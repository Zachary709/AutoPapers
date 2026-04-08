from __future__ import annotations

import urllib.request


def build_url_opener(proxy_url: str = "") -> urllib.request.OpenerDirector:
    normalized = proxy_url.strip()
    proxies = (
        {
            "http": normalized,
            "https": normalized,
        }
        if normalized
        else {
            "http": None,
            "https": None,
        }
    )
    return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
