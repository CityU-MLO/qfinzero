# Daily Fill Price Look-Ahead Bias Fix

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate look-ahead bias in daily-frequency MARKET order fills by replacing `bar.open` with 3:50 PM ET minute bar open price.

**Architecture:** Patch daily bar `open` fields at data prefetch time (in `SessionService.create_session`), so the existing `ExecutionEngine` fills at the realistic price without any engine changes. Fallback chain: 15:50 bar → nearest bar in 15:40-15:49 window → daily bar close.

**Tech Stack:** Python (PMB service), UPQ async HTTP client, pytest

---

## Background

PMB MARKET orders fill at `bar.open`. For daily sessions, `bar.open` is the day's opening price — but the strategy sees the day's close in the same tick event. This creates look-ahead bias: the strategy uses future information (close) to make decisions, then fills at a price (open) that was already in the past.

**Fix:** For daily sessions, replace each daily bar's `open` with the 3:50 PM ET minute bar's open price. This represents a realistic "near close" execution price — the strategy decides based on EOD data and fills at a price available 10 minutes before close.

**Fallback chain** (when 3:50 PM bar is missing):
1. Nearest minute bar in 15:40-15:49 ET window (prefer latest)
2. Daily bar's `close` (EOD settlement price)

**Scope:** Only affects daily-frequency sessions. Minute-frequency sessions already use `window_start` open price (no bias).

---

### Task 1: Add `_patch_daily_open_with_minute_price` method to SessionService

**Files:**
- Modify: `infra/pmb/services/session_service.py:440` (add new method at end of class)
- Test: `infra/pmb/tests/test_daily_fill_patch.py` (create)

**Step 1: Write the failing test**

Create `infra/pmb/tests/test_daily_fill_patch.py`:

