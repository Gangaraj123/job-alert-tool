# Job Alert Tool

Tracks a list of companies' career pages, finds new job postings, scores
them against your profile with Claude, and sends a ranked daily digest to
Telegram. Includes a Streamlit UI for editing the company list and browsing
scraped jobs.

## How it works

```
companies (DB) ──> ATS detector (cached in DB)
                        │
                        ▼
          ┌── Tier 1: ATS JSON API (Greenhouse/Lever/Ashby/Workable/
          │            SmartRecruiters/Workday/Recruitee)
          ├── Tier 2: JSON-LD JobPosting schema + bounded sitemap crawl
          └── Tier 3: Playwright render + Claude extraction (last resort)
                        │
                        ▼
                 normalize → pre-filter (keywords/location)
                        │
                        ▼
              dedupe against DB (seen job IDs)
                        │
                        ▼
      AI fit-scoring (Claude + your profile.md, prompt-cached)
                        │
                        ▼
         drop jobs below threshold → Telegram digest
         (ranked by score, grouped by priority,
          + a "broken fetchers" section)
```

Each company is fetched inside its own try/except — one broken fetcher never
aborts the run for the rest. Every tier is wrapped with timeouts and
retry/backoff.

**Company list lives in the database**, not a YAML file, so the Streamlit UI
and the daily cron job always see the same data. `companies.seed.yaml` is
only used once to bootstrap the DB (`--seed`).

## Architecture / hosting

| Piece | Where it runs | Cost |
|---|---|---|
| Database | [Turso](https://turso.tech) (remote, SQLite-compatible via libSQL) | Free tier |
| Daily pipeline | GitHub Actions, scheduled cron | Free (public or free Actions minutes) |
| UI (edit companies, browse jobs) | [Streamlit Community Cloud](https://streamlit.io/cloud) | Free |
| AI scoring + extraction | Anthropic API (Claude) | Pennies/day at this scale |
| Notifications | Telegram Bot API | Free |

Nothing here needs a server you maintain. The only real recurring cost is
Claude API usage, which for a few dozen companies and new postings per day is
a few cents.

## One-time setup

### 1. Turso (database)

```bash
curl -sSfL https://get.tur.so/install.sh | bash   # installs the turso CLI
turso auth login                                   # opens a browser, one click

turso db create job-alert-tool
turso db show job-alert-tool --url                 # -> TURSO_DATABASE_URL
turso db tokens create job-alert-tool               # -> TURSO_AUTH_TOKEN
```

### 2. Anthropic API key

Create a key at https://console.anthropic.com/settings/keys → `ANTHROPIC_API_KEY`.

> **Model names**: `config.yaml` defaults to `claude-haiku-5-5` for both
> scoring and the Playwright-extraction tier. If your account doesn't have
> access to that exact id, swap it for whatever Haiku id you do have access
> to (e.g. `claude-haiku-4-5-20251001`) — check with the Anthropic console or
> `claude models list`.

### 3. Telegram bot

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → get the bot token (`TELEGRAM_BOT_TOKEN`).
2. Message your new bot anything, then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `chat.id` from
   the response → `TELEGRAM_CHAT_ID`.

### 4. GitHub repo + secrets

```bash
gh repo create job-alert-tool --private --source=. --remote=origin
git add -A && git commit -m "Initial commit"
git push -u origin main

gh secret set TURSO_DATABASE_URL
gh secret set TURSO_AUTH_TOKEN
gh secret set ANTHROPIC_API_KEY
gh secret set TELEGRAM_BOT_TOKEN
gh secret set TELEGRAM_CHAT_ID
```

The workflow in `.github/workflows/daily.yml` runs daily at 03:00 UTC and can
also be triggered manually from the Actions tab ("Run workflow").

### 5. Seed the company list (once)

Locally, with `.env` populated (see `.env.example`):

```bash
pip install -r requirements.txt
python -m src.main --seed
```

This loads `companies.seed.yaml` into the DB. After this, **edit the company
list from the Streamlit UI**, not this file.

### 6. Deploy the UI (Streamlit Community Cloud)

1. Go to https://share.streamlit.io → "New app".
2. Pick this repo, branch `main`, main file path `ui/app.py`.
3. In "Advanced settings" → Secrets, paste the contents of
   `ui/.streamlit/secrets.toml.example` filled in with your real values.
4. Deploy. You now have a URL to edit companies / browse jobs from anywhere.

### 7. Set your profile

Edit `profile.md` with your real background, skills, and what you're looking
for — this is what Claude scores every job against.

## Local development

```bash
cp .env.example .env    # fill in values (or leave TURSO_* blank to use a
                         # local SQLite file at data/local.db for testing)
pip install -r requirements.txt
python -m playwright install chromium

python -m src.main --seed              # load the seed company list once
python -m src.main --test-company "Stripe"   # debug fetchers for one company
python -m src.main --dry-run           # full run, skip the Telegram send
python -m src.main                     # full run, sends the digest

streamlit run ui/app.py                # local UI at http://localhost:8501
```

`--test-company` runs every fetch tier independently for that one company
and prints which tier(s) succeed/fail and how many jobs each found — the
fastest way to debug a new company's career page.

## Config reference (`config.yaml`)

- `filters.keywords` / `filters.locations` — cheap pre-filter before any AI
  call. Empty list = no filtering on that dimension.
- `scoring.min_fit_score_for_digest` — jobs below this are stored (so you can
  see them in the UI / avoid re-fetching) but excluded from the Telegram digest.
- `fetch.ats_cache_ttl_days` — how often to re-run ATS detection for a company
  even if it's cached.
- `fetch.max_sitemap_urls` / `fetch.max_page_text_chars` — cost/time bounds
  on the sitemap-crawl and Playwright tiers.

## Notes on the fetch tiers

- **Greenhouse, Lever, Ashby, Recruitee, SmartRecruiters, Workable** have
  stable public JSON APIs and are the most reliable tier.
- **Workday** has no officially documented public API; the implementation in
  `src/fetchers/ats_api.py::fetch_workday` is best-effort and tenant-specific.
  If it fails for a given company, the pipeline automatically falls through
  to the JSON-LD/sitemap tier, then Playwright — this is expected and handled.
- The **Playwright + Claude** tier is the most expensive (headless browser +
  one LLM call per company) and is only reached when both earlier tiers find
  nothing, which keeps typical runs cheap.
