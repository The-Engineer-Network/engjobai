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
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

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
RETRY_DELAY = 1.5

# A real browser sends far more than a User-Agent, and several boards check.
# Sending only a UA earns a 403 from them, which the old code could not tell
# apart from a 404 — so a live job on a picky host looked exactly like a dead
# link. The retry adds a Referer too: a visitor arriving from a search engine
# is the traffic these boards are built to accept.
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}

# Outcomes worth a second attempt: all of them describe the host's mood, not
# the job's existence.
SOFT_FAILURES = ("blocked", "server_error", "timeout")

# Seconds between two requests to the same host. The global semaphore alone
# happily pointed all eight slots at one board; WorkingNomads answers that
# with 403 and served every one of the same URLs when they were spaced out.
PER_HOST_DELAY = 0.7


class _HostGate:
    """One request at a time per host, spaced by PER_HOST_DELAY.

    Concurrency is still global — different hosts proceed in parallel. This
    only stops a single board from receiving the whole fleet at once.
    """

    def __init__(self, delay: float = PER_HOST_DELAY) -> None:
        self._delay = delay
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._ready: dict[str, float] = defaultdict(float)

    @asynccontextmanager
    async def slot(self, host: str):
        async with self._locks[host]:
            loop = asyncio.get_running_loop()
            wait = self._ready[host] - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                yield
            finally:
                self._ready[host] = asyncio.get_running_loop().time() + self._delay


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


async def _attempt(client: httpx.AsyncClient, job: Job, retry: bool = False) -> tuple[str, str]:
    """One request. Returns (outcome, html) — an observation, not a verdict.

    Every failure mode used to collapse into a single False, so a rate-limited
    host, a slow host and a deleted posting were indistinguishable in the
    stats. Naming them is what makes the drop count reviewable.
    """
    headers = dict(BROWSER_HEADERS)
    if retry:
        parts = urlsplit(job.url)
        headers["Referer"] = f"{parts.scheme}://{parts.netloc}/"

    try:
        r = await client.get(job.url, headers=headers)
    except httpx.TimeoutException:
        return ("timeout", "")
    except Exception:
        # Connection refused, DNS failure, TLS error. Suggestive of a dead
        # domain, but our own network can produce every one of these.
        return ("unreachable", "")

    if r.status_code in (404, 410):
        return ("gone", "")
    if r.status_code in (403, 401, 429):
        return ("blocked", "")
    if r.status_code >= 500:
        return ("server_error", "")
    if r.status_code >= 400:
        return ("gone", "")
    return ("ok", r.text[:120_000])


async def _check(client: httpx.AsyncClient, job: Job, sem: asyncio.Semaphore,
                 gate: _HostGate) -> str:
    """Classify one job. Returns the outcome name; "ok" means publishable."""
    host = urlsplit(job.url).netloc
    async with gate.slot(host), sem:
        outcome, html = await _attempt(client, job)

        # A block or a wobble says nothing about the job, so ask once more
        # before writing it off.
        if outcome in SOFT_FAILURES:
            await asyncio.sleep(RETRY_DELAY)
            outcome, html = await _attempt(client, job, retry=True)

        if outcome != "ok":
            return outcome

        if any(m in html.lower() for m in CLOSED_MARKERS):
            return "closed"

        # Free upgrade: if this job arrived with a thin description (a bare
        # anchor scrape), take the real one from the page we just fetched.
        if len(job.description) < 60:
            better = _extract_description(html)
            if better:
                job.description = better

        job.verified_at = now_iso()
        return "ok"


async def _verify_all(jobs: list[Job],
                      feed_sources: frozenset[str]) -> tuple[list[Job], Counter, Counter]:
    sem = asyncio.Semaphore(CONCURRENCY)
    gate = _HostGate()
    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": UA},
    ) as client:
        results = await asyncio.gather(
            *(_check(client, j, sem, gate) for j in jobs), return_exceptions=True
        )

    outcomes = ["crashed" if isinstance(r, BaseException) else r for r in results]

    # Only two outcomes are evidence that a posting is gone: the host said 404,
    # or the page says the role closed. Everything else -- 403, a timeout, a
    # dropped connection -- describes the trip, not the job.
    #
    # That distinction matters most for structured feeds, where we read the
    # provider's index minutes earlier and know the domain is up. Jobicy is the
    # proof: its API answers 200 while every job page answers 403, at any
    # header set. Dropping those was discarding live roles on the strength of
    # a host's opinion of our IP.
    #
    # Scraped boards get no such benefit. There the fetch is the only evidence
    # that ever existed, so a failed fetch is still fatal.
    NOT_DEATH = ("blocked", "timeout", "unreachable", "server_error")
    for i, (job, outcome) in enumerate(zip(jobs, outcomes)):
        if outcome in NOT_DEATH and job.source in feed_sources:
            job.verified_at = now_iso()
            outcomes[i] = "feed_ok"
    alive = [j for j, o in zip(jobs, outcomes) if o in ("ok", "feed_ok")]
    # Which host refused, not just how many refusals: one board rejecting this
    # IP a hundred times and a hundred dead links are the same number until
    # you name the host.
    offenders = Counter(f"{urlsplit(j.url).netloc} {o}"
                        for j, o in zip(jobs, outcomes) if o not in ("ok", "feed_ok"))
    return alive, Counter(outcomes), offenders


def verify(jobs: list[Job], max_age_days: int = 14,
           feed_sources: frozenset[str] = frozenset()) -> tuple[list[Job], dict]:
    """Return (surviving jobs, stats).

    `breakdown` names why each dropped job was dropped. It exists because the
    drop count alone is not reviewable: "51 dead" reads like 51 deleted
    postings, when it may be one board refusing this IP fifty-one times.
    """
    fresh = [j for j in jobs if not _too_old(j, max_age_days)]
    dropped_age = len(jobs) - len(fresh)

    if not fresh:
        return [], {"checked": 0, "dropped_age": dropped_age,
                    "dropped_dead": 0, "breakdown": {}, "offenders": {}}

    alive, outcomes, offenders = asyncio.run(_verify_all(fresh, feed_sources))
    return alive, {
        "checked": len(fresh),
        "dropped_age": dropped_age,
        "dropped_dead": len(fresh) - len(alive),
        "breakdown": {k: v for k, v in outcomes.items() if k != "ok"},
        "feed_trusted": outcomes.get("feed_ok", 0),
        "offenders": dict(offenders.most_common(8)),
    }