```python
"""Tests for daily bar open patching with minute bar prices."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from models.market import StockBar, OptionBar
from domain.market_data_cache import MarketDataCache
from domain.session_clock import iso_to_ns
from services.session_service import SessionService


def _make_service():
    """Create a SessionService with a mock UPQ client."""
    upq = AsyncMock()
    return SessionService(upq)


def _ns(time_str: str) -> int:
    """Convert 'YYYY-MM-DDTHH:MM:SS' to nanoseconds (UTC)."""
    return iso_to_ns(time_str + "+00:00")


# --- Stock patching ---

@pytest.mark.asyncio
async def test_stock_open_patched_with_1550_bar():
    """Daily stock bar.open should be replaced with 15:50 ET minute bar open."""
    svc = _make_service()
    cache = MarketDataCache()

    # Daily bar: open=100, close=105
    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=daily_ns,
                 open=100.0, high=110.0, low=95.0, close=105.0, volume=1000),
    ])

    # 15:50 ET = 20:50 UTC minute bar: open=104.50
    minute_bars = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:50:00"),
                 open=104.50, high=105.0, low=104.0, close=104.80, volume=500),
    ]
    svc._upq.get_stock_minute_bars.return_value = minute_bars

    # Build a minimal request-like object
    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._stock_bars["AAPL"][daily_ns]
    assert patched_bar.open == 104.50  # patched from minute bar
    assert patched_bar.close == 105.0  # unchanged
    assert patched_bar.high == 110.0   # unchanged


@pytest.mark.asyncio
async def test_stock_fallback_to_earlier_minute_bar():
    """When 15:50 is missing, use nearest bar in 15:40-15:49 window."""
    svc = _make_service()
    cache = MarketDataCache()

    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=daily_ns,
                 open=100.0, high=110.0, low=95.0, close=105.0, volume=1000),
    ])

    # Only a 15:45 ET = 20:45 UTC bar available (no 15:50)
    minute_bars = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:45:00"),
                 open=104.20, high=104.50, low=104.00, close=104.30, volume=300),
    ]
    svc._upq.get_stock_minute_bars.return_value = minute_bars

    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._stock_bars["AAPL"][daily_ns]
    assert patched_bar.open == 104.20


@pytest.mark.asyncio
async def test_stock_fallback_to_daily_close():
    """When no minute bar in 15:40-15:50 window, fall back to daily close."""
    svc = _make_service()
    cache = MarketDataCache()

    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=daily_ns,
                 open=100.0, high=110.0, low=95.0, close=105.0, volume=1000),
    ])

    # No minute bars in the 15:40-15:50 window
    svc._upq.get_stock_minute_bars.return_value = []

    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._stock_bars["AAPL"][daily_ns]
    assert patched_bar.open == 105.0  # fell back to daily close


@pytest.mark.asyncio
async def test_stock_prefers_latest_minute_bar():
    """When multiple bars in 15:40-15:50, prefer the latest (closest to 15:50)."""
    svc = _make_service()
    cache = MarketDataCache()

    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=daily_ns,
                 open=100.0, high=110.0, low=95.0, close=105.0, volume=1000),
    ])

    # Bars at 15:42 and 15:48 — should pick 15:48 (latest)
    minute_bars = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:42:00"),
                 open=103.00, high=103.50, low=102.50, close=103.20, volume=200),
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:48:00"),
                 open=104.10, high=104.50, low=103.80, close=104.30, volume=400),
    ]
    svc._upq.get_stock_minute_bars.return_value = minute_bars

    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._stock_bars["AAPL"][daily_ns]
    assert patched_bar.open == 104.10  # from 15:48 bar (latest)


# --- Option patching ---

@pytest.mark.asyncio
async def test_option_open_patched_with_1550_bar():
    """Daily option bar.open should be replaced with 15:50 ET minute bar open."""
    svc = _make_service()
    cache = MarketDataCache()

    contract = "O:AAPL240119C00150000"
    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_option_bars(contract, [
        OptionBar(contract=contract, window_start_ns=daily_ns,
                  open=3.00, high=3.50, low=2.50, close=3.20, volume=100),
    ])

    minute_bars = [
        OptionBar(contract=contract, window_start_ns=_ns("2024-01-02T20:50:00"),
                  open=3.15, high=3.20, low=3.10, close=3.18, volume=50),
    ]
    svc._upq.get_option_minute_bars.return_value = minute_bars

    req = MagicMock()
    req.universe.stocks = []
    req.universe.options = [contract]
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._option_bars[contract][daily_ns]
    assert patched_bar.open == 3.15
    assert patched_bar.close == 3.20  # unchanged


@pytest.mark.asyncio
async def test_option_fallback_to_daily_close():
    """Illiquid option with no minute bars falls back to daily close."""
    svc = _make_service()
    cache = MarketDataCache()

    contract = "O:QQQ240311C00466000"
    daily_ns = _ns("2024-01-02T00:00:00")
    cache.load_option_bars(contract, [
        OptionBar(contract=contract, window_start_ns=daily_ns,
                  open=0.06, high=0.08, low=0.04, close=0.05, volume=10),
    ])

    svc._upq.get_option_minute_bars.return_value = []

    req = MagicMock()
    req.universe.stocks = []
    req.universe.options = [contract]
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-02T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._option_bars[contract][daily_ns]
    assert patched_bar.open == 0.05  # fell back to daily close


# --- Multi-day patching ---

@pytest.mark.asyncio
async def test_multi_day_each_day_patched_independently():
    """Each daily bar gets its own day's 15:50 minute bar."""
    svc = _make_service()
    cache = MarketDataCache()

    ns_day1 = _ns("2024-01-02T00:00:00")
    ns_day2 = _ns("2024-01-03T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=ns_day1,
                 open=100.0, high=105.0, low=98.0, close=103.0, volume=1000),
        StockBar(symbol="AAPL", window_start_ns=ns_day2,
                 open=103.0, high=108.0, low=101.0, close=106.0, volume=1200),
    ])

    # Return minute bars for both days
    minute_bars = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:50:00"),
                 open=102.50, high=103.0, low=102.0, close=102.80, volume=500),
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-03T20:50:00"),
                 open=105.80, high=106.0, low=105.5, close=105.90, volume=600),
    ]
    svc._upq.get_stock_minute_bars.return_value = minute_bars

    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-01-02T00:00:00+00:00"
    req.end_ts = "2024-01-03T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    assert cache._stock_bars["AAPL"][ns_day1].open == 102.50
    assert cache._stock_bars["AAPL"][ns_day2].open == 105.80
```

**Step 2: Run test to verify it fails**

Run: `/Users/efan404/Codes/research/qfinzero/.venv/bin/pytest infra/pmb/tests/test_daily_fill_patch.py -v`
Expected: FAIL — `SessionService` has no method `_patch_daily_open_with_minute_price`

**Step 3: Implement `_patch_daily_open_with_minute_price`**

Add to `infra/pmb/services/session_service.py` at the end of the `SessionService` class (after `_clock_state`):

