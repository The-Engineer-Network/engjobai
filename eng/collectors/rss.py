"""RSS collector — currently We Work Remotely's four engineering categories.

WWR titles arrive as "Company: Job Title", so the company is split out here
rather than left glued to the front of every title on the page.
"""

from __future__ import annotations

import feedparser

from ..models import Job, clean
from .base import fetch


def collect(src: dict) -> list[Job]:
    raw = fetch(src["url"])
    if not raw:
        return []

    try:
        feed = feedparser.parse(raw)
    except Exception:
        return []

    jobs: list[Job] = []
    for entry in feed.entries:
        title = clean(getattr(entry, "title", ""))
        link = getattr(entry, "link", "")
        if not title or not link:
            continue

        company = ""
        if ":" in title:
            head, tail = title.split(":", 1)
            if len(head) < 60 and tail.strip():
                company, title = head.strip(), tail.strip()

        jobs.append(Job(
            title=title,
            company=company,
            url=link,
            source=src["id"],
            scope=src.get("scope", "global"),
            location=clean(getattr(entry, "region", "")) or "Remote",
            description=clean(getattr(entry, "summary", ""), 400),
            posted_at=getattr(entry, "published", "") or "",
            attribution=src.get("attribution", ""),
            attribution_url=src.get("attribution_url", ""),
            remote=True,
        ))
    return jobs
