#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import List, Dict
import sqlite3
import html

import feedparser
import requests

DEFAULT_SOURCES = [
    {
        "name": "Yahoo Finance",
        "url": "https://finance.yahoo.com/rss/headline?s={ticker}",
    },
    {
        "name": "Google News",
        "url": "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "PR Newswire",
        "url": "https://www.prnewswire.com/rss/news-releases-list.rss",
    },
    {
        "name": "Business Wire",
        "url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeEFhWXg==",
    },
    {
        "name": "SEC - Company Filings (CIK 0001792789)",
        "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001792789&type=&dateb=&owner=exclude&count=40&output=atom",
    },
]

STOPWORDS = set(
    "a an the and or but if while of to in on for with without by as is are was were be been "
    "this that these those from at it its into over under about after before between not no "
    "you your we our they their i me my us he she him her them his hers ours theirs"
    .split()
)

POS_WORDS = set(
    "beat beats growth strong stronger surge surges record optimistic upgrade upgraded buy outperform".split()
)
NEG_WORDS = set(
    "miss misses decline weak weaker plunge plunges downgrade downgraded sell underperform".split()
)


def load_sources(path: Path, ticker: str, query: str) -> List[Dict[str, str]]:
    if path.exists():
        data = json.loads(path.read_text())
        sources = data.get("sources", [])
    else:
        sources = DEFAULT_SOURCES
    rendered = []
    for s in sources:
        rendered.append({
            "name": s["name"],
            "url": s["url"].format(ticker=ticker, query=query),
        })
    return rendered


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    # Some feeds block default User-Agent
    headers = {"User-Agent": "news-collector/1.0"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return feedparser.parse(resp.text)


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def extract_items(feed: feedparser.FeedParserDict, source_name: str) -> List[Dict[str, str]]:
    items = []
    for e in feed.entries:
        title = normalize_text(getattr(e, "title", ""))
        link = getattr(e, "link", "")
        summary = normalize_text(getattr(e, "summary", ""))
        published = normalize_text(getattr(e, "published", ""))
        if not title and not summary:
            continue
        items.append({
            "source": source_name,
            "title": title,
            "link": link,
            "summary": summary,
            "published": published,
        })
    return items


def dedupe(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out = []
    for it in items:
        key = it.get("link") or it.get("title")
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


def summarize_text(text: str, max_sentences: int = 3) -> str:
    # Simple extractive summary: pick top sentences by word frequency
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) <= max_sentences:
        return text.strip()
    words = tokenize(text)
    freq = Counter(words)
    scored = []
    for s in sentences:
        score = sum(freq[w] for w in tokenize(s))
        scored.append((score, s))
    top = [s for _, s in sorted(scored, reverse=True)[:max_sentences]]
    return " ".join([t.strip() for t in top if t.strip()])


def sentiment_score(texts: List[str]) -> Dict[str, int]:
    score = 0
    for t in texts:
        words = tokenize(t)
        score += sum(1 for w in words if w in POS_WORDS)
        score -= sum(1 for w in words if w in NEG_WORDS)
    label = "neutral"
    if score >= 2:
        label = "bullish"
    elif score <= -2:
        label = "bearish"
    return {"score": score, "label": label}


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            title TEXT,
            link TEXT UNIQUE,
            summary TEXT,
            published TEXT,
            fetched_at TEXT
        )
        """
    )
    return conn


def store_items(conn: sqlite3.Connection, items: List[Dict[str, str]], fetched_at: str) -> None:
    if not items:
        return
    rows = [
        (
            i.get("source"),
            i.get("title"),
            i.get("link"),
            i.get("summary"),
            i.get("published"),
            fetched_at,
        )
        for i in items
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO news_items
            (source, title, link, summary, published, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def build_summary_sentiment(items: List[Dict[str, str]]) -> Dict[str, object]:
    combined = " ".join([f"{i['title']}. {i['summary']}" for i in items])
    summary = summarize_text(combined, max_sentences=3) if combined else "No items found."
    sentiment = sentiment_score([i["title"] + " " + i["summary"] for i in items])
    return {"summary": summary, "sentiment": sentiment}

def render_report(date: str, ticker: str, items: List[Dict[str, str]], summary: str, sentiment: Dict[str, int], errors: List[str]) -> str:
    lines = []
    lines.append(f"# {ticker} Daily News Summary")
    lines.append("")
    lines.append(f"Date: {date}")
    lines.append("")
    lines.append("## Summary")
    lines.append(summary)
    lines.append("")
    lines.append(f"Items: {len(items)}")
    lines.append("")
    lines.append("## Sentiment (non-predictive)")
    lines.append(f"Label: {sentiment['label']}")
    lines.append(f"Score: {sentiment['score']}")
    lines.append("")
    if errors:
        lines.append("## Fetch Errors")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("")
    lines.append("## Articles")
    if not items:
        lines.append("No articles found.")
    else:
        for it in items:
            lines.append(f"- {it['title']}")
            if it.get("published"):
                lines.append(f"  Published: {it['published']}")
            if it.get("link"):
                lines.append(f"  Link: {it['link']}")
            if it.get("summary"):
                lines.append(f"  Summary: {it['summary']}")
    return "\n".join(lines)


def render_html_report(date: str, ticker: str, items: List[Dict[str, str]], summary: str, sentiment: Dict[str, int], errors: List[str]) -> str:
    def esc(s: str) -> str:
        return html.escape(s or "")

    lines = []
    lines.append("<!doctype html>")
    lines.append("<html lang=\"en\">")
    lines.append("<head>")
    lines.append("<meta charset=\"utf-8\">")
    lines.append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    lines.append(f"<title>{esc(ticker)} Daily News Summary</title>")
    lines.append("<style>")
    lines.append("body{font-family:system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin:40px; color:#111;}")
    lines.append("h1{margin-bottom:4px;} .meta{color:#555; margin-bottom:20px;}")
    lines.append(".card{border:1px solid #ddd; padding:16px; border-radius:8px; margin-bottom:16px;}")
    lines.append("a{color:#0b57d0; text-decoration:none;} a:hover{text-decoration:underline;}")
    lines.append("</style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append(f"<h1>{esc(ticker)} Daily News Summary</h1>")
    lines.append(f"<div class=\"meta\">Date: {esc(date)} • Items: {len(items)}</div>")
    lines.append("<div class=\"card\">")
    lines.append("<h2>Summary</h2>")
    lines.append(f"<p>{esc(summary)}</p>")
    lines.append("</div>")
    lines.append("<div class=\"card\">")
    lines.append("<h2>Sentiment (non-predictive)</h2>")
    lines.append(f"<p>Label: {esc(sentiment['label'])} • Score: {sentiment['score']}</p>")
    lines.append("</div>")
    if errors:
        lines.append("<div class=\"card\">")
        lines.append("<h2>Fetch Errors</h2>")
        lines.append("<ul>")
        for e in errors:
            lines.append(f"<li>{esc(e)}</li>")
        lines.append("</ul>")
        lines.append("</div>")
    lines.append("<div class=\"card\">")
    lines.append("<h2>Articles</h2>")
    if not items:
        lines.append("<p>No articles found.</p>")
    else:
        lines.append("<ul>")
        for it in items:
            title = esc(it.get("title", ""))
            link = esc(it.get("link", ""))
            published = esc(it.get("published", ""))
            summary_it = esc(it.get("summary", ""))
            if link:
                lines.append(f"<li><a href=\"{link}\">{title}</a></li>")
            else:
                lines.append(f"<li>{title}</li>")
            if published:
                lines.append(f"<div class=\"meta\">Published: {published}</div>")
            if summary_it:
                lines.append(f"<div>{summary_it}</div>")
        lines.append("</ul>")
    lines.append("</div>")
    lines.append("</body>")
    lines.append("</html>")
    return "\n".join(lines)


def write_site(site_dir: Path, date: str, ticker: str, items: List[Dict[str, str]], summary: str, sentiment: Dict[str, int], errors: List[str], cname: str) -> None:
    site_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = site_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    html_report = render_html_report(date, ticker, items, summary, sentiment, errors)
    latest_path = site_dir / "index.html"
    archive_path = archive_dir / f"{date}.html"
    latest_path.write_text(html_report)
    archive_path.write_text(html_report)

    # Build archive index
    archive_files = sorted(archive_dir.glob("*.html"), reverse=True)
    lines = []
    lines.append("<!doctype html>")
    lines.append("<html lang=\"en\">")
    lines.append("<head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    lines.append(f"<title>{html.escape(ticker)} Report Archive</title></head>")
    lines.append("<body>")
    lines.append(f"<h1>{html.escape(ticker)} Report Archive</h1>")
    lines.append("<ul>")
    for f in archive_files:
        day = f.stem
        rel = f"archive/{f.name}"
        lines.append(f"<li><a href=\"{rel}\">{html.escape(day)}</a></li>")
    lines.append("</ul>")
    lines.append("</body></html>")
    (site_dir / "archive.html").write_text("\n".join(lines))
    if cname:
        (site_dir / "CNAME").write_text(cname.strip() + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect and summarize news for a stock ticker.")
    parser.add_argument("--ticker", default="DASH", help="Stock ticker symbol")
    parser.add_argument("--query", default="DoorDash stock", help="News query")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="Report date YYYY-MM-DD")
    parser.add_argument("--sources", default="sources.json", help="Path to sources config JSON")
    parser.add_argument("--db", default="data/news.db", help="SQLite DB path for raw items")
    parser.add_argument("--out", default="reports/latest.md", help="Output report path")
    parser.add_argument("--site", default="site", help="Static site output directory")
    parser.add_argument("--no-site", action="store_true", help="Disable static site output")
    parser.add_argument("--cname", default="", help="Custom domain for GitHub Pages (e.g., dash.example.com)")
    args = parser.parse_args()

    sources_path = Path(args.sources)
    sources = load_sources(sources_path, args.ticker, args.query)

    all_items = []
    errors = []
    for s in sources:
        try:
            feed = fetch_feed(s["url"])
            items = extract_items(feed, s["name"])
            all_items.extend(items)
        except Exception as e:
            msg = f"{s['name']}: {e}"
            errors.append(msg)
            print(f"WARN: failed to fetch {msg}", file=sys.stderr)

    items = dedupe(all_items)
    fetched_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    conn = init_db(Path(args.db))
    store_items(conn, items, fetched_at)
    conn.close()
    meta = build_summary_sentiment(items)
    report = render_report(args.date, args.ticker, items, meta["summary"], meta["sentiment"], errors)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    if not args.no_site:
        write_site(Path(args.site), args.date, args.ticker, items, meta["summary"], meta["sentiment"], errors, args.cname)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
