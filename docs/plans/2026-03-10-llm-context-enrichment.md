# LLM Context Enrichment for Overlay Agent

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add macro and sector context to the LLM overlay agent so DeepSeek can make informed decisions during 2025 backtest.

**Architecture:** A Python script (`generate_llm_context.py`) runs on qlib to extract economy calendar and semiconductor earnings data from existing SQLite databases, outputting structured JSON files. The overlay LLM agent reads these files via SSH at each rebalance day and appends the context to its prompt.

**Tech Stack:** Python 3 (sqlite3, json), SSH for remote file reads, existing DeepSeek LLM integration.

---

### Task 1: Create `generate_llm_context.py` on qlib

**Files:**
- Create: `infra/pmb/demos/generate_llm_context.py` (run on qlib via `scp` + `ssh`)

**Step 1: Write the script**

This script reads from 3 SQLite databases and outputs to `/home/qlib/news/llm_context_2025/`.

```python
#!/usr/bin/env python3
"""
Generate pre-computed LLM context for overlay agent backtest (2025).

Reads from qlib SQLite databases:
  - nasdaq_econ_events.sqlite3 → macro monthly review + upcoming events
  - benzinga_earnings.sqlite3  → semiconductor earnings calendar

Output: /home/qlib/news/llm_context_2025/
  ├── macro/
  │   ├── 2024-12_review.json    # last month review for Jan 2025
  │   ├── 2025-01_review.json
  │   ├── ...
  │   ├── 2025-11_review.json
  │   ├── 2025-01_upcoming.json  # next month events for Jan 2025 = Feb events
  │   ├── ...
  │   └── 2025-12_upcoming.json
  └── semi_earnings_2025.json

Usage (on qlib):
  python3 generate_llm_context.py
"""

import json
import os
import sqlite3

# --- Config ---
OUTPUT_DIR = "/home/qlib/news/llm_context_2025"
ECON_DB = "/home/qlib/news/nasdaq_econ_events.sqlite3"
EARNINGS_DB = "/home/qlib/news/benzinga_earnings.sqlite3"

SEMI_TICKERS = [
    "NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM",
    "MU", "MRVL", "TXN", "LRCX", "KLAC", "AMAT",
]

# ~25 medium-to-high impact US macro events
ECON_EVENT_WHITELIST = [
    # High impact
    "Fed Interest Rate Decision",
    "FOMC Statement",
    "FOMC Press Conference",
    "FOMC Meeting Minutes",
    "Nonfarm Payrolls",
    "Unemployment Rate",
    "CPI",
    "Core CPI",
    "PPI",
    "Core PPI",
    "GDP",
    "ISM Manufacturing PMI",
    "ISM Non-Manufacturing PMI",
    "Retail Sales",
    "Core Retail Sales",
    # Medium impact
    "CB Consumer Confidence",
    "Michigan Consumer Sentiment",
    "Durable Goods Orders",
    "Core Durable Goods Orders",
    "Housing Starts",
    "Building Permits",
    "Initial Jobless Claims",
    "Continuing Jobless Claims",
    "Industrial Production",
    "Capacity Utilization Rate",
    "Trade Balance",
    "Philadelphia Fed Manufacturing Index",
    "NY Empire State Manufacturing Index",
    "Existing Home Sales",
    "New Home Sales",
    "PCE Prices",
    "Core PCE Prices",
    "JOLTS Job Openings",
    "ADP Nonfarm Employment Change",
]


def generate_macro_review(conn, year_month: str) -> dict:
    """Generate review of macro events that occurred in a given month.

    Args:
        conn: sqlite3 connection to nasdaq_econ_events.sqlite3
        year_month: e.g. "2025-01"

    Returns:
        {"month": "2025-01", "events": [{date, event, actual, consensus, previous}, ...]}
    """
    placeholders = ",".join("?" for _ in ECON_EVENT_WHITELIST)
    rows = conn.execute(
        f"""
        SELECT date, event_name, actual, consensus, previous
        FROM econ_events
        WHERE country = 'United States'
          AND date >= ? AND date < ?
          AND event_name IN ({placeholders})
        ORDER BY date, event_name
        """,
        [f"{year_month}-01", _next_month(year_month)] + ECON_EVENT_WHITELIST,
    ).fetchall()

    # Deduplicate (some events appear twice in the DB)
    seen = set()
    events = []
    for date, event, actual, consensus, previous in rows:
        key = (date, event)
        if key in seen:
            continue
        seen.add(key)
        events.append({
            "date": date,
            "event": event,
            "actual": _clean(actual),
            "consensus": _clean(consensus),
            "previous": _clean(previous),
        })

    return {"month": year_month, "events": events}


def generate_macro_upcoming(conn, year_month: str) -> dict:
    """Generate list of upcoming macro events for a given month.

    Only includes date + event name (no data — hasn't happened yet).

    Args:
        conn: sqlite3 connection
        year_month: the month whose events to list, e.g. "2025-02"

    Returns:
        {"month": "2025-02", "events": [{date, event}, ...]}
    """
    placeholders = ",".join("?" for _ in ECON_EVENT_WHITELIST)
    rows = conn.execute(
        f"""
        SELECT DISTINCT date, event_name
        FROM econ_events
        WHERE country = 'United States'
          AND date >= ? AND date < ?
          AND event_name IN ({placeholders})
        ORDER BY date, event_name
        """,
        [f"{year_month}-01", _next_month(year_month)] + ECON_EVENT_WHITELIST,
    ).fetchall()

    events = []
    seen = set()
    for date, event in rows:
        key = (date, event)
        if key in seen:
            continue
        seen.add(key)
        events.append({"date": date, "event": event})

    return {"month": year_month, "events": events}


def generate_semi_earnings(conn) -> dict:
    """Generate semiconductor earnings calendar for 2025.

    Returns:
        {"tickers": [...], "earnings": [{ticker, date, time, fiscal_period,
         fiscal_year, estimated_eps, actual_eps, eps_surprise_percent,
         actual_revenue, estimated_revenue}, ...]}
    """
    placeholders = ",".join("?" for _ in SEMI_TICKERS)
    rows = conn.execute(
        f"""
        SELECT ticker, date, time, fiscal_period, fiscal_year,
               estimated_eps, actual_eps, eps_surprise_percent,
               actual_revenue, estimated_revenue
        FROM earnings
        WHERE ticker IN ({placeholders})
          AND date >= '2025-01-01' AND date <= '2025-12-31'
        ORDER BY date, ticker
        """,
        SEMI_TICKERS,
    ).fetchall()

    earnings = []
    for row in rows:
        earnings.append({
            "ticker": row[0],
            "date": row[1],
            "time": row[2],
            "fiscal_period": row[3],
            "fiscal_year": row[4],
            "estimated_eps": row[5],
            "actual_eps": row[6],
            "eps_surprise_percent": row[7],
            "actual_revenue": row[8],
            "estimated_revenue": row[9],
        })

    return {"tickers": SEMI_TICKERS, "earnings": earnings}


def _next_month(year_month: str) -> str:
    """Return first day of the month after year_month."""
    y, m = int(year_month[:4]), int(year_month[5:7])
    if m == 12:
        return f"{y+1:04d}-01-01"
    return f"{y:04d}-{m+1:02d}-01"


def _clean(val: str) -> str:
    """Clean whitespace and HTML entities from econ event values."""
    if not val:
        return ""
    val = val.strip()
    if val in ("&nbsp;", " "):
        return ""
    return val


def main():
    os.makedirs(f"{OUTPUT_DIR}/macro", exist_ok=True)

    # --- Macro context ---
    econ_conn = sqlite3.connect(ECON_DB)

    # Reviews: 2024-12 through 2025-11 (for Jan-Dec 2025 backtest)
    review_months = ["2024-12"] + [f"2025-{m:02d}" for m in range(1, 12)]
    for ym in review_months:
        review = generate_macro_review(econ_conn, ym)
        path = f"{OUTPUT_DIR}/macro/{ym}_review.json"
        with open(path, "w") as f:
            json.dump(review, f, indent=2)
        print(f"  Written {path} ({len(review['events'])} events)")

    # Upcoming: 2025-01 through 2025-12
    # For month M, upcoming = events scheduled in month M+1
    # But for the backtest, we label by the month the agent is IN
    # So 2025-01_upcoming.json = "what's coming next month" = Feb 2025 events
    for m in range(1, 13):
        current_month = f"2025-{m:02d}"
        if m == 12:
            next_m = "2026-01"
        else:
            next_m = f"2025-{m+1:02d}"
        upcoming = generate_macro_upcoming(econ_conn, next_m)
        path = f"{OUTPUT_DIR}/macro/{current_month}_upcoming.json"
        with open(path, "w") as f:
            json.dump(upcoming, f, indent=2)
        print(f"  Written {path} ({len(upcoming['events'])} events)")

    econ_conn.close()

    # --- Semiconductor earnings ---
    earn_conn = sqlite3.connect(EARNINGS_DB)
    semi = generate_semi_earnings(earn_conn)
    path = f"{OUTPUT_DIR}/semi_earnings_2025.json"
    with open(path, "w") as f:
        json.dump(semi, f, indent=2)
    print(f"  Written {path} ({len(semi['earnings'])} earnings)")
    earn_conn.close()

    print(f"\nDone. Output in {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
```

