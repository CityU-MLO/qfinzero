"""
Demo: Query US economic calendar via ESPClient.

Shows how to:
  - Query economic events for a date range
  - Filter by importance (high = FOMC, CPI, NFP, etc.)
  - Display actual vs consensus data
  - Use full view to get descriptions

Prerequisites:
  - ESP running on http://127.0.0.1:19330

Usage:
  cd qfinzero
  python demos/esp/econ_calendar.py
"""

from qfinzero.clients.esp import ESPClient


def main():
    with ESPClient() as esp:
        # ── 1. All US econ events this week ───────────────────────
        print("=== US Econ Events (2025-01-06 to 2025-01-10) ===\n")

        result = esp.econ_calendar(
            start_date="2025-01-06",
            end_date="2025-01-10",
            limit=30,
        )

        header = f"{'Date':^10} | {'Time(UTC)':^8} | {'Imp':>4} | {'Event':^35} | {'Actual':>8} | {'Cons':>8} | {'Prev':>8}"
        print(header)
        print("-" * len(header))

        for ev in result["events"]:
            p = ev.get("payload", {})
            time_part = ev["time_utc"][11:16] if len(ev["time_utc"]) > 11 else "??:??"
            print(
                f"{ev['time_utc'][:10]:^10} | {time_part:^8} | "
                f"{ev['importance'][:4]:>4} | {ev['title'][:35]:^35} | "
                f"{(p.get('actual') or ''):>8} | {(p.get('consensus') or ''):>8} | "
                f"{(p.get('previous') or ''):>8}"
            )

        print(f"\nTotal: {len(result['events'])} events")

        # ── 2. High-importance events only ────────────────────────
        print("\n=== High-Importance Events (2025-01-01 to 2025-03-31) ===\n")

        result = esp.econ_calendar(
            start_date="2025-01-01",
            end_date="2025-03-31",
            min_importance="high",
            limit=20,
        )

        for ev in result["events"]:
            p = ev.get("payload", {})
            actual = p.get("actual") or ""
            status_icon = "!" if ev["status"] == "occurred" else "~"
            print(
                f"  {status_icon} {ev['time_utc'][:10]}  {ev['title'][:45]:<45}  "
                f"actual={actual}"
            )

        print(f"\n  {len(result['events'])} high-importance events (FOMC, CPI, NFP, GDP, etc.)")

        # ── 3. Full view with descriptions ────────────────────────
        print("\n=== Full Event Details (single day) ===\n")

        result = esp.query_events(
            mode="window",
            start_utc="2025-01-10T00:00:00Z",
            end_utc="2025-01-11T00:00:00Z",
            event_types=["macro_calendar"],
            limit=5,
            view="full",
        )

        for ev in result["events"]:
            p = ev.get("payload", {})
            print(f"  {ev['title']}")
            print(f"    Time: {ev['time_utc']}")
            print(f"    Status: {ev['status']}  Importance: {ev['importance']}")
            desc = p.get("description") or ""
            if desc:
                print(f"    Description: {desc[:120]}...")
            print()


if __name__ == "__main__":
    main()
