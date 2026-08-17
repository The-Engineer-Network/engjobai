# ENG Job Engine

A daily tech-job board for **The Engineer Network**. It collects postings from
17 live sources across Nigeria and the global remote market, drops the scams and
the dead links, sorts what survives into eight tracks, and publishes one page
you share to the WhatsApp group.

You press one button. Everyone gets 8 sections, up to 10 verified roles each,
every link with a description.

---

## Quick start

```bash
cd eng-job-engine
pip install -r requirements.txt

python -m eng.doctor     # check which sources are alive right now
python run.py --open     # build today's board and open it
```

That's it — no API key required to get a working board. The AI is an optional
upgrade (see below).

Useful flags:

| Command | What it does |
|---|---|
| `python run.py` | Full run: collect, verify, publish |
| `python run.py --open` | Same, then open the page in your browser |
| `python run.py --dry` | Collect and report, write nothing |
| `python run.py --no-verify` | Skip link checking — fast, for testing layout |
| `python -m eng.doctor` | Test all 17 sources and print what each returned |

Output lands in `site/`:

* `site/index.html` — today's board, the file you share
* `site/YYYY-MM-DD.html` — permanent dated archive
* `site/YYYY-MM-DD.json` — the same data, machine-readable

---

## What it actually does

```
collect (17 sources, parallel)
   ↓  948 raw postings on a typical morning
dedup against every job ever seen
   ↓  fingerprint = normalised title + company, so the same Moniepoint role
      appearing on four boards is published once, ever
scam gate  →  tech gate  →  rules  →  AI (only the leftovers)
   ↓
verify every link concurrently
   ↓  404? "no longer accepting"? older than 14 days? dropped, not downgraded
      (this pass also lifts the real description off each job page)
fill buckets: Nigeria first, then Africa, then global
   ↓
publish one branded HTML page + a WhatsApp share message
```

### The two rules that matter

**Never pad.** If Mobile only has 6 real roles today, the page says `6/10`.
It never fills the gap with filler. Your channel's credibility is the whole
asset — three fake listings costs you the audience.

**Scam gate is a hard drop, not a warning.** Any posting mentioning an
application fee, training fee, BVN request, or Western Union is dropped
silently and never published. Warnings get ignored by readers; absence
doesn't. Edit `scam_blocklist` in `config.yaml` to add more.

---

## Sources

All 17 confirmed returning data. `python -m eng.doctor` re-checks any time.

**Global — free JSON APIs (no keys, nothing to break)**
RemoteOK · Remotive · Himalayas · Arbeitnow · Jobicy · Working Nomads

**Global — RSS**
We Work Remotely × 4 categories (programming, devops, design, product)

**Nigeria — scraped**
MyJobMag · Jobberman · Jobzilla · NaijaJobPortal · JobGurus · HotNigerianJobs

**Nigeria — Telegram** (public `t.me/s/` view, no bot token)
Jobs in Nigeria Daily · Jobnow Nigeria · Job Network NG · Rekrut Consulting

### Attribution is a requirement, not a courtesy

RemoteOK's and Jobicy's API terms require crediting them with a direct link.
Every card carries a `via <source>` link back for exactly this reason — don't
remove it. It also makes the page look more trustworthy, not less.

### Two sources are disabled on purpose

Checked, not guessed:

* `africatechjobs.xyz` — root URL now returns **404**
* `launchafrica.io` — returns 200 but renders listings client-side, so there is
  nothing in the HTML to scrape. Would need Playwright; not worth it for its volume.

Both are left in `config.yaml` with `enabled: false` so you can flip them back on.

### HotNigerianJobs: a known limitation

Its RSS feed at `/rss.xml` looks alive (HTTP 200, valid XML) but is
**abandoned — last built June 2021**. So we scrape the HTML index instead.

HNJ also posts *company roundups* ("R & R Recruiting — 24 Positions") rather
than one job per link, so most of its entries have no tech signal in the title
and get dropped. It contributes little. That is the source's shape, not a bug.

---

## Adding the AI (optional)

Without a key the engine runs on rules alone and produces a good board — roughly
300 of 880 postings get sorted by keyword rules, and ~170 arrive with a real
description from the source.

