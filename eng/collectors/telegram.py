"""Telegram channels, read through the public t.me/s/<channel> web view.

No bot token, no account, no API key — the preview page is public HTML.

Telegram posts are free text, so we extract the first meaningful line as the
title and the first outbound link as the apply URL. Posts with no link are
skipped: a job the community cannot click through to is not shareable.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from ..models import Job, clean
from .base import fetch

TG_INTERNAL = ("t.me", "telegram.me", "telegram.org")
NOISE = re.compile(r"^(vacancy|job alert|hiring|urgent|new job|apply now)\b[:\-\s]*",
                   re.IGNORECASE)

# These channels carry referral spam and giveaways alongside real vacancies
# ("Join OPay with me and get N50 free money"). A post must look like a job
# posting before we will touch it, and must not look like a promo.
JOB_SIGNAL = (
    "vacanc", "hiring", "recruit", "job", "role", "position", "apply",
    "developer", "engineer", "designer", "analyst", "internship", "graduate",
    "opening", "career", "salary", "remote", "full-time", "full time", "onsite",
)

PROMO_SIGNAL = (
    "free money", "get paid to", "referral", "refer and earn", "invite your friends",
    "bonus instantly", "sign up bonus", "signup bonus", "airdrop", "giveaway",
    "click this link and", "join opay", "loan app", "betting", "forex signal",
    "crypto invest", "double your", "earn daily", "work from home scheme",
)


def _first_line(text: str) -> str:
    for raw in text.split("\n"):
        line = NOISE.sub("", clean(raw)).strip(" :-–—•*#")
        if len(line) > 12:
            return line[:150]
    return ""


def _collect_channel(channel: str, src: dict) -> list[Job]:
    html = fetch(f"https://t.me/s/{channel}")
    if not html:
        return []

    try:
        tree = HTMLParser(html)
    except Exception:
        return []

    jobs: list[Job] = []
    for bubble in tree.css("div.tgme_widget_message_text"):
        body = bubble.text(separator="\n")
        low = body.lower()

        # Two gates, in this order. Promo check first so a referral post that
        # happens to say "job" cannot slip through on the job signal.
        if any(p in low for p in PROMO_SIGNAL):
            continue
        if not any(s in low for s in JOB_SIGNAL):
            continue

        title = _first_line(body)
        if not title:
            continue

        url = ""
        for anchor in bubble.css("a"):
            href = (anchor.attributes or {}).get("href", "")
            if href.startswith("http") and not any(d in href for d in TG_INTERNAL):
                url = href
                break
        if not url:
            continue

        jobs.append(Job(
            title=title,
            url=url,
            source=src["id"],
            scope=src.get("scope", "nigeria"),
            location="Nigeria",
            description=clean(body, 400),
            attribution=f"Telegram · @{channel}",
            attribution_url=f"https://t.me/{channel}",
        ))
    return jobs


def collect(src: dict) -> list[Job]:
    out: list[Job] = []
    for channel in src.get("channels", []):
        try:
            out.extend(_collect_channel(channel, src))
        except Exception:
            continue
    return out
