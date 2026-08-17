"""Confirm a job is real and still open before it reaches the community.

This is what the word "verified" on the page actually means:

  * the apply URL resolves (no 404, no dead domain)
  * the landing page does not say the role is closed
  * the posting is not older than `rules.max_age_days`

Checks run concurrently because they are pure network wait. Anything that
fails is dropped, not downgraded — a broken link shared to 500 engineers is
worse than a shorter digest.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

import httpx

from .models import Job, clean, now_iso

# We already download every job page to check it is open, so we may as well
# read the description out of the same response instead of throwing it away.
# This is what gives anchor-scraped boards (Jobberman, Jobzilla) a real
# description without a single extra request or AI call.
META_DESC = re.compile(
    r'<meta[^>]+(?:property=["\']og:description["\']|name=["\']description["\'])'
    r'[^>]+content=["\']([^"\']{40,400})["\']',
    re.IGNORECASE,
)
META_DESC_REVERSED = re.compile(
    r'<meta[^>]+content=["\']([^"\']{40,400})["\'][^>]+'
    r'(?:property=["\']og:description["\']|name=["\']description["\'])',
    re.IGNORECASE,
)


def _extract_description(html: str) -> str:
    for pattern in (META_DESC, META_DESC_REVERSED):
        match = pattern.search(html)
        if match:
            text = clean(match.group(1), 400)
            # Skip boilerplate site taglines that say nothing about the role.
            if len(text) > 45 and "find latest jobs" not in text.lower():
                return text
    return ""

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

CLOSED_MARKERS = (
    "no longer accepting", "this job is closed", "position has been filled",
    "application closed", "job expired", "this vacancy is closed",
    "applications are closed", "no longer available", "posting has expired",
)

CONCURRENCY = 8
TIMEOUT = 20.0


def _too_old(job: Job, max_age_days: int) -> bool:
    if not job.posted_at:
        return False  # unknown date is not evidence of staleness
    try:
        stamp = datetime.fromisoformat(job.posted_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return stamp < datetime.now(timezone.utc) - timedelta(days=max_age_days)


async def _check(client: httpx.AsyncClient, job: Job, sem: asyncio.Semaphore) -> bool:
    async with sem:
        try:
            r = await client.get(job.url)
        except Exception:
            return False

        if r.status_code >= 400:
            return False

        html = r.text[:120_000]
        if any(m in html.lower() for m in CLOSED_MARKERS):
            return False

        # Free upgrade: if this job arrived with a thin description (a bare
        # anchor scrape), take the real one from the page we just fetched.
        if len(job.description) < 60:
            better = _extract_description(html)
            if better:
                job.description = better

        job.verified_at = now_iso()
        return True


async def _verify_all(jobs: list[Job]) -> list[Job]:
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": UA},
    ) as client:
        results = await asyncio.gather(
            *(_check(client, j, sem) for j in jobs), return_exceptions=True
        )
    return [j for j, ok in zip(jobs, results) if ok is True]


def verify(jobs: list[Job], max_age_days: int = 14) -> tuple[list[Job], dict]:
    """Return (surviving jobs, stats)."""
    fresh = [j for j in jobs if not _too_old(j, max_age_days)]
    dropped_age = len(jobs) - len(fresh)

    if not fresh:
        return [], {"checked": 0, "dropped_age": dropped_age, "dropped_dead": 0}

    alive = asyncio.run(_verify_all(fresh))
    return alive, {
        "checked": len(fresh),
        "dropped_age": dropped_age,
        "dropped_dead": len(fresh) - len(alive),
    }
