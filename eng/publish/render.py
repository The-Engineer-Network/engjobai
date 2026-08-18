"""Render the daily digest as a self-contained HTML page.

Colours and type follow theengineernetwork.com: warm near-black ground,
#E8891C orange accent, cream text. No external requests — the page is one
file you can open, host anywhere, or email to yourself.

Two files are written per run:
    site/YYYY-MM-DD.html   the dated archive page (permanent link)
    site/index.html        today's digest (what you share)
"""

from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path
from urllib.parse import quote

from ..models import Job

CSS = """
*{box-sizing:border-box}
:root{
  --bg:#0C0906; --surface:#15100A; --surface-2:#1D1610; --line:#2E241A;
  --accent:#E8891C; --accent-2:#F6AC52; --accent-wash:#2A1B0C;
  --text:#F4EBE0; --muted:#A5937E; --dim:#7A6A59;
  --sans:ui-sans-serif,system-ui,"Segoe UI",-apple-system,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"Cascadia Mono","SF Mono",Consolas,monospace;
}
html{scroll-behavior:smooth;scroll-padding-top:5.5rem}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);
  font-size:16px;line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:76rem;margin:0 auto;padding:0 clamp(1rem,3vw,2rem)}

/* ---- top bar ---- */
.bar{position:sticky;top:0;z-index:50;background:rgba(12,9,6,.94);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.bar-in{display:flex;align-items:center;gap:1rem;padding:.85rem 0}
.mark{font-weight:800;letter-spacing:-.03em;font-size:1.35rem;color:var(--accent);
  text-decoration:none;white-space:nowrap}
.mark span{color:var(--text);font-weight:600;font-size:.82rem;letter-spacing:.01em;
  margin-left:.5rem}
.bar-sp{flex:1}
.btn{display:inline-flex;align-items:center;gap:.5rem;border:none;cursor:pointer;
  font-family:var(--sans);font-size:.9rem;font-weight:650;padding:.62rem 1.15rem;
  border-radius:6px;background:var(--accent);color:#1A1006;text-decoration:none;
  transition:background .15s}
.btn:hover{background:var(--accent-2)}
.btn-ghost{background:transparent;color:var(--text);border:1px solid var(--line)}
.btn-ghost:hover{background:var(--surface-2);border-color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}

/* ---- hero ---- */
.hero{padding:clamp(2.25rem,5vw,3.75rem) 0 1.75rem}
.eyebrow{font-family:var(--mono);font-size:.72rem;letter-spacing:.16em;
  text-transform:uppercase;color:var(--accent);margin:0 0 .75rem}
h1{font-size:clamp(2rem,5.5vw,3.1rem);line-height:1.05;letter-spacing:-.035em;
  margin:0 0 .85rem;font-weight:800;text-wrap:balance}
.lede{margin:0;max-width:52ch;color:var(--muted);font-size:1.05rem}
.counts{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1.6rem}
.count{display:inline-flex;align-items:baseline;gap:.42rem;background:var(--surface);
  border:1px solid var(--line);border-radius:999px;padding:.34rem .85rem;
  font-size:.83rem;color:var(--muted);text-decoration:none;transition:border-color .15s}
.count:hover{border-color:var(--accent)}
.count b{color:var(--text);font-family:var(--mono);font-size:.9rem}
.count.thin b{color:var(--accent-2)}

/* ---- share strip ---- */
.share{margin:2rem 0 .5rem;background:var(--surface);border:1px solid var(--line);
  border-left:3px solid var(--accent);border-radius:8px;padding:1.15rem 1.35rem;
  display:flex;flex-wrap:wrap;align-items:center;gap:1rem}
.share p{margin:0;flex:1;min-width:16rem;color:var(--muted);font-size:.94rem}
.share strong{color:var(--text)}

/* ---- sections ---- */
section{padding-top:2.75rem}
.sec-head{display:flex;align-items:baseline;gap:.75rem;flex-wrap:wrap;
  border-bottom:1px solid var(--line);padding-bottom:.7rem;margin-bottom:1.25rem}
h2{font-size:clamp(1.3rem,3vw,1.65rem);letter-spacing:-.02em;margin:0;font-weight:750}
.tally{font-family:var(--mono);font-size:.78rem;color:var(--dim);
  background:var(--surface-2);border-radius:4px;padding:.2rem .5rem}
.tally.short{color:var(--accent-2)}
.sec-blurb{width:100%;margin:.15rem 0 0;color:var(--muted);font-size:.92rem}

.grid{display:grid;gap:.85rem;
  grid-template-columns:repeat(auto-fill,minmax(min(21rem,100%),1fr))}

/* ---- job card ---- */
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;
  padding:1.05rem 1.15rem 1rem;display:flex;flex-direction:column;gap:.6rem;
  min-width:0;transition:border-color .15s,transform .15s}
.card:hover{border-color:var(--accent);transform:translateY(-2px)}
.card h3{margin:0;font-size:1rem;line-height:1.35;letter-spacing:-.01em;
  font-weight:650;overflow-wrap:anywhere}
.card h3 a{color:var(--text);text-decoration:none}
.card h3 a:hover{color:var(--accent-2)}
.meta{font-size:.85rem;color:var(--muted);margin:0;overflow-wrap:anywhere}
.meta b{color:var(--text);font-weight:600}
/* A bare URL or an un-spaced string from a feed is longer than the card. Let it
   break mid-token rather than paint outside the card and scroll the whole page. */
.desc{margin:0;font-size:.9rem;color:var(--muted);line-height:1.5;
  overflow-wrap:anywhere}
.chips{display:flex;flex-wrap:wrap;gap:.35rem}
.chip{font-family:var(--mono);font-size:.65rem;letter-spacing:.06em;
  text-transform:uppercase;padding:.2rem .45rem;border-radius:3px;
  background:var(--surface-2);color:var(--dim)}
.chip.ng{background:var(--accent-wash);color:var(--accent-2)}
.chip.rm{background:#0F2418;color:#5FBF83}
.card-foot{display:flex;align-items:center;gap:.6rem;margin-top:auto;padding-top:.7rem;
  border-top:1px solid var(--line)}
.apply{font-size:.87rem;font-weight:650;color:var(--accent);text-decoration:none}
.apply:hover{color:var(--accent-2);text-decoration:underline}
.mini{margin-left:auto;background:transparent;border:1px solid var(--line);
  color:var(--muted);font-family:var(--sans);font-size:.75rem;cursor:pointer;
  padding:.28rem .6rem;border-radius:4px;transition:all .15s}
.mini:hover{border-color:var(--accent);color:var(--accent)}
.src{font-family:var(--mono);font-size:.66rem;color:var(--dim);text-decoration:none}
.src:hover{color:var(--accent)}

.empty{background:var(--surface);border:1px dashed var(--line);border-radius:8px;
  padding:1.5rem;color:var(--muted);font-size:.92rem;text-align:center}

/* ---- caution + footer ---- */
.caution{margin:3.5rem 0 0;background:var(--surface);border:1px solid var(--line);
  border-left:3px solid #C4622A;border-radius:0 8px 8px 0;padding:1.2rem 1.4rem}
.caution h2{font-size:1.05rem;margin:0 0 .6rem}
.caution ul{margin:0;padding-left:1.15rem;color:var(--muted);font-size:.9rem}
.caution li{margin-bottom:.35rem}
footer{margin-top:3rem;border-top:1px solid var(--line);padding:1.5rem 0 3.5rem;
  color:var(--dim);font-size:.8rem;line-height:1.7}
footer a{color:var(--muted)}

@media(max-width:36rem){
  .bar-in{flex-wrap:wrap}
  .grid{grid-template-columns:1fr}
}
"""

