# PMB Execution Engine Bugs

**Date:** 2026-03-03
**Status:** Open
**Affected component:** `infra/pmb/`

## Context

During end-to-end testing of the MCP agent tools, two bugs were found in the PMB
(Paper Money Broker) execution engine. Both are code-level issues, not agent tool
layer issues.

---

## Bug 1: mark_price not updated to market close on fill day

**Severity:** High — causes incorrect equity, unrealized P&L, return, and drawdown
in every session where orders fill.

### Symptoms

On the step where a MARKET BUY order fills:

| Field | Expected | Actual |
|-------|----------|--------|
| mark_price | $188.12 (bar close) | $188.1319 (fill price) |
| unrealized_pnl | -$1.19 | $0.00 |
| equity | ~$99,998.81 | $99,999.95 |

### Root cause

In `session_service.py:_process_tick()`, the step executes in this order:

```
Step 2 (line 231): update_market_prices(prices)   -- updates existing positions
Step 3 (line 235): execution_engine.process_step() -- fills orders, creates new positions
Step 4 (line 273): account snapshot                -- reads stale mark_price
```

When a new position is created in Step 3 via `ledger.apply_fill()`, it sets
`mark_price = fill_price` (ledger.py:80). Since `update_market_prices` already ran
in Step 2 (before the position existed), the new position never gets marked to the
bar's close price on the fill day.

For **existing** positions being added to, the issue is different: `apply_fill`
does not touch `mark_price` when adding to a long (ledger.py:82-87), so Step 2's
update survives. But for new positions and short covers that flip to long
(ledger.py:95-96), `mark_price` is stale.

### Impact

- Account snapshot on fill day shows wrong equity
- Equity curve point for fill day is wrong
- Summary metrics (total_return, max_drawdown) are calculated from equity curve
  and therefore also wrong
- If the session is stopped immediately after the fill step (as in the test case),
  the entire summary is meaningless

### Reproduction

```
1. Create account, create daily session with NVDA
2. Step once (see NVDA close = $188.85)
3. Place MARKET BUY 100 NVDA
4. Step once (fill at ~$188.13, bar close = $188.12)
5. Observe: mark_price = $188.13, unrealized_pnl = $0.00
   Expected: mark_price = $188.12, unrealized_pnl = -$1.19
```

---

## Bug 2: MARKET order fills at close price (look-ahead bias)

**Severity:** Medium — design issue that undermines backtest validity.

### Symptoms

A MARKET order placed after seeing the 1/2 bar fills at **1/5's close price**
($188.12 + slippage = $188.1319), not at 1/5's open price ($191.76).

### Root cause

`execution_engine.py:204-205`:

```python
if order.order_type == OrderType.MARKET:
    return self._apply_slippage(bar.close, is_buy)
```

### Why this is a problem

The agent workflow is: step → see bar → place order → step → order fills.

In daily frequency, orders placed after seeing day N's close should fill at
day N+1's **open** price (the first available price when the market opens).
Using close price means the fill happens at a price the agent could not have
known at order time — this is **look-ahead bias**.

The demo `daily_buy_close.py` is literally named "buy at close" and relies on
this behavior, but even a "buy at close" strategy in reality would fill at the
close price of the day the order was *placed*, not the next day's close.

### Note on STOP and LIMIT orders

- STOP orders correctly use `bar.open` as the reference: `max(stop_price, bar.open)`
  (line 216). This is consistent — stop triggers are evaluated intrabar, and the
  fill anchors to open.
- LIMIT orders use `bar.close` as fill: `min(limit_price, bar.close)` (line 209).
  This has a similar look-ahead concern but is less severe since the limit price
  constrains the fill.

---

## Fix Plan

### Bug 1 fix: Re-run mark-to-market after execution

Add a second `update_market_prices` call after Step 3 in `_process_tick()`:

```python
# 2. Update market prices in ledger
prices = state.cache.get_prices_at(ts_ns)
state.ledger.update_market_prices(prices)

# 3. Execution: process open orders
exec_events, trades = state.execution_engine.process_step(...)

# 3b. Re-mark positions created/modified by fills
state.ledger.update_market_prices(prices)
```

**Why this is safe:**
- `update_market_prices` is idempotent — calling it twice with the same prices
  is harmless for positions that already have the correct mark
- New positions (from fills) get their mark_price corrected to bar close
- Existing positions are unaffected (already marked correctly from Step 2)
- No other code depends on mark_price being equal to fill_price

### Bug 2 fix: MARKET orders fill at open price

Change `_calculate_fill_price` to use `bar.open` for MARKET orders:

```python
if order.order_type == OrderType.MARKET:
    return self._apply_slippage(bar.open, is_buy)
```

**Why this is safe:**
- Matches real-world semantics: market orders fill at the first available price
- Consistent with STOP order behavior which already uses `bar.open`
- The `daily_buy_close.py` demo will still work — the strategy name refers to the
  timing of the decision (observe close, then buy), not the fill price. Fills at
  next day's open is actually more realistic.
- Slippage model (`_apply_slippage`) works the same way regardless of base price

**What changes in behavior:**
- Fill prices will shift from close to open of the execution bar
- Backtest results will differ (typically slightly worse, since open price after
  a buy signal tends to be higher due to overnight gaps)
- This is a **correctness improvement**, not a regression
