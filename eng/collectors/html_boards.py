"""Config-driven scraper for the Nigerian and African boards.

Every board is described by selectors in config.yaml rather than by its own
Python file. That is deliberate: these sites redesign, and when one does you
fix a CSS selector in config instead of editing code. `python -m eng.doctor`
tells you which selector went stale.

Two boards have selectors verified against their live markup:
  * myjobmag        li.job-info  ->  h2 a  +  li.job-desc
  * hotnigerianjobs a[href*='hotjobs/']

The rest ship with best-effort selectors and are expected to need tuning.
"""

from __future__ import annotations

from selectolax.parser import HTMLParser

from ..models import Job, clean
from .base import absolute, fetch

# HotNigerianJobs and Nairaland list every sector. Cheap pre-filter so we do not
# carry hundreds of irrelevant rows into the classifier.
TECH_HINT = (
    "develop", "engineer", "software", "programmer", "frontend", "front-end",
    "backend", "back-end", "fullstack", "full-stack", "devops", "data", "cloud",
    "python", "java", "php", "react", "node", "mobile", "android", "ios",
    "designer", "ui/ux", "qa", "tester", "cyber", "security", "network", "it ",
    "technolog", "digital", "web", "analyst", "database", "system",
)


def _text(node) -> str:
    """Text of a node, with a space between child elements.

    Without the separator, adjacent spans concatenate and you get titles like
    "development teacheratAvocado SolutionsKarshi, FCT" instead of
    "development teacher at Avocado Solutions Karshi, FCT".
    """
    if not node:
        return ""
    return clean(node.text(separator=" ", deep=True))


def _pick(card, selector: str):
    """First node matching any comma-separated selector, or the card itself."""
    if not selector:
        return None
    if selector == "self":
        return card
    for part in selector.split(","):
        found = card.css_first(part.strip())
        if found is not None:
            return found
    return None


def _from_page(html: str, src: dict, page_url: str) -> list[Job]:
    tree = HTMLParser(html)
    sel = src.get("select", {})
    base = src.get("base", page_url)

    cards = []
    for part in sel.get("card", "").split(","):
        part = part.strip()
        if part:
            cards.extend(tree.css(part))
    if not cards:
        return []

    jobs: list[Job] = []
    seen_urls: set[str] = set()

    for card in cards:
        title_node = _pick(card, sel.get("title", "a"))
        link_node = _pick(card, sel.get("link", "a"))
        if title_node is None or link_node is None:
            continue

        title = _text(title_node)
        href = link_node.attributes.get("href", "") if link_node.attributes else ""
        if not title or not href or len(title) < 6:
            continue

        url = absolute(base, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        low = title.lower()
        if not any(h in low for h in TECH_HINT):
            continue

        # MyJobMag renders "Job Title at Company" — split it so the company
        # shows in its own field instead of trailing the title everywhere.
        company = ""
        if " at " in title:
            head, tail = title.rsplit(" at ", 1)
            if 2 < len(tail) < 60:
                title, company = head.strip(), tail.strip()

        jobs.append(Job(
            title=title,
            company=company,
            url=url,
            source=src["id"],
            scope=src.get("scope", "nigeria"),
            location="Nigeria" if src.get("scope") == "nigeria" else "",
            description=_text(_pick(card, sel.get("desc", ""))),
            attribution=src.get("attribution", ""),
            attribution_url=src.get("attribution_url", ""),
        ))
    return jobs


def collect(src: dict) -> list[Job]:
    out: list[Job] = []
    for url in src.get("urls", []):
        html = fetch(url)
        if not html:
            continue
        try:
            out.extend(_from_page(html, src, url))
        except Exception:
            continue
    return out
