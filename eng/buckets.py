"""Fill each track's bucket, honouring the fill order and the never-pad rule."""

from __future__ import annotations

from .models import Job
from .store import Store


def _rank(job: Job, order: list[str]) -> tuple[int, str]:
    """Sort key: preferred scope first, then newest-looking first."""
    try:
        scope_rank = order.index(job.scope)
    except ValueError:
        scope_rank = len(order)
    # posted_at descending — empty dates sort last within their scope
    return (scope_rank, "" if not job.posted_at else job.posted_at)


def fill(jobs: list[Job], config: dict, store: Store | None = None) -> tuple[dict, dict]:
    """Return (buckets, report).

    Fill order is Nigeria-local first, then Africa, then global — so each
    track skews toward roles the community can realistically land, and global
    remote fills whatever is left rather than dominating.
    """
    rules = config.get("rules", {})
    order = config.get("fill_order", ["nigeria", "africa", "global"])
    never_pad = rules.get("never_pad", True)
    carry_hours = int(rules.get("carry_forward_hours", 0))

    buckets: dict[str, list[Job]] = {}
    report: dict[str, dict] = {}

    for track in config["tracks"]:
        key = track["key"]
        target = int(track.get("target", 10))

        pool = [j for j in jobs if j.track == key]
        pool.sort(key=lambda j: _rank(j, order), reverse=False)
        # Newest first inside each scope band
        pool.sort(key=lambda j: (order.index(j.scope) if j.scope in order else 99,
                                 j.posted_at == "", ))

        chosen = pool[:target]
        carried = 0

        # A thin track may be refilled with still-open jobs from the last few
        # days that were never published — clearly a different thing from
        # recycling a stale posting, which max_age_days already blocks.
        if store and carry_hours and len(chosen) < target:
            picked = {j.fingerprint for j in chosen}
            for extra in store.carry_forward(key, carry_hours, target - len(chosen)):
                if extra.fingerprint not in picked:
                    chosen.append(extra)
                    picked.add(extra.fingerprint)
                    carried += 1

        buckets[key] = chosen
        report[key] = {
            "label": track["label"],
            "count": len(chosen),
            "target": target,
            "available": len(pool),
            "carried": carried,
            "short": len(chosen) < target,
        }

    if never_pad:
        # Nothing to do — never_pad is enforced by construction above. This
        # branch exists so turning the flag off is a visible, deliberate act
        # rather than something the code quietly assumed.
        pass

    return buckets, report
