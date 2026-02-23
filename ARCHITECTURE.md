# DASH News Agent – Architecture & Setup

## Goals
- Collect daily news for `DASH`.
- Produce a concise daily summary.
- Provide **non-predictive** sentiment labeling (bullish/neutral/bearish) as a proxy signal, not a forecast.

## High-Level Architecture
- **Source Feeds (RSS)**
  - Yahoo Finance RSS for ticker headlines
  - Google News RSS search for query-driven coverage
- **Collector** (`news_agent.py`)
  - Fetches RSS feeds
  - Normalizes + deduplicates items
- **Summarizer**
  - Extractive summary from combined item titles + summaries
- **Sentiment Proxy**
  - Simple lexicon score
  - Labels: bullish / neutral / bearish
- **Report Writer**
  - Markdown report per run

## Data Flow
1. Render RSS URLs with ticker/query.
2. Fetch each feed with a custom User-Agent.
3. Parse entries (title, link, summary, published).
4. Deduplicate by link/title.
5. Summarize combined text.
6. Score sentiment using lexicon.
7. Write report to `reports/`.

## Files
- `news_agent.py` – CLI entry point for collection + summary + report.
- `requirements.txt` – Python dependencies.
- `reports/` – Output folder for daily reports.
- `sources.json` (optional) – Custom feed list.
- `data/news.db` – SQLite store for raw items.
- `site/` – Static site output (latest + archive).
- `ARCHITECTURE.md` – This document.

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run (Manual)
```bash
python3 news_agent.py \
  --ticker DASH \
  --query "DoorDash stock" \
  --date 2026-02-23 \
  --db data/news.db \
  --out reports/2026-02-23.md \
  --site site \
  --cname dash.example.com
```

## Run (Cron-friendly)
Example daily cron at 7:30 AM local time:
```bash
30 7 * * * /path/to/.venv/bin/python /path/to/news_collection/news_agent.py --ticker DASH --query "DoorDash stock" --out /path/to/news_collection/reports/$(date +\%F).md --site /path/to/news_collection/site
```

## Source Configuration (Optional)
Create a `sources.json` to override defaults:
```json
{
  "sources": [
    {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/rss/headline?s={ticker}"},
    {"name": "Google News", "url": "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"}
  ]
}
```

## Limitations
- RSS summaries are short and sometimes incomplete.
- Sentiment is a **proxy** and not a trading signal.
- No price prediction is generated.

## Static Hosting (Later)
- The site output is in `site/` with:
  - `site/index.html` (latest report)
  - `site/archive.html` (archive index)
  - `site/archive/YYYY-MM-DD.html` (daily reports)
- You can host `site/` via GitHub Pages, Cloudflare Pages, or Netlify when ready.
- For GitHub Pages custom domain, pass `--cname dash.example.com` so a `CNAME` file is generated.

## GitHub Pages (dash.peigenyou.com)
Use the repo `https://github.com/fusubacon/daily-report`.

1. Set the git remote:
   ```bash
   git init
   git remote add origin https://github.com/fusubacon/daily-report.git
   ```
2. Publish the site:
   ```bash
   ./publish.sh site
   ```
3. In GitHub repo settings, enable Pages from branch `gh-pages`.
4. Set Custom domain to `dash.peigenyou.com` and enable HTTPS.

### Squarespace DNS
Add a CNAME record:
- Host/Name: `dash`
- Type: `CNAME`
- Value/Points to: `fusubacon.github.io`

## GitHub Actions (Daily Auto-Refresh)
This repo includes `.github/workflows/daily-report.yml` to build and publish daily.

1. Push the repo to GitHub.
2. In GitHub repo settings, ensure Actions are enabled.
3. Confirm Pages is set to `gh-pages`.
4. Trigger once via “Run workflow” to generate the first site.

## Optimization Hooks
- Replace RSS with paid APIs for deeper coverage.
- Add entity linking + topic clustering.
- Replace extractive summary with LLM summarization.
- Add multi-day trend indicators (news volume, sentiment slope).
- Store raw items in SQLite for auditability.

## Safety & Compliance
- Outputs are informational. No investment advice.
- Sentiment is explicitly non-predictive.
