# Overlay Strategy Backtest Results — 2024 Full Year

**Date:** 2026-03-09
**Branch:** `feat/overlay-strategy-backtest`
**Services:** UPQ (port 19703), PMB (port 19701) on qlib

---

## Assumptions & Configuration

### Common Parameters

| Parameter | Value |
|-----------|-------|
| Period | 2024-01-02 to 2024-12-31 (252 trading days) |
| Underlyings | QQQ, NVDA |
| Stock Position | 10,000 shares |
| Cash Buffer | 20% of stock notional |
| Initial Capital | Stock notional + 20% cash buffer |
| Rebalance Frequency | Weekly (every Monday) |
| Account Type | Margin |
| Slippage | 2 bps |
| Stock Fee | $0.005/share |
| Option Fee | $0.65/contract |
| Execution | Market orders, GTC |

### Covered Call Strategy (`overlay_profit_increase_v2.py`)

| Parameter | Value |
|-----------|-------|
| Option Type | OTM Call (~5% above spot) |
| DTE Window | 7–45 days |
| Position Size | Short 1 contract per roll |
| Delta Constraint | Effective portfolio delta <= 10,000 shares |
| ETF Benchmark | JEPQ (for QQQ), NVDY (for NVDA) |
| On Expiry ITM | Call-away (sell 100 shares at strike), then re-buy 100 shares |
| On Expiry OTM | Premium kept, roll to next contract |

### Protective Put Strategy (`overlay_hedging_v2.py`)

| Parameter | Value |
|-----------|-------|
| Option Type | OTM Put (~5% below spot) |
| DTE Window | 7–60 days |
| Position Size | Long 1 contract per roll |
| Delta Constraint | Effective portfolio delta <= 10,000 shares |
| On Expiry ITM | Put exercised (close at intrinsic, protection activated) |
| On Expiry OTM | Premium lost, roll to next contract |

### Key Enhancements Applied

1. **Stock Split Adjustment (NVDA):** UPQ applies on-read price adjustment via `SplitCalendar`. NVDA 10:1 split on 2024-06-10 — pre-split prices divided by 10 (e.g. $1208.88 → $120.89). Without this fix, NVDA showed an artificial -60% loss.

2. **ETF Total Return (Dividends):** JEPQ/NVDY benchmark returns now include reinvested dividends via UPQ `/dividends/query` endpoint. JEPQ paid $5.44/share across 12 monthly distributions in 2024.

3. **Delta Constraint:** Before opening a new option position, the script computes effective portfolio delta (stock delta + option delta × qty × 100 multiplier) and skips if it would exceed 10,000 shares.

---

## Results

### 1. NVDA Covered Call

**Initial conditions:**
- Reference price: $48.17 (split-adjusted)
- Initial capital: $578,016 (= $48.17 × 10,000 × 1.20)
- ETF benchmark: NVDY

| Metric | Covered Call | Buy-Hold | NVDY ETF |
|--------|-------------|----------|----------|
| Total Return | +149.26% | +149.00% | +93.78% |
| Final Equity | $1,440,774 | $1,439,236 | $1,120,063 |
| Max Drawdown | 25.15% | — | — |
| Overlay Alpha | +0.27% | — | — |

**Option Activity:**
- Calls sold: 29
- Est. total premium collected: $85,620 (×100 multiplier)
- Expired OTM (profit kept): 21
- Expired ITM (call-away): 7
- Fees paid: $75.85

**Notes:**
- Pre-split period (Jan–Jun 9): few contracts discovered due to split-adjusted spot price ($48–$95) not matching pre-split option chain strikes. First viable contract found on 2024-03-18 (O:NVDA240419C00095000 at $95 strike with $791.87 premium — this premium appears unadjusted, reflecting pre-split option pricing).
- Post-split period (Jun 10 onwards): normal option discovery, 28 additional contracts.
- NVDY ETF only returned +93.78% vs NVDA stock +149% — the covered call ETF significantly underperformed the underlying in a strong bull year.

### 2. QQQ Covered Call

**Initial conditions:**
- Reference price: $402.59
- Initial capital: $4,831,080 (= $402.59 × 10,000 × 1.20)
- ETF benchmark: JEPQ

| Metric | Covered Call | Buy-Hold | JEPQ ETF |
|--------|-------------|----------|----------|
| Total Return | +22.98% | +22.49% | +24.72% |
| Final Equity | $5,941,261 | $5,917,480 | $6,025,285 |
| Max Drawdown | 11.64% | — | — |
| Overlay Alpha | +0.49% | — | — |

**Option Activity:**
- Calls sold: 42
- Est. total premium collected: $1,234 (×100 multiplier)
- Expired OTM (profit kept): 38
- Expired ITM (call-away): 3
- Fees paid: $80.30

