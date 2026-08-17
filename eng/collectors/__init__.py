"""Collector registry and runner.

Collectors run in parallel threads because they are almost pure network wait.
A collector that throws, times out, or returns nothing is reported and skipped
— one dead board never takes down the run.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from ..models import Job
from . import html_boards, json_apis, rss, telegram

KINDS = {
    "json_api": json_apis.collect,
    "rss": rss.collect,
    "html": html_boards.collect,
    "telegram": telegram.collect,
}

MAX_WORKERS = 8


def run_one(src: dict) -> tuple[str, list[Job], str]:
    """Returns (source id, jobs, error message)."""
    handler = KINDS.get(src.get("kind", ""))
    if not handler:
        return src["id"], [], f"unknown kind: {src.get('kind')}"
    try:
        return src["id"], handler(src), ""
    except Exception as exc:
        return src["id"], [], f"{type(exc).__name__}: {exc}"


def collect_all(sources: list[dict], verbose: bool = True) -> tuple[list[Job], dict]:
    active = [s for s in sources if s.get("enabled", True)]
    jobs: list[Job] = []
    report: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(run_one, s): s for s in active}
        for future in as_completed(futures):
            src_id, found, error = future.result()
            report[src_id] = {"count": len(found), "error": error}
            jobs.extend(found)
            if verbose:
                if error:
                    print(f"  {src_id:<22} FAILED  {error[:60]}")
                elif not found:
                    print(f"  {src_id:<22} 0 jobs  (selector may need tuning)")
                else:
                    print(f"  {src_id:<22} {len(found)} jobs")

    return jobs, report