```python
async def _patch_daily_open_with_minute_price(
    self, req: "CreateSessionRequest", cache: MarketDataCache
) -> None:
    """Replace daily bar.open with 15:50 ET minute bar open to eliminate look-ahead bias.

    For each daily bar, fetch minute bars in the 15:40-15:50 ET window for that day.
    Fallback chain: 15:50 bar → latest bar in 15:40-15:49 → daily bar close.
    """
    from datetime import datetime, timedelta, timezone

    ET = timezone(timedelta(hours=-5))  # Eastern Time (simplified, ignores DST)

    # --- Patch stock bars ---
    for symbol, daily_bars_by_ns in cache._stock_bars.items():
        # Collect all trading dates from daily bars
        dates = set()
        for ns in daily_bars_by_ns:
            dt_utc = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
            dates.add(dt_utc.strftime("%Y-%m-%d"))

        if not dates:
            continue

        # Fetch minute bars for the full date range
        min_date = min(dates)
        max_date = max(dates)
        # Query 15:40-15:51 ET window = 20:40-20:51 UTC (for EST; will need DST handling)
        start_ts = f"{min_date}T20:40:00+00:00"
        end_ts = f"{max_date}T20:51:00+00:00"

        try:
            minute_bars = await self._upq.get_stock_minute_bars(
                [symbol], start_ts, end_ts
            )
        except Exception:
            continue  # UPQ unavailable — skip patching

        # Group minute bars by date
        minute_by_date: dict[str, list] = {}
        for mb in minute_bars:
            dt_utc = datetime.fromtimestamp(mb.window_start_ns / 1e9, tz=timezone.utc)
            date_key = dt_utc.strftime("%Y-%m-%d")
            minute_by_date.setdefault(date_key, []).append(mb)

        # Patch each daily bar
        for ns, daily_bar in daily_bars_by_ns.items():
            dt_utc = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
            date_key = dt_utc.strftime("%Y-%m-%d")

            bars_for_day = minute_by_date.get(date_key, [])
            patch_price = self._pick_near_close_price(bars_for_day, date_key)

            if patch_price is not None:
                daily_bar.open = patch_price
            else:
                daily_bar.open = daily_bar.close  # fallback to daily close

    # --- Patch option bars ---
    for contract, daily_bars_by_ns in cache._option_bars.items():
        dates = set()
        for ns in daily_bars_by_ns:
            dt_utc = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
            dates.add(dt_utc.strftime("%Y-%m-%d"))

        if not dates:
            continue

        min_date = min(dates)
        max_date = max(dates)
        start_ts = f"{min_date}T20:40:00+00:00"
        end_ts = f"{max_date}T20:51:00+00:00"

        try:
            minute_bars = await self._upq.get_option_minute_bars(
                contract, start_ts, end_ts
            )
        except Exception:
            continue

        minute_by_date: dict[str, list] = {}
        for mb in minute_bars:
            dt_utc = datetime.fromtimestamp(mb.window_start_ns / 1e9, tz=timezone.utc)
            date_key = dt_utc.strftime("%Y-%m-%d")
            minute_by_date.setdefault(date_key, []).append(mb)

        for ns, daily_bar in daily_bars_by_ns.items():
            dt_utc = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
            date_key = dt_utc.strftime("%Y-%m-%d")

            bars_for_day = minute_by_date.get(date_key, [])
            patch_price = self._pick_near_close_price(bars_for_day, date_key)

            if patch_price is not None:
                daily_bar.open = patch_price
            else:
                daily_bar.open = daily_bar.close

def _pick_near_close_price(
    self, minute_bars: list, date_key: str
) -> float | None:
    """Pick the best minute bar open price from the 15:40-15:50 ET window.

    Priority: 15:50 bar → latest bar in 15:40-15:49 window.
    Returns None if no bars in the window.
    """
    if not minute_bars:
        return None

    from datetime import datetime, timezone, timedelta

    # 15:50 ET = 20:50 UTC (EST) or 19:50 UTC (EDT)
    # We match by looking for bars with ET hour=15, minute=50
    ET = timezone(timedelta(hours=-5))

    target_bar = None
    best_fallback = None
    best_fallback_ns = -1

    for bar in minute_bars:
        dt_utc = datetime.fromtimestamp(bar.window_start_ns / 1e9, tz=timezone.utc)
        dt_et = dt_utc.astimezone(ET)

        if dt_et.hour == 15 and dt_et.minute == 50:
            target_bar = bar
            break  # exact match — use it

        if dt_et.hour == 15 and 40 <= dt_et.minute <= 49:
            if bar.window_start_ns > best_fallback_ns:
                best_fallback = bar
                best_fallback_ns = bar.window_start_ns

    if target_bar is not None:
        return target_bar.open
    if best_fallback is not None:
        return best_fallback.open
    return None
```