JS = """
function toast(btn, msg){
  const old = btn.textContent;
  btn.textContent = msg;
  setTimeout(() => { btn.textContent = old; }, 1400);
}
function copyJob(btn){
  const c = btn.closest('.card');
  const text = c.dataset.share;
  navigator.clipboard.writeText(text).then(() => toast(btn, 'Copied'));
}
function shareJob(btn){
  const c = btn.closest('.card');
  window.open('https://wa.me/?text=' + encodeURIComponent(c.dataset.share), '_blank');
}
"""


def _chip(text: str, cls: str = "") -> str:
    return f'<span class="chip {cls}">{html.escape(text)}</span>'


def _card(job: Job, base_url: str) -> str:
    chips = []
    if job.scope == "nigeria":
        chips.append(_chip("Nigeria", "ng"))
    elif job.scope == "africa":
        chips.append(_chip("Africa", "ng"))
    if job.remote:
        chips.append(_chip("Remote", "rm"))
    if job.salary:
        chips.append(_chip(job.salary))

    meta_bits = []
    if job.company:
        meta_bits.append(f"<b>{html.escape(job.company)}</b>")
    if job.location:
        meta_bits.append(html.escape(job.location))
    meta = " · ".join(meta_bits)

    # The text that lands in WhatsApp when someone shares this single job.
    share_text = f"{job.title}"
    if job.company:
        share_text += f" at {job.company}"
    share_text += f"\n{job.description}\nApply: {job.url}"

    # Some APIs require a credited, followed link back. Honour it per card.
    src = ""
    if job.attribution:
        if job.attribution_url:
            src = (f'<a class="src" href="{html.escape(job.attribution_url)}" '
                   f'target="_blank" rel="noopener">via {html.escape(job.attribution)}</a>')
        else:
            src = f'<span class="src">via {html.escape(job.attribution)}</span>'

    return f"""      <article class="card" data-share="{html.escape(share_text)}">
        <div class="chips">{''.join(chips)}</div>
        <h3><a href="{html.escape(job.url)}" target="_blank" rel="noopener">{html.escape(job.title)}</a></h3>
        {f'<p class="meta">{meta}</p>' if meta else ''}
        <p class="desc">{html.escape(job.description)}</p>
        <div class="card-foot">
          <a class="apply" href="{html.escape(job.url)}" target="_blank" rel="noopener">Apply &rarr;</a>
          {src}
          <button class="mini" onclick="shareJob(this)">Share</button>
          <button class="mini" onclick="copyJob(this)">Copy</button>
        </div>
      </article>"""


