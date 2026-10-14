# Job Alert Tool

Tracks a list of companies' career pages, finds new job postings that match
your keyword/location filters, dedupes them against previously-seen
postings, and emails you a daily digest grouped by company. Includes a
Streamlit UI for editing the company list and browsing scraped jobs.

No AI involved — this is a plain fetch → filter → dedupe → email pipeline.

## How it works

```
companies (DB) ──> ATS detector (cached in DB)
                        │
                        ▼
          ┌── Tier 1: ATS JSON API (Greenhouse/Lever/Ashby/Workable/
          │            SmartRecruiters/Workday/Recruitee)
          └── Tier 2: JSON-LD JobPosting schema + bounded sitemap crawl
                        │
                        ▼
                 normalize → pre-filter (keywords/location)
                        │
                        ▼
              dedupe against DB (seen job IDs)
                        │
                        ▼
         email digest, grouped by company
         (+ a "broken fetchers" section for companies
          where every tier failed)
```

Each company is fetched inside its own try/except — one broken fetcher never
aborts the run for the rest. Every tier is wrapped with timeouts and
retry/backoff. A company with no known ATS and no JSON-LD data just shows up
in the digest's "broken fetchers" section for you to check manually (there's
no browser-rendering/AI fallback — see "Design choice" below).

**Company list lives in the database**, not a YAML file, so the Streamlit UI
and the daily cron job always see the same data. `companies.seed.yaml` is
only used once to bootstrap the DB (`--seed`).

**Adding a company in the UI** shows its favicon (via Google's free favicon
endpoint, no API key) and lets you run a live "Detect & preview" check —
same tiered detection used by the real pipeline — before you save, so you
immediately see e.g. "Detected Ashby — 30 jobs found" or a clear failure
reason. Existing companies have the same check available as "Re-check now".

**"Run now" + run history**: the home page in the UI has a "Run now" button
that runs the real pipeline synchronously (same code the daily cron uses)
and shows timing/stats plus the jobs it found when done. Every run (cron or
UI-triggered) is logged in a `runs` table with start time, duration, and
counts, and the home page lists recent runs — expand one to see exactly
which jobs it found.

**Closed/expired jobs — no AI needed**: each successful fetch returns the
*current full list* of a company's open postings straight from its ATS. If
a job that was previously seen is simply absent from the latest fetch, it's
deterministically marked `closed_at` — this is ground truth from the source,
not a guess, and costs nothing. The Jobs page defaults to hiding closed
postings, with a toggle to show them. Separately, you can manually check off
a job as "Done" (applied/reviewed) — that's a user action, unrelated to the
closed-detection, and both are visible/editable as columns in the Jobs table.

## Architecture / hosting

