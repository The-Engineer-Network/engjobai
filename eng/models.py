"""Core data shapes. Every collector returns Job objects, whatever its source."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

WS = re.compile(r"\s+")
TAGS = re.compile(r"<[^>]+>")
# A tag left unterminated by an upstream truncation: "<span" with no ">".
HALF_TAG = re.compile(r"<\s*/?[a-zA-Z][^>]*$")


def to_iso(value) -> str:
    """Normalise any date a source hands us into an ISO8601 string.

    Sources disagree wildly: Himalayas sends a unix epoch *integer*, RSS feeds
    send RFC-2822 strings, the JSON APIs send ISO. Normalising here means every
    consumer downstream can assume a string, and none of them need a try/except.
    Unparseable values become "" — treated as "date unknown", never as stale.
    """
    if value in (None, ""):
        return ""

    # Unix epoch, as int/float or a numeric string.
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        try:
            seconds = float(value)
            if seconds > 1e11:      # milliseconds
                seconds /= 1000.0
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")
        except (ValueError, OSError, OverflowError):
            return ""

    text = str(value).strip()
    try:                            # ISO8601
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat(timespec="seconds")
    except ValueError:
        pass
    try:                            # RFC-2822, as used by RSS
        return parsedate_to_datetime(text).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""


def clean(text: str | None, limit: int = 0) -> str:
    """Strip tags and collapse whitespace. Optionally truncate on a word boundary.

    Sources disagree about escaping as much as they disagree about dates. Most
    send plain HTML, several send that HTML entity-escaped, and a few (anything
    routed through Word or a CMS rich-text field) send it escaped twice. A
    single tag-strip only catches the first kind, so the rest arrived as literal
    "&lt;p&gt;" markup on the page. Unescape and strip in a loop until the text
    settles: three passes covers every double-encoded feed we see, and the loop
    stops early the moment a pass changes nothing.
    """
    if not text:
        return ""
    out = str(text)
    for _ in range(3):
        stepped = html.unescape(TAGS.sub(" ", out))
        if stepped == out:
            break
        out = stepped
    out = WS.sub(" ", HALF_TAG.sub("", TAGS.sub(" ", out))).strip()
    if limit and len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0].rstrip(",;:.-") + "…"
    return out


@dataclass
class Job:
    """One posting, normalised to the same shape regardless of where it came from."""

    title: str
    url: str
    source: str                      # collector id, e.g. "myjobmag"
    scope: str = "global"            # nigeria | africa | global
    company: str = ""
    location: str = ""
    description: str = ""
    salary: str = ""
    posted_at: str = ""              # ISO8601 when known
    attribution: str = ""            # display name required by some APIs' terms
    attribution_url: str = ""
    track: str = ""                  # set by the classifier
    remote: bool = False
    tags: list[str] = field(default_factory=list)

    # populated by the pipeline
    fingerprint: str = ""
    first_seen: str = ""
    verified_at: str = ""

    def __post_init__(self) -> None:
        self.title = clean(self.title, 160)
        self.company = clean(self.company, 90)
        self.location = clean(self.location, 80)
        self.description = clean(self.description, 400)
        self.posted_at = to_iso(self.posted_at)
        self.salary = clean(self.salary, 60)
        if not self.fingerprint:
            self.fingerprint = self.make_fingerprint()

    def make_fingerprint(self) -> str:
        """Identity for dedup: same role at same company is the same job.

        Deliberately NOT the URL — the same Moniepoint role appears on four
        boards with four URLs, and the community should see it once.
        """
        norm = re.sub(r"[^a-z0-9 ]", "", f"{self.title} {self.company}".lower())
        norm = WS.sub(" ", norm).strip()
        return hashlib.sha1(norm.encode()).hexdigest()[:16]

    @property
    def haystack(self) -> str:
        """Everything searchable, lowercased — used by rules and the scam gate."""
        return f"{self.title} {self.company} {self.description} {' '.join(self.tags)}".lower()

    def to_dict(self) -> dict:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