def _section(track: dict, jobs: list[Job], base_url: str) -> str:
    target = track.get("target", 10)
    short = len(jobs) < target
    tally = f'<span class="tally{" short" if short else ""}">{len(jobs)}/{target}</span>'

    if jobs:
        body = f'<div class="grid">\n{chr(10).join(_card(j, base_url) for j in jobs)}\n    </div>'
    else:
        body = ('<div class="empty">Nothing verified for this track today. '
                'Not padded with filler — check back tomorrow.</div>')

    return f"""    <section id="{track['key']}">
      <div class="sec-head">
        <h2>{html.escape(track['label'])}</h2>
        {tally}
        <p class="sec-blurb">{html.escape(track.get('blurb', ''))}</p>
      </div>
      {body}
    </section>"""


def render(buckets: dict[str, list[Job]], config: dict, day: str | None = None) -> str:
    day = day or date.today().isoformat()
    community = config.get("community", {})
    base_url = community.get("public_base_url", "").rstrip("/")
    group = community.get("whatsapp_group", "")
    tracks = config["tracks"]

    total = sum(len(v) for v in buckets.values())
    pretty_day = date.fromisoformat(day).strftime("%A %d %B %Y")

    # The message that lands in the group when you press the big Share button.
    summary_lines = [f"ENG Job Board — {date.fromisoformat(day).strftime('%a %d %b')}", ""]
    for t in tracks:
        n = len(buckets.get(t["key"], []))
        if n:
            summary_lines.append(f"{t['label']}: {n}")
    summary_lines += ["", f"{total} verified roles, every link checked against its source this morning."]
    if base_url:
        summary_lines.append(f"{base_url}/{day}.html")
    share_msg = "\n".join(summary_lines)
    wa_url = "https://wa.me/?text=" + quote(share_msg)

    counts = "".join(
        f'<a class="count{" thin" if len(buckets.get(t["key"], [])) < t.get("target", 10) else ""}" '
        f'href="#{t["key"]}">{html.escape(t["label"])} <b>{len(buckets.get(t["key"], []))}</b></a>'
        for t in tracks
    )

    sections = "\n".join(_section(t, buckets.get(t["key"], []), base_url) for t in tracks)

    join = (f'<a class="btn btn-ghost" href="{html.escape(group)}" target="_blank" '
            f'rel="noopener">Join the community</a>') if group else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ENG Job Board — {pretty_day}</title>
<meta name="description" content="{total} verified frontend, backend, DevOps, mobile and data roles for Nigerian engineers — {pretty_day}.">
<meta property="og:title" content="ENG Job Board — {pretty_day}">
<meta property="og:description" content="{total} verified tech roles. Nigeria and global remote.">
<meta name="theme-color" content="#0C0906">
<style>{CSS}</style>
</head>
<body>

<div class="bar"><div class="wrap bar-in">
  <a class="mark" href="index.html">ENG<span>Job Board</span></a>
  <div class="bar-sp"></div>
  {join}
  <a class="btn" href="{html.escape(wa_url)}" target="_blank" rel="noopener">Share to WhatsApp</a>
</div></div>

<div class="wrap">

  <header class="hero">
    <p class="eyebrow">{pretty_day}</p>
    <h1>{total} verified tech roles, sorted by track.</h1>
    <p class="lede">Collected this morning from Nigerian job boards, African startup boards
      and global remote boards. Every link was checked against its source before it was published.</p>
    <div class="counts">{counts}</div>
  </header>

  <div class="share">
    <p><strong>Press share, it lands in the group.</strong> Every job also has its own
      Share button, so you can send one role to one person.</p>
    <a class="btn" href="{html.escape(wa_url)}" target="_blank" rel="noopener">Share today's board</a>
  </div>

{sections}

  <div class="caution">
    <h2>Before anyone applies</h2>
    <ul>
      <li>No real employer charges an application, training or processing fee. Postings
        mentioning one are dropped automatically and never appear here.</li>
      <li>Check the company on Nairaland and Glassdoor before an interview.</li>
      <li>For global remote roles, confirm early that they can pay into Nigeria.</li>
      <li>Found a bad listing that slipped through? Report it so it gets blocked.</li>
    </ul>
  </div>

  <footer>
    Built for {html.escape(community.get('name', 'the community'))} ·
    generated {pretty_day} · {total} roles published.<br>
    Listings link to the original posting on the source board. Job data via the
    sources credited on each card. Inclusion is not an endorsement of any employer.
  </footer>

</div>
<script>{JS}</script>
</body>
</html>"""


def write(buckets: dict[str, list[Job]], config: dict, out_dir: str | Path = "site",
          day: str | None = None) -> tuple[Path, Path]:
    day = day or date.today().isoformat()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    page = render(buckets, config, day)
    dated = out / f"{day}.html"
    index = out / "index.html"
    dated.write_text(page, encoding="utf-8")
    index.write_text(page, encoding="utf-8")

    # Machine-readable copy, so the data is reusable beyond this page.
    (out / f"{day}.json").write_text(
        json.dumps({k: [j.to_dict() for j in v] for k, v in buckets.items()},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return dated, index
