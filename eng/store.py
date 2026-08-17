"""SQLite store. Remembers every job ever seen so the digest never repeats itself.

The file is small and safe to commit — that is what lets the GitHub Actions run
keep its memory between days without any server.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Job, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    fingerprint TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    source      TEXT NOT NULL,
    scope       TEXT NOT NULL,
    company     TEXT,
    location    TEXT,
    description TEXT,
    salary      TEXT,
    posted_at   TEXT,
    track       TEXT,
    remote      INTEGER DEFAULT 0,
    payload     TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    verified_at TEXT,
    published_on TEXT
);
CREATE INDEX IF NOT EXISTS idx_track   ON jobs(track);
CREATE INDEX IF NOT EXISTS idx_pubon   ON jobs(published_on);
CREATE INDEX IF NOT EXISTS idx_seen    ON jobs(first_seen);
"""


class Store:
    def __init__(self, path: str | Path = "jobs.db") -> None:
        self.path = Path(path)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # -- reads ---------------------------------------------------------------

    def is_known(self, fingerprint: str) -> bool:
        cur = self.db.execute(
            "SELECT 1 FROM jobs WHERE fingerprint = ?", (fingerprint,)
        )
        return cur.fetchone() is not None

    def known_fingerprints(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT fingerprint FROM jobs")}

    def carry_forward(self, track: str, hours: int, limit: int) -> list[Job]:
        """Still-open jobs from the last `hours` that were never published.

        This is the honest way to refill a thin track: a real role you have not
        shared yet, not a recycled three-week-old posting.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = self.db.execute(
            """SELECT payload FROM jobs
               WHERE track = ? AND published_on IS NULL AND first_seen >= ?
               ORDER BY first_seen DESC LIMIT ?""",
            (track, cutoff, limit),
        ).fetchall()
        return [Job(**json.loads(r["payload"])) for r in rows]

    # -- writes --------------------------------------------------------------

    def upsert(self, job: Job) -> bool:
        """Insert if new. Returns True when the job had not been seen before."""
        if self.is_known(job.fingerprint):
            return False
        job.first_seen = job.first_seen or now_iso()
        self.db.execute(
            """INSERT INTO jobs (fingerprint, title, url, source, scope, company,
                                 location, description, salary, posted_at, track,
                                 remote, payload, first_seen, verified_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (job.fingerprint, job.title, job.url, job.source, job.scope, job.company,
             job.location, job.description, job.salary, job.posted_at, job.track,
             int(job.remote), json.dumps(job.to_dict()), job.first_seen, job.verified_at),
        )
        self.db.commit()
        return True

    def mark_published(self, fingerprints: list[str], day: str) -> None:
        self.db.executemany(
            "UPDATE jobs SET published_on = ? WHERE fingerprint = ?",
            [(day, fp) for fp in fingerprints],
        )
        self.db.commit()

    def stats(self) -> dict:
        total = self.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        published = self.db.execute(
            "SELECT COUNT(*) FROM jobs WHERE published_on IS NOT NULL"
        ).fetchone()[0]
        return {"total_seen": total, "published": published}

    def close(self) -> None:
        self.db.close()
