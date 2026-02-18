"""
Demo: GateAgent trigger check via NPPClient.

Shows how to:
  - Check for upcoming high-importance events (triggers)
  - Use trigger reason codes for agent wakeup decisions
  - Simulate GateAgent polling loop with replay mode

Prerequisites:
  - NPP running on http://127.0.0.1:19330

Usage:
  cd qfinzero
  python demos/npp/trigger_check.py
"""

from qfinzero.clients.npp import NPPClient


def main():
    with NPPClient() as npp:
        # ── 1. Next triggers (upcoming 24h) ───────────────────────
        print("=== Next Triggers (upcoming 24h, medium+ importance) ===\n")

        result = npp.next_triggers(
            min_importance="medium",
            horizon_minutes=1440,
            limit=5,
        )

        if not result["triggers"]:
            print("  No triggers found in the next 24h")
        else:
            for t in result["triggers"]:
                ev = t["event"]
                reasons = ", ".join(t["reason_codes"])
                print(f"  Trigger at {t['trigger_time_utc'][:16]}")
                print(f"    Event: {ev['title'][:60]}")
                print(f"    Type: {ev['event_type']}  Importance: {ev['importance']}")
                print(f"    Reasons: {reasons}")
                print()

        # ── 2. Watchlist triggers ─────────────────────────────────
        print("=== Watchlist Triggers (NVDA, AAPL, SPY) ===\n")

        result = npp.next_triggers(
            tickers=["NVDA", "AAPL", "SPY"],
            min_importance="medium",
            horizon_minutes=1440,
            limit=5,
        )

        for t in result["triggers"]:
            ev = t["event"]
            tickers_str = ", ".join(ev.get("tickers", [])[:3])
            print(
                f"  {t['trigger_time_utc'][:16]}  "
                f"{ev['event_type']:>16}  {ev['title'][:40]}  [{tickers_str}]"
            )

        # ── 3. Replay: simulate GateAgent on 2025-01-29 ──────────
        print("\n=== Replay: GateAgent on 2025-01-29 08:00 UTC ===\n")

        result = npp.next_triggers(
            min_importance="high",
            horizon_minutes=480,  # next 8 hours
            limit=5,
            now_utc="2025-01-29T08:00:00Z",
        )

        if not result["triggers"]:
            print("  No high-importance triggers in the next 8h")
        else:
            for t in result["triggers"]:
                ev = t["event"]
                reasons = ", ".join(t["reason_codes"])
                print(f"  {t['trigger_time_utc'][:16]}  {ev['title'][:50]}  [{reasons}]")

        # ── 4. Streaming poll simulation ──────────────────────────
        print("\n=== Stream Poll Simulation ===\n")

        cursor = None
        for poll in range(3):
            result = npp.stream(
                cursor=cursor,
                limit=5,
                now_utc="2025-01-29T14:00:00Z",
            )
            cursor = result.get("next_cursor")
            count = len(result["events"])
            print(f"  Poll {poll + 1}: {count} new events")
            for ev in result["events"][:2]:
                print(f"    {ev['time_utc'][:16]}  {ev['title'][:50]}")
            if not cursor:
                print("  (no more events)")
                break


if __name__ == "__main__":
    main()
