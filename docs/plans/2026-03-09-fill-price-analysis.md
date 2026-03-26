# Fill Price & Look-Ahead Bias Analysis

**Date:** 2026-03-09
**Branch:** `feat/overlay-strategy-backtest`
**Context:** PMB MARKET order fill price validation for overlay strategy backtests

---

## Problem Statement

PMB's `ExecutionEngine` fills MARKET orders at `bar.open` of the current tick's bar. When running at daily frequency (`1d`), the overlay demo scripts:

1. Receive a `MARKET_TICK` event containing the day's OHLCV data (including `close`)
2. Make trading decisions based on that tick's data
3. Place MARKET orders that fill at `bar.open` of the **same bar**

This creates a timing paradox: the strategy sees today's close price (future information at the time of order placement) but fills at today's open price (already in the past). Neither price reflects a realistic execution time.

**Question:** Can we use minute-level data with the **3:50 PM bar's `window_start` open price** as the fill price to eliminate this bias?

---

## Empirical Analysis: Open-Close Gaps

### Daily: Overnight Gap (today open vs yesterday close)

Measured across 251 trading days in 2024:

| Ticker | Mean |gap| | Median | P95 | Max | >=1% days |
|--------|-----------|--------|------|--------|-----------|
| SPY | 35 bps | 27 bps | 1.07% | 3.99% | 6% |
| QQQ | 50 bps | 36 bps | 1.45% | 5.36% | 10% |
| AAPL | 60 bps | 37 bps | 1.90% | 9.45% | 15% |
| NVDA | **137 bps** | 108 bps | 3.38% | **14.18%** | **55%** |

**Implication:** Using next-day open as fill price introduces 35-137 bps of gap noise — far exceeding the 2 bps slippage assumption.

### Minute: Adjacent Bar Gap (bar open vs prev bar close)

Sampled from first trading week of each month in 2024 (~30K bar transitions per ticker):

| Ticker | Mean |gap| | Median | P99 | >=25bps |
|--------|-----------|--------|------|---------|
| SPY | 0.57 bps | 0.20 bps | 4.2 bps | 0.1% |
| QQQ | 0.80 bps | 0.42 bps | 5.0 bps | 0.1% |
| AAPL | 1.31 bps | 0.45 bps | 11.1 bps | 0.2% |
| NVDA | 1.50 bps | 0.81 bps | 9.2 bps | 0.2% |

**Implication:** Minute-level bar transitions have sub-bps median gaps. Using next minute bar's open as fill price introduces negligible bias.

---

## Option Minute Data Coverage at 3:50 PM ET

Tested with actual 5% OTM contracts matching overlay demo parameters:

### High Liquidity: NVDA Options (premium > $1)

| Contract | bars/day | 3:50 PM coverage |
|----------|----------|------------------|
| O:NVDA240712C00131000 ($1.42) | 304 | 80% |
| O:NVDA240913C00113000 ($2.32) | 346 | 100% |
| O:NVDA241213C00146000 ($1.10) | 335 | 100% |
| O:NVDA240913P00103000 ($2.30) | 325 | 100% |

### Low Liquidity: QQQ 5% OTM Options (premium < $0.25)

| Contract | bars/day | 3:50 PM coverage |
|----------|----------|------------------|
| O:QQQ240311C00466000 ($0.06) | **4** | **0%** |
| O:QQQ240611C00476000 ($0.05) | **8** | **17%** |
| O:QQQ240910C00485000 ($0.23) | **12** | **0%** |
| O:QQQ241210C00540000 ($0.06) | **9** | **0%** |
| O:QQQ240610P00430000 ($0.13) | **9** | **0%** |

**Root cause:** QQQ 5% OTM weekly options have very low premiums ($0.05-0.23) and trade only 4-12 times per day. Most trades cluster around market open and close, leaving 3:50 PM with no data.

---

## Trade-off Analysis

### Approach A: Pure Minute (3:50 PM bar open as fill)

- **Stocks:** Excellent — sub-bps gap, 100% coverage
- **NVDA options:** Good — high liquidity, 80-100% coverage
- **QQQ OTM options:** **Broken** — 0-17% coverage, cannot fill most days
- **Verdict:** Only works for high-liquidity options. Unusable for QQQ OTM contracts.

### Approach B: Daily Close with Enhanced Slippage

- Keep daily `close` as fill price (it's the EOD settlement price, conceptually correct for a "trade at close" strategy)
- Model bid-ask spread cost via an `option_spread_bps` parameter in `ExecutionConfig`
- OTM options typically have 50-100% bid-ask spread relative to premium
- **Verdict:** Simple, robust, works for all contracts. Doesn't solve the look-ahead bias but acknowledges that overlay strategies are fundamentally "decide-and-trade-at-close" strategies.

### Approach C: Mixed Frequency (Recommended)

Use daily frequency for decision-making but improve fill price realism:

1. **Stock orders:** Fill at daily `close` (settlement price, appropriate for EOD strategies)
2. **Option orders:** Fill at daily `close` + apply realistic spread cost
3. **Future enhancement:** For strategies that need intraday execution, support minute-frequency sessions with the 3:50 PM execution window — but only for liquid contracts (e.g., NVDA, ATM/near-ATM options)

---

## Decision

**Proceed with Approach C (mixed frequency):**

1. **Phase 1 (immediate):** Add `option_spread_bps` to `ExecutionConfig` for bid-ask spread modeling on option fills. This is the biggest missing cost — a $0.05 premium option with $0.03-$0.05 spread means 30-50 bps effective slippage per contract trade.

2. **Phase 2 (next):** Support minute-frequency overlay backtests where option liquidity allows. The infrastructure already supports `frequency: "1m"` — the session service switches between `get_stock_daily_bars` and `get_stock_minute_bars` based on the frequency param. The main work is updating the overlay demo scripts to operate at minute granularity and handle the 3:50 PM execution window.

3. **Guard rail:** For minute-frequency backtests, if an option contract has no bar at the target execution time, fall back to the most recent available bar's close (with a configurable staleness threshold, e.g., 10 minutes max).

---

## Reference Data

Analysis scripts: `scripts/analyze_gaps.py`
Data period: 2024-01-02 to 2024-12-31
UPQ storage: `/home/qlib/upq_storage/` (stock_daily, stock_minute, option_day, option_minute)