| Piece | Where it runs | Cost |
|---|---|---|
| Database | [Turso](https://turso.tech) (remote, SQLite-compatible via libSQL) | Free tier |
| Daily pipeline | GitHub Actions, scheduled cron | Free (public or free Actions minutes) |
| UI (edit companies, browse jobs) | [Streamlit Community Cloud](https://streamlit.io/cloud) | Free |
| Notifications | Gmail SMTP | Free |

Nothing here needs a server you maintain, and there's no recurring API cost
at all — no AI calls anywhere in the pipeline.

## One-time setup

### 1. Turso (database)

```bash
curl -sSfL https://get.tur.so/install.sh | bash   # installs the turso CLI
turso auth login                                   # opens a browser, one click

turso db create job-alert-tool
turso db show job-alert-tool --url                 # -> TURSO_DATABASE_URL
turso db tokens create job-alert-tool               # -> TURSO_AUTH_TOKEN
```

### 2. Gmail app password (for the digest)

1. Turn on 2-Step Verification on the sending Gmail account if it isn't already.
2. Go to https://myaccount.google.com/apppasswords and create an app password
   (name it e.g. "job-alert-tool") → `GMAIL_APP_PASSWORD` (16 characters).
3. `GMAIL_ADDRESS` is that Gmail address. `DIGEST_TO_EMAIL` is optional —
   leave unset to just email yourself.

### 3. GitHub repo + secrets

```bash
gh repo create job-alert-tool --private --source=. --remote=origin
git add -A && git commit -m "Initial commit"
git push -u origin main

gh secret set TURSO_DATABASE_URL
gh secret set TURSO_AUTH_TOKEN
gh secret set GMAIL_ADDRESS
gh secret set GMAIL_APP_PASSWORD
gh secret set DIGEST_TO_EMAIL   # optional
```

The workflow in `.github/workflows/daily.yml` runs daily at 03:00 UTC and can
also be triggered manually from the Actions tab ("Run workflow").

### 4. Seed the company list (once)

Locally, with `.env` populated (see `.env.example`):

```bash
pip install -r requirements.txt
python -m src.main --seed
```

This loads `companies.seed.yaml` into the DB. After this, **edit the company
list from the Streamlit UI**, not this file.

### 5. Deploy the UI (Streamlit Community Cloud)

1. Go to https://share.streamlit.io → "New app".
2. Pick this repo, branch `main`, main file path `ui/app.py`.
3. In "Advanced settings" → Secrets, paste the contents of
   `ui/.streamlit/secrets.toml.example` filled in with your real Turso
   values (the UI doesn't need the Gmail secrets — only the cron job sends
   email).
4. Deploy. You now have a URL to edit companies / browse jobs from anywhere.

## Local development

```bash
cp .env.example .env    # fill in values (or leave TURSO_* blank to use a
                         # local SQLite file at data/local.db for testing)
pip install -r requirements.txt

python -m src.main --seed              # load the seed company list once
python -m src.main --test-company "Stripe"   # debug fetchers for one company
python -m src.main --dry-run           # full run, skip the email send
python -m src.main                     # full run, sends the digest

streamlit run ui/app.py                # local UI at http://localhost:8501
```

`--test-company` runs every fetch tier independently for that one company
and prints which tier(s) succeed/fail and how many jobs each found — the
fastest way to debug a new company's career page.

## Config reference (`config.yaml`)

- `filters.keywords` / `filters.locations` — the only filtering in the whole
  pipeline: a job must match a keyword (if any are set) AND a location (if
  any are set, with `always_allow_remote` as an override). Empty list on
  either = no filtering on that dimension.
- `fetch.ats_cache_ttl_days` — how often to re-run ATS detection for a company
  even if it's cached.
- `fetch.max_sitemap_urls` — cost/time bound on the sitemap-crawl tier.

## Design choice: no AI, no Playwright tier

The original design for this tool included an AI fit-scoring step and a
last-resort Playwright-render + Claude-extraction tier for companies with no
known ATS. Both were deliberately dropped: the digest is meant to be
reviewed manually day-to-day, and the person running this didn't want the
AI cost/complexity for scoring or for the rare company that needs
browser-rendering to scrape. If you want either back later:
- **Scoring**: re-introduce a step after `filter_jobs` that calls an LLM with
  a profile description and stores a score, then sort/filter the digest by it.
- **Playwright+AI tier**: re-add a third tier in
  `fetch_company_jobs_tiered` (`src/pipeline.py`) that renders the page and
  extracts postings via an LLM call, for companies where both Tier 1 and
  Tier 2 fail.

## Notes on the fetch tiers

- **Greenhouse, Lever, Ashby, Recruitee, SmartRecruiters, Workable** have
  stable public JSON APIs and are the most reliable tier.
- **Workday** has no officially documented public API; the implementation in
  `src/fetchers/ats_api.py::fetch_workday` is best-effort and tenant-specific.
  If it fails for a given company, the pipeline automatically falls through
  to the JSON-LD/sitemap tier — this is expected and handled.
- If both tiers fail for a company, it's marked broken in the DB and listed
  in the digest's "broken fetchers" section rather than aborting the run.
