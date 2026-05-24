"""
Demo: Search news by ticker via ESPClient.

Shows how to:
  - Query news events for specific tickers
  - Distinguish breaking_news vs daily_news
  - Fetch full article body by news ID

Prerequisites:
  - ESP running on http://127.0.0.1:19702
  - MongoDB running on localhost:27018 with market_news.ticker_news

Usage:
  cd qfinzero
  python demos/esp/news_search.py
"""

from qfinzero.clients.esp import ESPClient


def main():
    with ESPClient() as esp:
        # ── 1. Recent NVDA news ───────────────────────────────────
        print("=== NVDA News (2025-01-06 to 2025-01-10) ===\n")

        result = esp.query_events(
            mode="window",
            start_utc="2025-01-06T00:00:00Z",
            end_utc="2025-01-10T00:00:00Z",
            event_types=["breaking_news", "daily_news"],
            tickers=["NVDA"],
            limit=10,
            view="full",
        )

        if not result["events"]:
            print("  No news found (is MongoDB running on port 27018?)")
        else:
            for ev in result["events"]:
                p = ev.get("payload", {})
                tickers_str = ", ".join(ev.get("tickers", [])[:5])
                print(f"  [{ev['event_type']:>13}] {ev['time_utc'][:16]}")
                print(f"    {ev['title'][:80]}")
                print(f"    Tickers: {tickers_str}")
                print(f"    URL: {p.get('article_url', 'N/A')}")
                if ev.get("snippet"):
                    print(f"    Snippet: {ev['snippet'][:100]}...")
                print()

        # ── 2. Fetch full article body ────────────────────────────
        if result["events"]:
            first = result["events"][0]
            news_id = first["source_id"]
            print(f"=== Full Article: {news_id} ===\n")

            try:
                body = esp.news_body(news_id)
                print(f"  Title: {body.get('title', 'N/A')}")
                print(f"  Author: {body.get('author', 'N/A')}")
                print(f"  Published: {body.get('published_utc', 'N/A')}")
                print(f"  URL: {body.get('article_url', 'N/A')}")
                desc = body.get("description") or ""
                print(f"  Description: {desc[:200]}")
                kw = body.get("keywords") or []
                if kw:
                    print(f"  Keywords: {', '.join(kw[:10])}")
            except Exception as e:
                print(f"  Error fetching body: {e}")

        # ── 3. Multi-ticker news ──────────────────────────────────
        print("\n=== SPY + QQQ News (2025-01-06 to 2025-01-07) ===\n")

        result = esp.query_events(
            mode="window",
            start_utc="2025-01-06T00:00:00Z",
            end_utc="2025-01-07T00:00:00Z",
            event_types=["breaking_news", "daily_news"],
            tickers=["SPY", "QQQ"],
            limit=10,
            view="compact",
        )

        for ev in result["events"]:
            print(f"  {ev['time_utc'][:16]}  {ev['title'][:70]}")

        print(f"\n  {len(result['events'])} news articles")


if __name__ == "__main__":
    main()