**Step 2: Copy to qlib and run**

```bash
scp infra/pmb/demos/generate_llm_context.py qlib:/tmp/generate_llm_context.py
ssh qlib "python3 /tmp/generate_llm_context.py"
```

Expected: creates `/home/qlib/news/llm_context_2025/` with ~23 macro files + 1 semi earnings file.

**Step 3: Verify output**

```bash
ssh qlib "ls -la /home/qlib/news/llm_context_2025/macro/ && cat /home/qlib/news/llm_context_2025/macro/2025-01_review.json | python3 -m json.tool | head -30"
ssh qlib "cat /home/qlib/news/llm_context_2025/semi_earnings_2025.json | python3 -m json.tool | head -30"
```

**Step 4: Commit**

```bash
git add infra/pmb/demos/generate_llm_context.py
git commit -m "feat: add generate_llm_context.py for LLM agent macro/earnings context"
```

---

### Task 2: Add context loading to `overlay_helpers.py`

**Files:**
- Modify: `infra/pmb/demos/overlay_helpers.py`

**Step 1: Add SSH-based context loading functions**

Append to `overlay_helpers.py`:

```python
import subprocess

QLIB_CONTEXT_DIR = "/home/qlib/news/llm_context_2025"


def load_remote_json(remote_path: str) -> dict | None:
    """Load a JSON file from qlib via SSH."""
    try:
        result = subprocess.run(
            ["ssh", "qlib", f"cat {remote_path}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        print(f"  [WARN] Failed to load {remote_path}: {e}")
    return None


def load_macro_context(current_month: str) -> dict:
    """Load macro context for a given month.

    Args:
        current_month: e.g. "2025-01"

    Returns:
        {"last_month_review": {...}, "next_month_upcoming": {...}}
    """
    # Previous month review
    y, m = int(current_month[:4]), int(current_month[5:7])
    if m == 1:
        prev_month = f"{y-1:04d}-12"
    else:
        prev_month = f"{y:04d}-{m-1:02d}"

    review = load_remote_json(
        f"{QLIB_CONTEXT_DIR}/macro/{prev_month}_review.json"
    )
    upcoming = load_remote_json(
        f"{QLIB_CONTEXT_DIR}/macro/{current_month}_upcoming.json"
    )

    return {
        "last_month_review": review,
        "next_month_upcoming": upcoming,
    }


def load_semi_earnings() -> dict | None:
    """Load semiconductor earnings calendar for 2025."""
    return load_remote_json(f"{QLIB_CONTEXT_DIR}/semi_earnings_2025.json")
```

