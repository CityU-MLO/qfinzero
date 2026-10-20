> 中文: [../../cn/pmb/broker-terminal.md](../../cn/pmb/broker-terminal.md)

# PMB Broker Terminal & Options Guide

The **Broker** is a standalone, real-broker-style trading site served by the
unified server at **`/broker`** (nav: *Broker*). It drives the PMB session
engine — real UPQ-priced fills over historical market data, minute by minute,
with a clock you control. This guide covers the terminal for humans and the
matching REST/MCP surface for agents, including **options and option
strategies**.

---

## 1. Getting on the floor

The landing page has two actions:

- **Allocate Account** — open a paper account: starting capital, market,
  leverage (1× / 2× / 4×), maintenance-margin threshold.
- **Enter Account** — pick an account, a **trading day**, and an initial
  **watchlist**, then *Open the market*. This creates a minute-frequency
  session over that day's real bars.

## 2. The trading floor

| Area | What it does |
|---|---|
| **Watchlist** | Live quotes with **% change from the open**. Add a symbol in the box at the bottom (loads its bars into the live session); remove with the trash icon. |
| **Chart** | Toggle **Candles** (K-line, built minute-by-minute) or **Line**. Candles overlay **MA5/MA20** moving averages and a **volume** histogram, with price axis, last-price marker and ET time axis. |
| **Option chain** | Toggle from *Chart*. See §4. |
| **Order ticket** | BUY/SELL, quantity, **MARKET**/**LIMIT**, and for stocks the **trading hours**: *Regular* (09:30–16:00 ET, any type), *Extended* (04:00–20:00) or *24/5* (with the Blue Ocean overnight session, 20:00–04:00); extended and 24/5 take limit orders only. Shows est. cost/proceeds and **buying power after** the order. |
| **Blotter** | *Positions* (with one-click **Flatten**), *Orders* (with **Cancel all**), *Trades*. **Close all** flattens every position. |
| **Account** | Full detail overlay — details, holdings (mkt value / weight / P&L), and history (live **equity curve** + trade log). |

## 3. Playback & time-travel

The status bar at the bottom is the market clock:

- **Open market** — seeks to the regular-session open (09:30 ET) and starts time.
  **From overnight** starts at 20:00 ET the evening before (the day's session
  opens with Blue Ocean's overnight session) and **From pre-market** at 04:00
  ET, when the day has bars there. The clock shows the segment it is in
  (overnight, pre-market, regular, after-hours); the chart shades the same
  segments. A regular-hours order placed outside 09:30–16:00 waits for the
  open, and the ticket says so; the Orders tab lists each order's hours.
- **Play / Pause**, single **step**, and a **speed slider** (1×–60× =
  market-minutes per second).
- **Timeline scrubber** — drag it. Dragging **back rewinds time and undoes every
  order placed after that moment** (deterministic replay). Dragging forward
  fast-forwards.

## 3a. Chart and order feedback

The chart (zoom with the wheel, pan by dragging) joins the minute bars from
before the session start, time-locked to the start, to the bars the session
plays, at 1, 5, 15 minutes or 1 hour, with MA20, VWAP and Bollinger bands.
Fills are marked on the candles (B/S with quantity and price), working limit
orders and the position's average price are drawn as lines.

Every order says what happened: a market order is announced when it fills on
the next bar (with the average price), a limit order as working and again when
it fills; the blotter switches to the matching tab and highlights the row.

## 4. Options & the option chain

Switch the center panel to **Option chain** — a **two-sided, live, minute-level**
chain (calls | strike | puts), like a real broker:

- Each strike shows **bid / ask / last / volume** on both the call and put side,
  with the **ATM** strike highlighted and the underlying **spot** shown. Bid and
  ask are the quotes in force at the current bar (blank when the store has no
  option quotes for that day).
- **Greeks** (on by default) adds IV, Δ, Γ, Θ and ν per leg, computed at the
  current bar from the underlying's minute close and the quote mid (else the
  last trade): they move with the clock. Grey values are the day's close
  Greeks, shown when there are no live ones. Without an interest rate for the
  date a banner links to Settings → Rates.
- It **flashes as the clock ticks** — the near-ATM legs update minute-by-minute
  (green/red on an up/down tick). Illiquid strikes fall back to the day's mark.
- Pick an **expiry**; click **B** / **S** on either side to trade that contract
  (the broker loads it into the session and submits a market order).

Performance: the chain **paints instantly** (~0.1s) from the cached day skeleton,
then the near-ATM contracts' minute bars load **concurrently in the background**
(`GET /v1/sessions/{id}/option_chain` returns `loading: true` and the UI re-polls)
so live marks fill in within ~1s. After that every step is a fast cache read.

Under the hood the strikes come from UPQ `/option/chain_query` and the live
marks, quotes and Greeks from `/option/chain_snapshot` at the session clock
(Black–Scholes European Greeks; the rate is the Treasury curve of the day, else
the latest earlier one). Contract ids are OPRA, e.g. `O:AAPL240328C00170000`
(underlying `AAPL`, expiry `2024-03-28`, `C`all, strike `170.000`).

> **Fills need data at the current minute.** An option order only fills if that
> contract has a bar at the current sim minute; otherwise it rests as a working
> order until one prints.

## 5. Option strategies

The engine supports every combination as a set of single-leg option positions,
so strategies are built by placing (or holding) the legs. Common ones:

| Strategy | Legs | View |
|---|---|---|
| **Long call / put** | Buy 1 call (or put) | Directional, defined risk |
| **Covered call** | Long 100 shares + short 1 call | Income on a holding |
| **Protective put** | Long 100 shares + long 1 put | Insured downside |
| **Vertical spread** | Long + short same type, different strikes | Defined-risk directional |
| **Straddle / strangle** | Long call + long put (same / different strikes) | Volatility |
| **Iron condor** | Short call spread + short put spread | Range-bound income |

**In the terminal:** place each leg from the option chain (buy the long legs,
sell the short legs) — e.g. a bull-call spread = **B** the lower strike and
**S** a higher strike on the same expiry. The Account → Holdings view shows the
combined position, greeks-adjusted P&L, and weight.

**Via the API (multi-leg in one call):** the order model also accepts a
`SpreadOrderSpec` (`legs` + `spread_type`, e.g. `PUT_DEBIT_SPREAD`,
`PUT_CREDIT_SPREAD`) for margin-aware two-leg spreads. Add the contracts first,
then submit the spread.

## 6. Agent API (REST + MCP)

Everything the terminal does is available to agents. Base URL is the PMB
service (or `…/api/pmb/v1` through the web BFF, `…/svc/pmb` through the hub).

| REST | MCP tool | Purpose |
|---|---|---|
| `POST /v1/accounts` | `pmb_create_account` | Allocate an account |
| `GET /v1/accounts` | — | List accounts |
| `POST /v1/sessions` | `pmb_create_session` | Start a day session (universe = stocks/options) |
| `POST /v1/sessions/{id}/step` | `pmb_step_session` | Advance N minutes |
| `GET /v1/sessions/{id}/state` | `pmb_session_state` | **One-call snapshot**: clock, account, positions, orders, trades, market |
| `GET /v1/sessions/{id}/timeline` | — | All bar timestamps (the scrubbable clock) |
| `POST /v1/sessions/{id}/rewind` | `pmb_rewind` | **Time-travel** back to `target_ts`, undoing later orders |
| `POST /v1/sessions/{id}/add_stocks` | `pmb_add_stocks` | Grow the watchlist/universe live |
| `POST /v1/sessions/{id}/add_contracts` | `pmb_add_contracts` | Load option contracts for trading |
| `GET /v1/sessions/{id}/option_chain` | — | Live two-sided minute chain at the current bar |
| `POST /v1/orders` | `pmb_buy_stock` / `pmb_sell_stock` / `pmb_buy_option` / `pmb_sell_option` | Place orders (stock or `OPTION:<contract>`) |
| `POST /v1/orders/{id}/cancel` | `pmb_cancel_order` | Cancel a working order |
| `GET /option/chain_query` (UPQ) | `upq_option_chain` | Discover option contracts + greeks |

**Typical agent loop:** `pmb_create_account` → `pmb_create_session` → loop
(`pmb_step_session` → `pmb_session_state` → decide → `pmb_buy_stock` /
`upq_option_chain` + `pmb_add_contracts` + `pmb_buy_option`) → `pmb_get_summary`.
Use `pmb_rewind` to branch from an earlier bar.

## 7. Windows 98 skin

The broker has a retro skin at **`/legacy/broker`** — classic gray-bevel
chrome (title bar, sunken status bar, raised buttons). Toggle it with the
**Win98 UI ⇄ Modern UI** button in the corner.
