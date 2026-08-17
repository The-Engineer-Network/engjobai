"""Global job boards that expose a free JSON API.

Each board shapes its payload differently, so there is one small adapter per
board. These are the highest-value collectors in the project: no scraping, no
markup to break, and together they cover the global half of every track.
"""

from __future__ import annotations

from ..models import Job, clean
from .base import fetch


def _job(src: dict, **kw) -> Job:
    return Job(source=src["id"], scope=src.get("scope", "global"),
               attribution=src.get("attribution", ""),
               attribution_url=src.get("attribution_url", ""), **kw)


def _remoteok(data, src) -> list[Job]:
    out = []
    for row in data or []:
        # The first element is RemoteOK's legal/terms notice, not a job.
        if not isinstance(row, dict) or not row.get("position"):
            continue
        out.append(_job(
            src,
            title=row.get("position", ""),
            company=row.get("company", ""),
            url=row.get("url") or row.get("apply_url", ""),
            location=row.get("location", "") or "Remote",
            description=clean(row.get("description", ""), 400),
            posted_at=row.get("date", ""),
            salary=_salary(row.get("salary_min"), row.get("salary_max")),
            tags=[str(t) for t in (row.get("tags") or [])][:8],
            remote=True,
        ))
    return out


def _remotive(data, src) -> list[Job]:
    return [_job(
        src,
        title=r.get("title", ""),
        company=r.get("company_name", ""),
        url=r.get("url", ""),
        location=r.get("candidate_required_location", "") or "Remote",
        description=clean(r.get("description", ""), 400),
        posted_at=r.get("publication_date", ""),
        salary=r.get("salary", "") or "",
        tags=[str(t) for t in (r.get("tags") or [])][:8],
        remote=True,
    ) for r in (data or {}).get("jobs", []) if r.get("title")]


def _himalayas(data, src) -> list[Job]:
    out = []
    for r in (data or {}).get("jobs", []):
        if not r.get("title"):
            continue
        locs = r.get("locationRestrictions") or []
        out.append(_job(
            src,
            title=r.get("title", ""),
            company=r.get("companyName", ""),
            url=r.get("applicationLink") or r.get("guid", ""),
            location=", ".join(str(l) for l in locs[:3]) or "Remote",
            description=clean(r.get("excerpt") or r.get("description", ""), 400),
            posted_at=r.get("pubDate", ""),
            tags=[str(t) for t in (r.get("categories") or [])][:8],
            remote=True,
        ))
    return out


def _arbeitnow(data, src) -> list[Job]:
    return [_job(
        src,
        title=r.get("title", ""),
        company=r.get("company_name", ""),
        url=r.get("url", ""),
        location=r.get("location", ""),
        description=clean(r.get("description", ""), 400),
        posted_at=str(r.get("created_at", "")),
        tags=[str(t) for t in (r.get("tags") or [])][:8],
        remote=bool(r.get("remote")),
    ) for r in (data or {}).get("data", []) if r.get("title")]


def _jobicy(data, src) -> list[Job]:
    return [_job(
        src,
        title=r.get("jobTitle", ""),
        company=r.get("companyName", ""),
        url=r.get("url", ""),
        location=r.get("jobGeo", "") or "Remote",
        description=clean(r.get("jobExcerpt") or r.get("jobDescription", ""), 400),
        posted_at=r.get("pubDate", ""),
        salary=_salary(r.get("annualSalaryMin"), r.get("annualSalaryMax"),
                       r.get("salaryCurrency", "USD")),
        tags=[str(t) for t in (r.get("jobIndustry") or [])][:8],
        remote=True,
    ) for r in (data or {}).get("jobs", []) if r.get("jobTitle")]


def _workingnomads(data, src) -> list[Job]:
    return [_job(
        src,
        title=r.get("title", ""),
        company=r.get("company_name", ""),
        url=r.get("url", ""),
        location=r.get("location", "") or "Remote",
        description=clean(r.get("description", ""), 400),
        posted_at=r.get("pub_date", ""),
        tags=[t.strip() for t in str(r.get("tags", "")).split(",") if t.strip()][:8],
        remote=True,
    ) for r in (data or []) if isinstance(r, dict) and r.get("title")]


def _salary(lo, hi, cur: str = "USD") -> str:
    try:
        lo, hi = int(lo or 0), int(hi or 0)
    except (TypeError, ValueError):
        return ""
    if lo and hi:
        return f"{cur} {lo:,} – {hi:,}"
    if lo:
        return f"{cur} {lo:,}+"
    return ""


ADAPTERS = {
    "remoteok": _remoteok,
    "remotive": _remotive,
    "himalayas": _himalayas,
    "arbeitnow": _arbeitnow,
    "jobicy": _jobicy,
    "workingnomads": _workingnomads,
}


def collect(src: dict) -> list[Job]:
    adapter = ADAPTERS.get(src["id"])
    if not adapter:
        return []
    data = fetch(src["url"], as_json=True)
    if data is None:
        return []
    try:
        return [j for j in adapter(data, src) if j.title and j.url]
    except Exception:
        return []
