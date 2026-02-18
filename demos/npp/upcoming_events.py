"""
Demo: Query upcoming events via NPPClient.

Shows how to:
  - Check server health
  - Query upcoming events (all types)
  - Query events that just happened
  - Query a custom time window
  - Use cursor-based pagination
  - Use replay mode with now_utc

Prerequisites:
  - NPP running on http://127.0.0.1:19340

Usage:
  cd qfinzero
  python demos/npp/upcoming_events.py
"""

from qfinzero.clients.npp import NPPClient


def main():
    with NPPClient() as npp:
        # Health check
        h = npp.health()
        print("NPP health:", h["status"])
        print("Data freshness:", h["data_freshness"])

        # ── 1. Upcoming events (next 24h) ─────────────────────────
        print("\n=== Upcoming Events (next 24h) ===\n")

        result = npp.query_events(
            mode="upcoming",
            horizon_minutes=1440,
            limit=10,
            view="compact",
        )

        for ev in result["events"]:
            print(
                f"  [{ev['event_type']:>16}] {ev['time_utc'][:16]}  "
                f"{ev['importance']:>6}  {ev['title'][:60]}"
            )
        print(f"\n  Returned {len(result['events'])} events")
        if result.get("next_cursor"):
            print(f"  More available (cursor: {result['next_cursor'][:20]}...)")

        # ── 2. Just happened (last 6h) ────────────────────────────
        print("\n=== Just Happened (last 6h) ===\n")

        result = npp.query_events(
            mode="just_happened",
            horizon_minutes=360,
            limit=10,
            view="full",
        )

        for ev in result["events"]:
            snippet = ev.get("snippet") or ""
            print(
                f"  [{ev['event_type']:>16}] {ev['time_utc'][:16]}  "
                f"{ev['title'][:40]}  {snippet[:40]}"
            )

        # ── 3. Window query ───────────────────────────────────────
        print("\n=== Window Query (2025-01-06 to 2025-01-07) ===\n")

        result = npp.query_events(
            mode="window",
            start_utc="2025-01-06T00:00:00Z",
            end_utc="2025-01-07T00:00:00Z",
            limit=10,
            view="compact",
        )

        for ev in result["events"]:
            tickers_str = ",".join(ev.get("tickers", [])[:3])
            print(
                f"  [{ev['event_type']:>16}] {ev['time_utc'][:16]}  "
                f"{ev['title'][:40]}  tickers=[{tickers_str}]"
            )

        # ── 4. Pagination ─────────────────────────────────────────
        print("\n=== Pagination Demo ===\n")

        cursor = None
        total = 0
        for page_num in range(3):
            result = npp.query_events(
                mode="window",
                start_utc="2025-01-06T00:00:00Z",
                end_utc="2025-01-10T00:00:00Z",
                limit=5,
                cursor=cursor,
                view="compact",
            )
            count = len(result["events"])
            total += count
            print(f"  Page {page_num + 1}: {count} events")
            cursor = result.get("next_cursor")
            if not cursor:
                print("  (no more pages)")
                break

        print(f"  Total fetched: {total}")

        # ── 5. Replay mode ────────────────────────────────────────
        print("\n=== Replay Mode (pretend it's 2025-06-15 10:00 UTC) ===\n")

        result = npp.query_events(
            mode="upcoming",
            horizon_minutes=120,
            limit=5,
            now_utc="2025-06-15T10:00:00Z",
        )

        for ev in result["events"]:
            print(f"  {ev['time_utc'][:16]}  {ev['title'][:60]}")


if __name__ == "__main__":
    main()
