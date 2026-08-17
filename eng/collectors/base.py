"""Shared HTTP plumbing for every collector."""

from __future__ import annotations

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

TIMEOUT = 40.0


def fetch(url: str, as_json: bool = False):
    """GET a URL. Returns text, parsed JSON, or None. Never raises."""
    try:
        r = httpx.get(
            url,
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": UA,
                "Accept": "application/json, text/html, application/xml;q=0.9, */*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        r.raise_for_status()
        return r.json() if as_json else r.text
    except Exception:
        return None


def absolute(base: str, href: str) -> str:
    """Turn a possibly-relative href into an absolute URL."""
    if not href:
        return ""
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("//"):
        return "https:" + href
    return base.rstrip("/") + "/" + href.lstrip("/")