**Step 4: Run test to verify it passes**

Run: `/Users/efan404/Codes/research/qfinzero/.venv/bin/pytest infra/pmb/tests/test_daily_fill_patch.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add infra/pmb/services/session_service.py infra/pmb/tests/test_daily_fill_patch.py
git commit -m "feat(pmb): patch daily bar.open with 15:50 ET minute price to fix look-ahead bias"
```

---

### Task 2: Wire the patch into `create_session` and ensure import

**Files:**
- Modify: `infra/pmb/services/session_service.py:1-5` (import) and `:107-108` (call site)

**Note:** The uncommitted diff already has these changes (the `from datetime import ...` and the `if req.frequency == Frequency.DAY:` call). After Task 1 adds the method body, these become valid. Verify the existing diff is correct and keep it.

**Step 1: Verify the call site is already correct**

The existing uncommitted change at line 107-108 already calls `await self._patch_daily_open_with_minute_price(req, cache)` inside `create_session` after option data loading and before building the `SessionClock`. This is the correct location — it patches `bar.open` before timestamps are extracted, so the clock and engine see the patched prices.

The `from datetime import datetime, timedelta, timezone` import at line 3 is already present in the diff. This import is used inside `_patch_daily_open_with_minute_price`.

**Step 2: Write integration test**

Add to `infra/pmb/tests/test_daily_fill_patch.py`:

```python
@pytest.mark.asyncio
async def test_create_session_calls_patch_for_daily():
    """Verify create_session invokes patching for daily frequency."""
    from unittest.mock import patch as mock_patch
    from models.session import CreateSessionRequest, Universe
    from models.account import Account, MarginConfig
    from models.enums import Frequency

    upq = AsyncMock()
    upq.get_stock_daily_bars.return_value = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T00:00:00"),
                 open=100.0, high=105.0, low=98.0, close=103.0, volume=1000),
    ]
    upq.get_stock_minute_bars.return_value = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-01-02T20:50:00"),
                 open=102.50, high=103.0, low=102.0, close=102.80, volume=500),
    ]

    svc = SessionService(upq)
    req = CreateSessionRequest(
        account_id="test",
        frequency=Frequency.DAY,
        start_ts="2024-01-02T00:00:00+00:00",
        end_ts="2024-01-02T23:59:59+00:00",
        universe=Universe(stocks=["AAPL"]),
    )
    account = Account(account_id="test", initial_cash=100000.0, margin_config=MarginConfig())

    session_id, clock = await svc.create_session(req, account)

    # Verify the patch was applied
    state = svc.get_session(session_id)
    daily_ns = _ns("2024-01-02T00:00:00")
    assert state.cache._stock_bars["AAPL"][daily_ns].open == 102.50
```

**Step 3: Run test**

Run: `/Users/efan404/Codes/research/qfinzero/.venv/bin/pytest infra/pmb/tests/test_daily_fill_patch.py -v`
Expected: All 8 tests PASS

**Step 4: Commit**

```bash
git add infra/pmb/services/session_service.py infra/pmb/tests/test_daily_fill_patch.py
git commit -m "feat(pmb): wire daily fill price patching into create_session"
```

---

### Task 3: Handle DST (Eastern Time switches between EST and EDT)

**Files:**
- Modify: `infra/pmb/services/session_service.py` (update `_pick_near_close_price` and time window computation)
- Test: `infra/pmb/tests/test_daily_fill_patch.py` (add DST-aware tests)

**Context:** US Eastern Time is UTC-5 (EST, Nov-Mar) or UTC-4 (EDT, Mar-Nov). The 15:50 ET minute bar timestamp changes:
- EST: 15:50 ET = 20:50 UTC
- EDT: 15:50 ET = 19:50 UTC

Using a fixed `-5` offset is wrong for ~7 months of the year. The `zoneinfo` module (Python 3.9+) handles this correctly.

**Step 1: Write DST test**

