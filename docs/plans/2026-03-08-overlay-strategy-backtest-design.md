# Overlay Strategy Backtest Design

**Date:** 2026-03-08
**Status:** Approved

## Problem

PMB has a complete step-driven backtest engine with option lifecycle support, but no demo
scripts that implement the classic overlay strategies described in the QFinZero paper:
**Profit Increase** (covered call) and **Hedging** (protective put). We need working
backtest scripts to validate these strategies over a full year of daily data.

## Goals

Two standalone demo scripts under `infra/pmb/demos/`:

1. **`overlay_profit_increase.py`** — Covered Call strategy for income enhancement
2. **`overlay_hedging.py`** — Protective Put strategy for downside protection

Both scripts share the same backtest parameters and produce comparable results
against a buy-and-hold benchmark.

## Non-Goals

- Cash-secured put or put spread strategies (future extension)
- Multi-ticker support (future extension)
- Parameterized CLI interface (future extension)
- Minute-level frequency (daily only for now)
- Greeks-based strike selection (use simple % OTM rule)

## Backtest Parameters

| Parameter       | Value                        |
|-----------------|------------------------------|
| Underlying      | AAPL                         |
| Period          | 2024-01-02 to 2024-12-31     |
| Frequency       | Daily (1d)                   |
| Initial Capital | $100,000                     |
| Account Type    | MARGIN                       |
| Stock Position  | 100 shares (bought on day 1) |
| Slippage        | 2 bps                        |
| Stock Fee       | $0.005/share                 |
| Option Fee      | $0.65/contract               |

## Strategy 1: Covered Call (Profit Increase)

### Logic

```
Day 1:
  Buy 100 shares AAPL at market

Each trading day:
  If no active short call position:
    Query option chain via UPQ chain_query:
      underlying = AAPL
      type = C (call)
      expiry_min = today + 25 days
      expiry_max = today + 35 days
      strike_min = current_price * 1.03
      strike_max = current_price * 1.10
    Select contract closest to current_price * 1.05
    SELL 1 call contract (MARKET order, GTC)
    Add contract to session universe (so PMB prefetches bar data)

  If OPTION_EXPIRY_EVENT received:
    Log expiry outcome (worthless / assignment)
    If call-away occurred (ITM):
      Re-buy 100 shares AAPL at market (restore stock position)
    Next day: open new short call (handled by "no active position" check)

End of backtest:
  Close any remaining option position
  Report results
```

### Roll Mechanism: Natural Expiry (Plan A)

The script does NOT roll options before expiry. Instead:

1. Short call expires OTM → worthless, premium fully captured. Script opens new call next day.
2. Short call expires ITM → PMB assignment engine triggers call-away:
   - Option closed at intrinsic value
   - 100 shares sold at strike price (synthetic fill)
   - Script detects stock position is gone, re-buys 100 shares
   - Opens new short call next day

This approach is chosen because:
- PMB already has complete expiry/assignment logic (`domain/option_lifecycle.py`)
- Simpler script logic — no need to track days-to-expiry or manage early close
- Validates the full assignment flow end-to-end
- Matches the paper's intent of studying overlay payoff reshaping

### Contract Discovery

Uses UPQ `chain_query` endpoint (port 19703) to dynamically find contracts:

```python
GET /option/chain_query?underlying=AAPL&date=2024-03-15
    &expiry_min=2024-04-09&expiry_max=2024-04-19
    &strike_min=175&strike_max=185&type=C
```

Returns list of matching contracts with close price, strike, expiry, OPRA ticker.
Script selects the one with strike closest to `current_price * 1.05`.

### Adding Contracts to Session Universe

PMB prefetches all bar data at session creation. Since we don't know which option
contracts we'll trade upfront, we need one of:

**(a)** Create a new session each month with the discovered contract in the universe
**(b)** Add a mechanism to dynamically add instruments to an existing session

The current PMB does not support (b). We will use approach **(a)**:
- Run backtest in monthly segments
- Each segment creates a new session with the known option contract
- Carry forward account state (cash, positions) between segments
- Stitch equity curves together at the end

**Alternative if PMB adds dynamic universe:** Revisit in a future iteration.

## Strategy 2: Protective Put (Hedging)

### Logic

```
Day 1:
  Buy 100 shares AAPL at market

Each trading day:
  If no active long put position:
    Query option chain via UPQ chain_query:
      underlying = AAPL
      type = P (put)
      expiry_min = today + 25 days
      expiry_max = today + 35 days
      strike_min = current_price * 0.90
      strike_max = current_price * 0.97
    Select contract closest to current_price * 0.95
    BUY 1 put contract (MARKET order, GTC)
    Add contract to session universe

  If OPTION_EXPIRY_EVENT received:
    Log expiry outcome
    Long put ITM → closed at intrinsic value (cash received)
    Long put OTM → expired worthless (premium lost)
    Next day: buy new put (handled by "no active position" check)

End of backtest:
  Close any remaining option position
  Report results
```

### Roll Mechanism: Natural Expiry (Plan A)

Same as covered call — let puts expire naturally:

1. Long put expires OTM → worthless, protection cost realized
2. Long put expires ITM → PMB closes at intrinsic value, cash credited
3. Script opens new put next day in either case

## Shared Components

### Monthly Session Segmentation

Both scripts follow this pattern:

```python
for month in months_in_range(start_date, end_date):
    # 1. Discover option contract for this month
    contract = query_option_chain(...)

    # 2. Create PMB session for this month segment
    session = create_session(
        universe={"stocks": ["AAPL"], "options": [contract]},
        start_ts=month_start,
        end_ts=month_end,
    )

    # 3. Step through all trading days
    for each day:
        step(1)
        handle events (expiry, fills, snapshots)

    # 4. Collect equity curve segment + final state
    carry forward cash/positions to next month
```

### Benchmark Comparison

Both scripts compute a buy-and-hold benchmark alongside the overlay:
- Same initial $100k, same 100 shares bought on day 1
- No option activity — pure stock return
- Final report shows: overlay return vs. benchmark return, alpha from overlay

### Result Output

Reuse existing `ResultSaver` with additional overlay-specific data:

```
infra/pmb/results/overlay_profit_increase_YYYYMMDD_HHMMSS/
  summary.json          # Standard PMB summary + overlay metrics
  equity_curve.csv      # Daily equity with benchmark column
  trades.csv            # All stock + option trades
  options_log.csv       # Option-specific: contract, strike, premium, expiry outcome
  report.txt            # Human-readable summary
```

### Overlay-Specific Metrics

In addition to standard PMB metrics (return, drawdown, fees):

- **Total premium collected** (covered call) / **Total premium paid** (protective put)
- **Number of contracts traded**
- **Assignment count** (covered call ITM expiries)
- **Protection utilization** (protective put ITM expiries)
- **Overlay alpha** = overlay return - benchmark return
- **Max drawdown comparison** (overlay vs benchmark)

## File Structure

```
infra/pmb/demos/
  overlay_profit_increase.py    # Covered Call demo
  overlay_hedging.py            # Protective Put demo
  result_saver.py               # Existing, reused as-is
  run_all.py                    # Updated to include new demos
```

## Dependencies

- PMB server running on `:19701` (test-env standard port)
- UPQ server running on `:19703` (test-env standard port)
- Option lifecycle support (already on main since 2026-03-06)

## Phase 2: LLM-Driven Overlay Agent + Paper Alignment

Phase 2 brings the implementation in line with the paper's evaluation protocol and
replaces rule-based logic with LLM decision-making.

### 2a. Paper Parameter Alignment

The following parameters must be updated to match the paper specification:

| Parameter | Phase 1 (current) | Paper Spec | Change |
|-----------|-------------------|------------|--------|
| **Underlyings (Profit)** | AAPL only | QQQ, NVDA, USO | Add 3 tickers |
| **Underlyings (Hedge)** | AAPL only | QQQ, NVDA | Add 2 tickers |
| **Position size** | 100 shares | 10,000 shares | 100x increase |
| **Cash buffer** | All-in $100k | 20% of stock notional | Proportional |
| **Rebalance freq** | Monthly | **Weekly** | 4x more frequent |
| **DTE range (Profit)** | 25-35 days | **7-45 days** | Wider window |
| **DTE range (Hedge)** | 25-35 days | **7-60 days** | Wider window |
| **Strategies (Profit)** | Covered call only | Covered call **+ cash-secured put** | Add CSP |
| **Strategies (Hedge)** | Protective put only | Protective put **+ put spread** | Add spread |
| **Benchmark** | Buy-and-hold | **Institutional ETFs** (JEPQ, NVDY, USOY) | Add ETF data |
| **Delta constraint** | None | Total effective delta ≤ initial position | Add check |

### 2b. Cash-Secured Put Selling (Profit Increase addition)

The agent may sell OTM puts that are fully cash-secured:
- Cash required = strike × 100 × num_contracts
- If assigned (ITM expiry): buy stock at strike (adds to holdings)
- Premium collected regardless of outcome
- Must not exceed cash buffer

### 2c. Put Spread (Hedging addition)

Buy high-strike put + sell low-strike put:
- Net debit = premium_paid - premium_received
- Max protection = high_strike - low_strike
- Cheaper than naked put, but capped protection
- Both legs must have same expiry

### 2d. LLM Agent Integration

Replace hardcoded rules with LLM decision-making:

- **Model:** DeepSeek Chat (config from `eval/models.yaml:34-38`)
- **Pattern:** Each rebalance day (weekly), feed market state + holdings +
  available option chain to the LLM, receive a JSON action, execute via PMB
- **Agent decides:** when to enter/exit, which contracts (strike + maturity),
  which strategy to apply (covered call vs CSP for profit; put vs spread for hedge)
- **Three key metrics to track:**
  1. **Latency** — per-call and total wall time
  2. **Token consumption** — prompt/completion tokens, estimated cost
  3. **Equity curve** — LLM agent vs rule-based vs buy-and-hold vs institutional ETF

### 2e. Institutional ETF Benchmark

For Profit Increase, compare against systematic overlay ETFs:
- **JEPQ** — JPMorgan Nasdaq Equity Premium Income ETF (for QQQ)
- **NVDY** — YieldMax NVDA Option Income ETF (for NVDA)
- **USOY** — YieldMax USO Option Income ETF (for USO)

These ETFs apply option overlays institutionally, serving as practical baselines
to assess whether LLM-based agents can match or surpass structured implementations.

## Future Extensions

1. **Parameterized CLI** — `--ticker AAPL --start 2024-01-02 --end 2024-12-31 --otm-pct 0.05`
2. **Greeks-based selection** — Use delta targeting instead of % OTM
3. **Early roll logic** — Roll before expiry based on time decay / delta thresholds
4. **Multi-leg strategies** — Iron condors, collars, strangles
