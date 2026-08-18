#!/usr/bin/env python
"""ENG Job Engine — one run collects, verifies, sorts and publishes the day's board.

    python run.py                 full run, writes site/index.html
    python run.py --no-verify     skip link checking (fast, for testing layout)
    python run.py --dry           collect and report, write nothing
    python run.py --open          open the page in your browser when done
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from datetime import date
from pathlib import Path

from eng import buckets as bucketing
from eng import config as cfg
from eng import verify as verifier
from eng.classify import Classifier
from eng.collectors import collect_all
from eng.llm import Groq
from eng.publish import write
from eng.store import Store

ROOT = Path(__file__).resolve().parent


def rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build today's ENG job board.")
    ap.add_argument("--no-verify", action="store_true", help="skip link verification")
    ap.add_argument("--dry", action="store_true", help="report only, write nothing")
    ap.add_argument("--open", action="store_true", help="open the page when finished")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg.load_env()
    config = cfg.load(args.config)
    today = date.today().isoformat()

    print(f"ENG Job Engine — {today}")

    # 1. Collect ------------------------------------------------------------
    rule("Collecting")
    raw, source_report = collect_all(config["sources"])
    print(f"\n  {len(raw)} raw postings from "
          f"{sum(1 for r in source_report.values() if r['count'])} live sources")

    live = [s for s, r in source_report.items() if r["count"]]
    dead = [s for s, r in source_report.items() if not r["count"]]
    if dead:
        print(f"  quiet: {', '.join(dead)}")

    if not raw:
        print("\nNothing collected. Run `python -m eng.doctor` to find out why.")
        return 1

    # 2. Dedup against everything ever seen ---------------------------------
    rule("Deduplicating")
    store = Store(ROOT / "jobs.db")
    seen_before = store.known_fingerprints()

    unique: list = []
    picked: set[str] = set()
    for job in raw:
        if job.fingerprint in picked:
            continue          # duplicate inside this run
        picked.add(job.fingerprint)
        if job.fingerprint in seen_before:
            continue          # already shared on a previous day
        unique.append(job)

    print(f"  {len(unique)} genuinely new "
          f"({len(raw) - len(unique)} duplicates or already published)")

    # 3. Gate and classify --------------------------------------------------
    rule("Classifying")
    llm = Groq()
    if llm.enabled:
        print(f"  AI enabled: Groq / {llm.model} (ambiguous jobs only)")
    else:
        print("  AI disabled (no GROQ_API_KEY) — running on rules alone")

    classifier = Classifier(config, llm)
    classified = classifier.run(unique)
    c = classifier.counters
    print(f"  dropped: {c['scam']} scam-gated, {c['not_tech']} non-tech, "
          f"{c['unclassified']} unclassifiable")
    print(f"  sorted:  {c['by_rule']} by rules, {c['by_ai']} by AI")
    if llm.enabled:
        print(f"  AI calls: {llm.calls} ok, {llm.failures} failed  [{llm.error_summary()}]")

    # 4. Verify -------------------------------------------------------------
    if args.no_verify:
        alive = classified
        print("\n  verification skipped (--no-verify)")
    else:
        rule("Verifying links")
        max_age = int(config.get("rules", {}).get("max_age_days", 14))
        alive, vstats = verifier.verify(classified, max_age)
        print(f"  {len(alive)} open  "
              f"(dropped {vstats['dropped_dead']} dead, {vstats['dropped_age']} too old)")

    # 4b. Descriptions — after verification, so we can reuse the pages it fetched
    rule("Writing descriptions")
    before = sum(1 for j in alive if len(j.description) < 60)
    classifier.describe(alive)
    print(f"  {len(alive) - before} came with a real description from the source")
    print(f"  {before} needed one written")

    # 5. Fill the buckets ---------------------------------------------------
    rule("Today's board")
    board, report = bucketing.fill(alive, config, store)
    total = sum(len(v) for v in board.values())

    for key, r in report.items():
        flag = "  <- thin" if r["short"] else ""
        carried = f", {r['carried']} carried forward" if r["carried"] else ""
        print(f"  {r['label']:<18} {r['count']}/{r['target']}"
              f"   (pool {r['available']}{carried}){flag}")
    print(f"\n  {total} roles total")

    if args.dry:
        print("\nDry run — nothing written.")
        store.close()
        return 0

    # 6. Persist and publish ------------------------------------------------
    for job in alive:
        store.upsert(job)
    store.mark_published([j.fingerprint for v in board.values() for j in v], today)

    dated, index = write(board, config, ROOT / "site", today)
    rule("Published")
    print(f"  {index}")
    print(f"  {dated}")
    print(f"  database: {store.stats()['total_seen']} jobs known, "
          f"{store.stats()['published']} published all-time")
    store.close()

    if args.open:
        webbrowser.open(index.as_uri())

    print("\nOpen the page and press \"Share to WhatsApp\".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