With a Groq key you additionally recover the ~260 postings per day that pass the
tech gate but match no track keyword, and get a written description for the
handful that have none.

```bash
cp .env.example .env
# paste your key from https://console.groq.com/keys
```

**Groq's free tier is enough**: 30 req/min, 6,000 tokens/min, 14,400 req/day.
The engine batches 20 jobs per call and throttles to stay well inside it. Rules
run first precisely so the AI only sees the ~20% that need judgment.

If you outgrow it: `llama-3.1-8b-instant` costs about **$1/month** at this volume.
`llama-3.3-70b-versatile` about **$11/month**. The LLM layer sits behind
`eng/llm.py`, so swapping providers is an afternoon.

The engine **never fails on AI problems.** Missing key, exhausted tier, Groq
having a bad day — every call returns `None` and the pipeline falls back to
rules. A rules-only digest is still a good digest; a crashed cron job is not.

---

## Running it daily without a server

`.github/workflows/daily.yml` is ready. Push this folder to a GitHub repo, add
`GROQ_API_KEY` under **Settings → Secrets → Actions**, and it runs on schedule
for free.

It fires **four times a day and publishes once** (04:00 WAT publish, then 09:00,
13:00, 17:00 top-ups). That's deliberate: several boards only show a rolling
window of the newest posts, so polling once a day silently misses jobs that
appeared and scrolled off.

`jobs.db` is committed by the workflow — that SQLite file *is* the engine's
memory of what it has already published, which is how it avoids repeating
itself with no server involved.

To publish the page publicly, point GitHub Pages or Cloudflare Pages at the
`site/` folder, then set `public_base_url` in `config.yaml` so share links
resolve.

---

## Tuning it

Everything you'd normally change is in **`config.yaml`** — no code edits.

| Want to… | Do this |
|---|---|
| Change how many jobs per section | `tracks[].target` |
| Add or remove a section | add/remove a `tracks[]` entry |
| Improve a section's sorting | add keywords to `tracks[].match` |
| Block more scam wording | add to `scam_blocklist` |
| Turn off a noisy source | `enabled: false` on that source |
| Fix a board that went quiet | edit its `select:` selectors |
| Add your WhatsApp group link | `community.whatsapp_group` |

**When a scraped board goes quiet**, `python -m eng.doctor` shows it as `0 jobs`.
That's a selector fix in `config.yaml`, not a code change — which is the entire
reason the scrapers are config-driven instead of one Python file per board.

---

## Project layout

```
eng-job-engine/
├── run.py                      entry point — the whole pipeline
├── config.yaml                 sources, tracks, rules, branding
├── requirements.txt
├── .env.example                Groq key goes here (optional)
├── eng/
│   ├── models.py               Job shape + date/text normalisation
│   ├── store.py                SQLite: what we've already published
│   ├── classify.py             scam gate → tech gate → rules → AI
│   ├── verify.py               concurrent link checks + description lifting
│   ├── buckets.py              fill order, never-pad rule
│   ├── llm.py                  Groq client (fails soft, always)
│   ├── doctor.py               source health check
│   ├── collectors/
│   │   ├── json_apis.py        6 global APIs, one adapter each
│   │   ├── rss.py              We Work Remotely feeds
│   │   ├── html_boards.py      config-driven scraper for NG boards
│   │   └── telegram.py         public t.me/s/ reader + spam gate
│   └── publish/render.py       the branded page
├── site/                       output (publish this folder)
└── .github/workflows/daily.yml
```

---

## Design notes

The page follows theengineernetwork.com: warm near-black ground (`#0C0906`),
orange accent (`#E8891C`), cream text. Self-contained single file — no external
CSS, fonts, or scripts, so it renders identically anywhere and works offline.

**Sharing works two ways.** The header button shares the whole day's board as a
summary plus link. Every individual card also has its own Share button, so you
can send one role to one person without forwarding all 76.

**Links go out, descriptions stay short.** Each card shows title, company,
location, a one-line description and an `Apply →` straight to the original
posting. We never republish the full job description — that's the employer's
copyrighted text, and applying on the real site is what gets your members seen.

---

*Built for The Engineer Network. Inclusion of a listing is not an endorsement
of the employer.*