Note: also add `import json` and `import subprocess` at the top of the file.

**Step 2: Commit**

```bash
git add infra/pmb/demos/overlay_helpers.py
git commit -m "feat: add SSH-based LLM context loading helpers"
```

---

### Task 3: Update `overlay_llm_agent.py` — dates + context integration

**Files:**
- Modify: `infra/pmb/demos/overlay_llm_agent.py`

**Step 1: Change backtest dates to 2025**

```python
# Line 45-46: change from
START_DATE = "2024-01-02"
END_DATE = "2024-12-31"
# to
START_DATE = "2025-01-02"
END_DATE = "2025-12-31"
```

**Step 2: Import context loading functions**

Add to the imports from `overlay_helpers`:

```python
from demos.overlay_helpers import (
    ...,  # existing imports
    load_macro_context, load_semi_earnings,
)
```

**Step 3: Pre-load semi earnings at startup**

In `run_llm_strategy()`, after the LLM config load and before Phase 1, add:

```python
    # Load context data
    semi_earnings = load_semi_earnings()
    if semi_earnings:
        print(f"  Loaded semiconductor earnings: {len(semi_earnings['earnings'])} records")
    else:
        print("  [WARN] Could not load semiconductor earnings context")
        semi_earnings = {"tickers": [], "earnings": []}
```

**Step 4: Load macro context per month + build context string**

In the trading loop, before the LLM call (after `if not is_rebalance_day...` block), add month-tracking and context building:

```python
    # Before the while loop, add:
    current_macro_month = ""
    macro_context = {}

    # Inside the loop, after the rebalance-day gate, before query_option_chain:
    # Load macro context when month changes
    month_str = current_date[:7]  # "2025-01"
    if month_str != current_macro_month:
        current_macro_month = month_str
        macro_context = load_macro_context(month_str)
        if macro_context.get("last_month_review"):
            n = len(macro_context["last_month_review"].get("events", []))
            print(f"  [CTX] Loaded macro context for {month_str}: {n} review events")
```

**Step 5: Update `build_user_prompt()` to accept and format context**

Add a `context` parameter to `build_user_prompt()` and append it:

```python
def build_user_prompt(strategy: str, underlying: str, date: str,
                      price: float, cash: float, equity: float,
                      active_options: list, chain: list[dict],
                      effective_delta: float | None = None,
                      context: str = "") -> str:
    # ... existing code ...

    # At the end, before the return, append context:
    context_section = ""
    if context:
        context_section = f"\n\nMarket Context:\n{context}"

    return f"""Current state:
...existing prompt...
Constraint: effective delta must stay <= {STOCK_QTY:,} shares.{context_section}"""
```

**Step 6: Build context string and pass to `build_user_prompt()`**

After loading macro context and before the LLM call:

```python
    # Build context string for LLM
    ctx_parts = []

    # Macro: last month review
    review = macro_context.get("last_month_review")
    if review and review.get("events"):
        ctx_parts.append(f"Last month ({review['month']}) key macro events:")
        for ev in review["events"]:
            line = f"  {ev['date']} {ev['event']}"
            if ev.get("actual"):
                line += f": actual={ev['actual']}"
                if ev.get("consensus"):
                    line += f" vs consensus={ev['consensus']}"
                if ev.get("previous"):
                    line += f" (prev={ev['previous']})"
            ctx_parts.append(line)

    # Macro: next month upcoming
    upcoming = macro_context.get("next_month_upcoming")
    if upcoming and upcoming.get("events"):
        ctx_parts.append(f"\nUpcoming macro events next month ({upcoming['month']}):")
        for ev in upcoming["events"]:
            ctx_parts.append(f"  {ev['date']} {ev['event']}")

    # Semiconductor earnings: show recent + upcoming relative to current_date
    if semi_earnings and semi_earnings.get("earnings"):
        # Past 14 days results + next 14 days upcoming
        recent = [e for e in semi_earnings["earnings"]
                  if e["date"] >= _date_offset(current_date, -14)
                  and e["date"] < current_date and e.get("actual_eps") is not None]
        upcoming_earn = [e for e in semi_earnings["earnings"]
                         if e["date"] >= current_date
                         and e["date"] <= _date_offset(current_date, 14)]

        if recent:
            ctx_parts.append("\nRecent semiconductor earnings (last 14 days):")
            for e in recent:
                surprise = ""
                if e.get("eps_surprise_percent") is not None:
                    surprise = f" surprise={e['eps_surprise_percent']:.1%}"
                ctx_parts.append(
                    f"  {e['date']} {e['ticker']} {e['fiscal_period']}/{e['fiscal_year']}: "
                    f"EPS actual={e['actual_eps']} est={e['estimated_eps']}{surprise}"
                )

        if upcoming_earn:
            ctx_parts.append("\nUpcoming semiconductor earnings (next 14 days):")
            for e in upcoming_earn:
                ctx_parts.append(
                    f"  {e['date']} {e['ticker']} {e['fiscal_period']}/{e['fiscal_year']}: "
                    f"est EPS={e['estimated_eps']}"
                )

    context_str = "\n".join(ctx_parts)
```

Add a helper for date arithmetic:

```python
def _date_offset(date_str: str, days: int) -> str:
    """Return date_str offset by N days."""
    from datetime import datetime, timedelta
    dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")
```

Then pass `context_str` to `build_user_prompt()`:

```python
    user_prompt = build_user_prompt(
        strategy, underlying, current_date,
        current_price, cash, equity,
        active_list, chain,
        effective_delta=eff_delta,
        context=context_str,
    )
```

**Step 7: Commit**

```bash
git add infra/pmb/demos/overlay_llm_agent.py
git commit -m "feat: integrate macro/earnings context into LLM agent, update to 2025"
```

---

### Task 4: Update other overlay demos to 2025 dates

**Files:**
- Modify: `infra/pmb/demos/overlay_profit_increase_v2.py`
- Modify: `infra/pmb/demos/overlay_hedging_v2.py`

**Step 1: Update dates in both files**

Change `START_DATE` and `END_DATE` from 2024 to 2025 in both files.

**Step 2: Commit**

```bash
git add infra/pmb/demos/overlay_profit_increase_v2.py infra/pmb/demos/overlay_hedging_v2.py
git commit -m "chore: update overlay demo dates to 2025"
```

---

### Task 5: Run the full pipeline end-to-end

**Step 1: Generate context on qlib**

```bash
scp infra/pmb/demos/generate_llm_context.py qlib:/tmp/generate_llm_context.py
ssh qlib "python3 /tmp/generate_llm_context.py"
```

**Step 2: Verify context files**

```bash
ssh qlib "ls /home/qlib/news/llm_context_2025/macro/ | wc -l"  # expect 23
ssh qlib "ls /home/qlib/news/llm_context_2025/semi_earnings_2025.json"
```

**Step 3: Run LLM agent backtest**

```bash
cd infra/pmb && python demos/overlay_llm_agent.py --ticker NVDA --strategy profit
```

Verify: LLM prompt now includes macro context + semiconductor earnings context.
