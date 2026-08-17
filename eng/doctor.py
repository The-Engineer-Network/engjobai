"""Source health check.

    python -m eng.doctor

Tests every source and prints what it returned. Run this whenever the digest
gets thin — a board that redesigned its markup shows up here as "0 jobs", and
the fix is a selector edit in config.yaml, not a code change.
"""

from __future__ import annotations

import sys

from . import config as cfg
from .collectors import run_one


def main() -> int:
    cfg.load_env()
    config = cfg.load()
    sources = config["sources"]

    print(f"Checking {len(sources)} sources\n")
    print(f"  {'SOURCE':<24}{'KIND':<10}{'SCOPE':<10}RESULT")
    print("  " + "-" * 66)

    alive = thin = broken = 0
    samples: list[str] = []

    for src in sources:
        if not src.get("enabled", True):
            print(f"  {src['id']:<24}{src.get('kind',''):<10}"
                  f"{src.get('scope',''):<10}disabled")
            continue

        _, jobs, error = run_one(src)
        kind = src.get("kind", "")
        scope = src.get("scope", "")

        if error:
            broken += 1
            status = f"ERROR  {error[:34]}"
        elif not jobs:
            thin += 1
            status = "0 jobs  <- check selectors / URL"
        else:
            alive += 1
            status = f"{len(jobs)} jobs"
            samples.append(f"    [{src['id']}] {jobs[0].title[:62]}")

        print(f"  {src['id']:<24}{kind:<10}{scope:<10}{status}")

    print("\n  " + "-" * 66)
    print(f"  {alive} returning data · {thin} empty · {broken} erroring")

    if samples:
        print("\n  Sample titles from each live source:")
        for line in samples:
            print(line)

    if thin or broken:
        print("\n  Empty or erroring sources are safe to leave enabled — the run "
              "\n  skips them. To silence one, set `enabled: false` in config.yaml.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