```python
@pytest.mark.asyncio
async def test_stock_patched_during_edt_summer():
    """During EDT (summer), 15:50 ET = 19:50 UTC, not 20:50."""
    svc = _make_service()
    cache = MarketDataCache()

    # July 15 is during EDT (UTC-4)
    daily_ns = _ns("2024-07-15T00:00:00")
    cache.load_stock_bars("AAPL", [
        StockBar(symbol="AAPL", window_start_ns=daily_ns,
                 open=200.0, high=210.0, low=195.0, close=205.0, volume=1000),
    ])

    # 15:50 EDT = 19:50 UTC
    minute_bars = [
        StockBar(symbol="AAPL", window_start_ns=_ns("2024-07-15T19:50:00"),
                 open=204.50, high=205.0, low=204.0, close=204.80, volume=500),
    ]
    svc._upq.get_stock_minute_bars.return_value = minute_bars

    req = MagicMock()
    req.universe.stocks = ["AAPL"]
    req.universe.options = []
    req.start_ts = "2024-07-15T00:00:00+00:00"
    req.end_ts = "2024-07-15T23:59:59+00:00"

    await svc._patch_daily_open_with_minute_price(req, cache)

    patched_bar = cache._stock_bars["AAPL"][daily_ns]
    assert patched_bar.open == 204.50
```

**Step 2: Update implementation to use `zoneinfo`**

Replace fixed `timezone(timedelta(hours=-5))` with `ZoneInfo("America/New_York")`:

```python
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
```

This ensures:
- EST (Nov-Mar): 15:50 ET = 20:50 UTC
- EDT (Mar-Nov): 15:50 ET = 19:50 UTC

Also update the UPQ query time window to cover both EST and EDT possibilities:
- Query `20:40-20:51 UTC` in winter, `19:40-19:51 UTC` in summer
- Simplest: query `19:40-20:51 UTC` to cover both (at most 12 extra minutes of data)

**Step 3: Run tests**

Run: `/Users/efan404/Codes/research/qfinzero/.venv/bin/pytest infra/pmb/tests/test_daily_fill_patch.py -v`
Expected: All tests PASS including the DST test

**Step 4: Commit**

```bash
git add infra/pmb/services/session_service.py infra/pmb/tests/test_daily_fill_patch.py
git commit -m "fix(pmb): use zoneinfo for DST-correct ET time in daily fill patching"
```

---

### Task 4: Commit the related uncommitted changes

**Files:**
- `infra/pmb/clients/upq_client.py` (Greeks support in option minute/daily bars)
- `infra/pmb/models/market.py` (Greek fields on OptionBar)
- `infra/upq/crates/upq-service/src/app.rs` (code review fixes: `ensure_fields_for_indicators`)
- `infra/upq/crates/upq-service/src/indicators.rs` (doc comment on `group_by_ticker`)

**Step 1: Verify these changes are independent and correct**

These are from prior work (Greeks support + code review feedback) and should be committed separately.

**Step 2: Commit UPQ code review fixes**

```bash
git add infra/upq/crates/upq-service/src/app.rs infra/upq/crates/upq-service/src/indicators.rs
git commit -m "fix(upq): exact field matching in ensure_fields_for_indicators + add doc comment"
```

**Step 3: Commit PMB Greeks support**

```bash
git add infra/pmb/clients/upq_client.py infra/pmb/models/market.py
git commit -m "feat(pmb): add Greeks fields to OptionBar and UPQ client"
```

---

### Task 5: Run full test suite

**Step 1: Run all PMB tests**

```bash
cd /Users/efan404/Codes/research/qfinzero && .venv/bin/pytest infra/pmb/tests/ -v
```

Expected: All tests pass, including existing tests + new `test_daily_fill_patch.py`.

**Step 2: Run UPQ tests**

```bash
cd /Users/efan404/Codes/research/qfinzero/infra/upq && cargo test --workspace
```

Expected: All Rust tests pass.

---

## Notes

- **No ExecutionEngine changes needed.** The patch happens at data layer — `bar.open` is mutated in `MarketDataCache` before any stepping occurs. The engine's `_calculate_fill_price` already uses `bar.open` for MARKET orders.
- **OptionBar.open mutability:** Pydantic `BaseModel` fields are mutable by default. Direct assignment `bar.open = new_value` works.
- **Minute data query efficiency:** For multi-ticker stock universes, minute bars are fetched once per ticker (not per day), covering the entire date range. The 15:40-15:51 UTC window is narrow, so the response should be small.
- **Option minute bars:** Fetched per contract (UPQ API is contract-based). Low-liquidity contracts will return empty arrays, triggering the daily-close fallback.