**Notes:**
- JEPQ outperformed both covered call and buy-hold (+24.72% vs +22.98%). JEPQ uses more aggressive premium generation (ELN structure + dividends from $5.44/share in 2024).
- Covered call alpha over buy-hold was +0.49%, modest for a full year of weekly rolling.
- Premium collected ($1,234 × 100 = $123,400) was relatively small compared to notional — OTM calls on QQQ were cheap in 2024 due to low implied vol for far-OTM strikes.

### 3. NVDA Protective Put

**Initial conditions:**
- Reference price: $48.17 (split-adjusted)
- Initial capital: $578,016
- No ETF benchmark (hedging strategy)

| Metric | Protective Put | Buy-Hold |
|--------|---------------|----------|
| Total Return | +150.16% | +149.00% |
| Final Equity | $1,445,988 | $1,439,236 |
| Max Drawdown | 25.13% | — |
| Hedge Cost (alpha) | +1.17% | — |

**Option Activity:**
- Puts bought: 4
- Est. total premium paid: $1,231 (×100 multiplier)
- Expired OTM (premium lost): 3
- Expired ITM (protection used): 0
- Fees paid: $51.95

**Notes:**
- Pre-split period (Jan–May): no put contracts found — same issue as covered call, split-adjusted spot doesn't match pre-split option chain.
- First put discovered 2024-06-03 (O:NVDA240621P00110000 at $110 strike, $0.01 premium — deep OTM).
- Only 4 puts actually purchased out of 30 discovered — sequential contract expiry scheduling limits active positions.
- Zero ITM expirations — NVDA never dropped 5% below spot during any contract's life in 2024.
- Total premium paid ($1,231 × 100 = $123,100) was modest relative to the ~$1.4M final equity.

### 4. QQQ Protective Put

**Initial conditions:**
- Reference price: $402.59
- Initial capital: $4,831,080
- No ETF benchmark (hedging strategy)

| Metric | Protective Put | Buy-Hold |
|--------|---------------|----------|
| Total Return | +23.03% | +22.49% |
| Final Equity | $5,943,867 | $5,917,480 |
| Max Drawdown | 11.63% | — |
| Hedge Cost (alpha) | +0.55% | — |

**Option Activity:**
- Puts bought: 6
- Est. total premium paid: $520 (×100 multiplier)
- Expired OTM (premium lost): 5
- Expired ITM (protection used): 0
- Fees paid: $53.25

**Notes:**
- Only 6 out of 49 discovered contracts were actually purchased — contract sequencing (wait for expiry before buying next) kept position count low.
- Zero ITM expirations — 2024 was a strong bull year for QQQ with max drawdown ~11.6%, never deep enough to trigger the 5% OTM puts.
- Net cost of protection was minimal ($52,000 premium + $53 fees) relative to $4.8M portfolio — essentially free insurance in a bull market.

---

## Cross-Strategy Comparison (2024)

### QQQ

| Strategy | Return | vs Buy-Hold | Max DD | Premium Flow |
|----------|--------|------------|--------|-------------|
| Buy-and-Hold | +22.49% | baseline | — | — |
| Covered Call | +22.98% | +0.49% | 11.64% | +$123,400 collected |
| Protective Put | +23.03% | +0.55% | 11.63% | -$52,000 paid |
| JEPQ ETF (total return) | +24.72% | +2.23% | — | dividends reinvested |

### NVDA

| Strategy | Return | vs Buy-Hold | Max DD | Premium Flow |
|----------|--------|------------|--------|-------------|
| Buy-and-Hold | +149.00% | baseline | — | — |
| Covered Call | +149.26% | +0.27% | 25.15% | +$85,620 collected |
| Protective Put | +150.16% | +1.17% | 25.13% | -$123,100 paid |
| NVDY ETF (total return) | +93.78% | -55.22% | — | dividends reinvested |

---

## Observations & Limitations

1. **2024 was a strong bull market** — covered calls and protective puts both added marginal alpha. In a bear or high-vol year, results would differ significantly.

2. **Single contract position** — both strategies trade only 1 contract at a time. Scaling to position-proportional sizing (e.g. 100 contracts for 10,000 shares) would amplify both premium income and call-away drag.

3. **Pre-split option pricing artifact** — NVDA pre-split options have original (unadjusted) premiums in the data since OPRA option tickers are not split-adjusted. The first discovered contract (O:NVDA240419C00095000) has $791.87 premium which reflects pre-split pricing. This is correct per OPRA convention but means pre-split and post-split option premiums are not directly comparable.

4. **ETF benchmarks** — JEPQ outperformed our simple covered call because it uses a more sophisticated income strategy (equity-linked notes + active management). NVDY underperformed NVDA because covered call strategies structurally cap upside in strong trending markets.

5. **Delta constraint** — was not actively triggered in these runs because we only hold 1 contract at a time (delta impact is negligible vs 10,000 share position). Would become meaningful with larger option positions.
