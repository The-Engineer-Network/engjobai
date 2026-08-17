"""Gate, classify, and describe.

Order matters and is deliberate:

    scam gate  ->  tech gate  ->  rules  ->  AI (only what is left)

By the time anything reaches the AI, roughly 80% of the day's volume has
already been decided for free. That is what keeps the whole thing inside
Groq's free tier.
"""

from __future__ import annotations

from .models import Job

# Signals that a posting is a tech role at all. HotNigerianJobs and Nairaland
# carry every sector, so without this gate the digest fills with bank teller
# roles that merely mention "systems".
TECH_SIGNALS = (
    "developer", "engineer", "programmer", "software", "frontend", "front-end",
    "backend", "back-end", "full-stack", "fullstack", "devops", "sre", "qa ",
    "data scien", "data engineer", "data analyst", "machine learning", "ai ",
    "cloud", "kubernetes", "docker", "react", "angular", "vue", "node", "python",
    "django", "laravel", "php", "java", "kotlin", "swift", "flutter", "golang",
    "typescript", "javascript", "ui/ux", "ux design", "ui design", "product design",
    "product manager", "cybersecurity", "security analyst", "database", "sql",
    "it support", "network engineer", "system administrator", "tech lead", "cto",
    "web design", "mobile app", "blockchain", "solidity", "graphic",
)

REMOTE_SIGNALS = ("remote", "work from home", "wfh", "anywhere", "distributed")

NIGERIA_SIGNALS = ("nigeria", "lagos", "abuja", "port harcourt", "ibadan", "kano",
                   "lekki", "ikeja", "yaba", "enugu", "benin city", "naija")


class Classifier:
    def __init__(self, config: dict, llm=None) -> None:
        self.tracks = config["tracks"]
        self.blocklist = [b.lower() for b in config.get("scam_blocklist", [])]
        self.llm = llm
        self.counters = {"scam": 0, "not_tech": 0, "by_rule": 0, "by_ai": 0, "unclassified": 0}

    # -- gates ---------------------------------------------------------------

    def is_scam(self, job: Job) -> bool:
        """Hard gate. A match is dropped silently and never published.

        Warnings get ignored by readers; absence does not. If this fires on a
        real job occasionally, that is the correct trade for a community feed.
        """
        return any(bad in job.haystack for bad in self.blocklist)

    def is_tech(self, job: Job) -> bool:
        return any(sig in job.haystack for sig in TECH_SIGNALS)

    # -- track assignment ----------------------------------------------------

    def by_rules(self, job: Job) -> str | None:
        """Keyword match, most specific track first.

        Full-stack is checked before frontend/backend so a 'Full-Stack React /
        Node' role lands in one bucket instead of arbitrarily in whichever
        keyword appeared first.
        """
        hay = job.haystack
        ordered = sorted(
            self.tracks,
            key=lambda t: 0 if t["key"] == "fullstack" else 1,
        )
        best, best_hits = None, 0
        for track in ordered:
            hits = sum(1 for kw in track["match"] if kw.lower() in hay)
            if hits > best_hits:
                best, best_hits = track["key"], hits
        return best

    def by_ai(self, jobs: list[Job]) -> dict[str, str]:
        """Classify the leftovers in one batched call, 20 at a time."""
        if not jobs or not self.llm or not self.llm.enabled:
            return {}

        keys = [t["key"] for t in self.tracks]
        system = (
            "You sort software job postings into exactly one track. "
            f"Valid tracks: {', '.join(keys)}, or 'none' if it is not a technology role. "
            'Reply with JSON only: {"results":[{"id":"<id>","track":"<track>"}]}'
        )

        out: dict[str, str] = {}
        for i in range(0, len(jobs), 20):
            batch = jobs[i:i + 20]
            listing = "\n".join(
                f"{j.fingerprint}: {j.title} | {j.company} | {j.description[:110]}"
                for j in batch
            )
            data = self.llm.ask_json(system, listing)
            if not data:
                continue
            for row in data.get("results", []):
                track = str(row.get("track", "")).strip()
                if track in keys:
                    out[str(row.get("id"))] = track
        return out

    # -- descriptions --------------------------------------------------------

    def describe(self, jobs: list[Job]) -> None:
        """Give every job a one-line description, in place.

        MyJobMag and the JSON APIs hand us real text. Telegram posts and bare
        anchor scrapes do not — those get a written line, because a link with
        no description is a link nobody clicks.
        """
        need = [j for j in jobs if len(j.description) < 40]
        for j in need:
            j.description = self._fallback_line(j)

        if not (self.llm and self.llm.enabled and need):
            return

        system = (
            "Write a single plain sentence (max 22 words) describing each job for "
            "an engineer deciding whether to click. State the role and stack. No "
            "hype, no 'exciting opportunity'. "
            'Reply with JSON only: {"results":[{"id":"<id>","line":"<sentence>"}]}'
        )
        for i in range(0, len(need), 20):
            batch = need[i:i + 20]
            listing = "\n".join(
                f"{j.fingerprint}: {j.title} | {j.company} | {j.location}" for j in batch
            )
            data = self.llm.ask_json(system, listing)
            if not data:
                continue
            index = {j.fingerprint: j for j in batch}
            for row in data.get("results", []):
                job = index.get(str(row.get("id")))
                line = str(row.get("line", "")).strip()
                if job and 15 < len(line) < 220:
                    job.description = line

    @staticmethod
    def _fallback_line(job: Job) -> str:
        bits = [job.title]
        if job.company:
            bits.append(f"at {job.company}")
        where = job.location or ("Remote" if job.remote else "")
        if where:
            bits.append(f"— {where}")
        return " ".join(bits) + "."

    # -- entry point ---------------------------------------------------------

    def run(self, jobs: list[Job]) -> list[Job]:
        kept, ambiguous = [], []

        for job in jobs:
            if self.is_scam(job):
                self.counters["scam"] += 1
                continue
            if not self.is_tech(job):
                self.counters["not_tech"] += 1
                continue

            job.remote = job.remote or any(s in job.haystack for s in REMOTE_SIGNALS)
            if job.scope != "nigeria" and any(s in job.haystack for s in NIGERIA_SIGNALS):
                job.scope = "nigeria"

            track = self.by_rules(job)
            if track:
                job.track = track
                self.counters["by_rule"] += 1
                kept.append(job)
            else:
                ambiguous.append(job)

        # Only the leftovers cost an API call.
        decided = self.by_ai(ambiguous)
        for job in ambiguous:
            track = decided.get(job.fingerprint)
            if track:
                job.track = track
                self.counters["by_ai"] += 1
                kept.append(job)
            else:
                self.counters["unclassified"] += 1

        # NOTE: describe() is deliberately NOT called here. It runs after
        # verification, because verification pulls real descriptions off the
        # job pages it downloads — and because there is no point writing a
        # description for a job that is about to be dropped as dead.
        return kept
