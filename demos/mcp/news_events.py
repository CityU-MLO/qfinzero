"""
Demo: News & Events via MCP (NPP tools)

Shows how an external system or LLM connects to QFinZero through the MCP
server and calls NPP tools to query market-moving events.

Covers:
  - npp_health
  - npp_query_events     — unified event search (upcoming / window modes)
  - npp_econ_calendar    — macro economic events
  - npp_earnings_calendar— earnings releases
  - npp_next_triggers    — get agent wakeup triggers
  - npp_stream_events    — incremental cursor-based polling
  - npp_timeline         — time-bucketed event summary

Prerequisites:
  - NPP running on http://127.0.0.1:19702
  - MCP server deps: pip install "mcp[cli]>=1.0.0"

Usage:
  cd qfinzero
  python demos/mcp/news_events.py
"""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "mcp", "server.py")


async def call(session: ClientSession, tool: str, **kwargs) -> any:
    """Call an MCP tool and return the parsed JSON result."""
    result = await session.call_tool(tool, kwargs)
    return json.loads(result.content[0].text)


async def main():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_SCRIPT],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ── Health check ──────────────────────────────────────────────
            health = await call(session, "npp_health")
            print(f"NPP health: {health.get('status')}")
            print(f"Data freshness: {health.get('data_freshness', {})}\n")

            # ── 1. Upcoming events (replay mode) ──────────────────────────
            # Use now_utc to pin time for reproducible results
            NOW = "2025-01-06T14:30:00Z"

            print(f"=== Upcoming Events (next 24h from {NOW[:10]}) ===\n")

            result = await call(
                session, "npp_query_events",
                mode="upcoming",
                horizon_minutes=1440,
                limit=10,
                view="compact",
                now_utc=NOW,
            )

            for ev in result["events"]:
                tickers = ",".join(ev.get("tickers", [])[:3]) or "—"
                print(
                    f"  [{ev['event_type']:>16}] {ev['time_utc'][:16]}  "
                    f"{ev['importance']:>6}  [{tickers:<12}]  {ev['title'][:50]}"
                )
            print(f"\n  {len(result['events'])} events returned")
            cursor = result.get("next_cursor")

            # ── 2. Window query ───────────────────────────────────────────
            print("\n=== Window Query (2025-01-06, earnings only) ===\n")

            result = await call(
                session, "npp_query_events",
                mode="window",
                start_utc="2025-01-06T00:00:00Z",
                end_utc="2025-01-07T00:00:00Z",
                event_types=["earnings"],
                limit=10,
                view="full",
            )

            for ev in result["events"]:
                payload = ev.get("payload") or {}
                eps_est = payload.get("eps_estimate", "?")
                eps_act = payload.get("eps_actual", "?")
                print(
                    f"  {ev['time_utc'][:16]}  {ev['title'][:40]:<40}  "
                    f"EPS est={eps_est} act={eps_act}"
                )

            # ── 3. Pagination (cursor-based) ───────────────────────────────
            print("\n=== Cursor Pagination (2025-01-06 to 2025-01-10) ===\n")

            page_cursor = None
            total = 0
            for page_num in range(1, 4):
                result = await call(
                    session, "npp_query_events",
                    mode="window",
                    start_utc="2025-01-06T00:00:00Z",
                    end_utc="2025-01-10T00:00:00Z",
                    limit=5,
                    cursor=page_cursor,
                    view="compact",
                )
                count = len(result["events"])
                total += count
                print(f"  Page {page_num}: {count} events")
                page_cursor = result.get("next_cursor")
                if not page_cursor:
                    print("  (no more pages)")
                    break
            print(f"  Total fetched: {total}")

            # ── 4. Stream (incremental polling) ───────────────────────────
            print("\n=== Stream (incremental polling from cursor) ===\n")

            if cursor:
                streamed = await call(
                    session, "npp_stream_events",
                    cursor=cursor,
                    limit=5,
                    now_utc=NOW,
                )
                print(f"  Events since cursor: {len(streamed['events'])}")
                for ev in streamed["events"]:
                    print(f"    {ev['time_utc'][:16]}  {ev['title'][:60]}")
            else:
                print("  (no cursor from earlier query)")

            # ── 5. Economic calendar ──────────────────────────────────────
            print("\n=== Economic Calendar (Jan 2025, high importance) ===\n")

            econ = await call(
                session, "npp_econ_calendar",
                start_date="2025-01-06",
                end_date="2025-01-31",
                min_importance="high",
                limit=10,
            )

            print(f"{'Date':^12} | {'Importance':^10} | Title")
            print("-" * 70)
            for ev in econ["events"]:
                print(
                    f"  {ev['time_utc'][:10]:^10} | {ev['importance']:^10} | {ev['title'][:50]}"
                )
            print(f"\n  {len(econ['events'])} macro events")

            # ── 6. Earnings calendar ──────────────────────────────────────
            print("\n=== Earnings Calendar (Jan 2025, AAPL / MSFT / NVDA) ===\n")

            earnings = await call(
                session, "npp_earnings_calendar",
                start_date="2025-01-01",
                end_date="2025-02-28",
                tickers=["AAPL", "MSFT", "NVDA"],
            )

            for ev in earnings["events"]:
                print(
                    f"  {ev['time_utc'][:16]}  {ev['title'][:60]}"
                )
            print(f"\n  {len(earnings['events'])} earnings events")

            # ── 7. Next triggers (agent wakeup) ───────────────────────────
            print("\n=== Next Triggers (agent wakeup events) ===\n")

            triggers = await call(
                session, "npp_next_triggers",
                tickers=["AAPL", "MSFT", "NVDA", "SPY"],
                min_importance="high",
                horizon_minutes=2880,   # next 2 days
                limit=5,
                now_utc=NOW,
            )

            for t in triggers["triggers"]:
                print(
                    f"  Wake at: {t['trigger_time_utc'][:16]}  "
                    f"reason={t['reason_codes']}  "
                    f"{t['event']['title'][:50]}"
                )

            # ── 8. Timeline (bucketed summary) ────────────────────────────
            print("\n=== Event Timeline for AAPL (2025-01-06, hourly buckets) ===\n")

            timeline = await call(
                session, "npp_timeline",
                tickers=["AAPL"],
                start_utc="2025-01-06T00:00:00Z",
                end_utc="2025-01-07T00:00:00Z",
                bucket_minutes=60,
            )

            for bucket in timeline.get("buckets", []):
                if bucket["count"] > 0:
                    print(
                        f"  {bucket['bucket_start_utc'][11:16]}–{bucket['bucket_end_utc'][11:16]}  "
                        f"{bucket['count']:2d} events: "
                        + ", ".join(e["title"][:30] for e in bucket["events"][:2])
                    )


if __name__ == "__main__":
    asyncio.run(main())
