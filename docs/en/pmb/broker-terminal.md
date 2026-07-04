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
| **Chart** | Toggle **Candles** (K-line, built minute-by-minute) or **Line**. Price axis, last-price marker, ET time axis. |
| **Option chain** | Toggle from *Chart*. See §4. |
| **Order ticket** | BUY/SELL, quantity, **MARKET**/**LIMIT**. Shows est. cost/proceeds and **buying power after** the order. |
| **Blotter** | *Positions* (with one-click **Flatten**), *Orders* (with **Cancel all**), *Trades*. **Close all** flattens every position. |
| **Account** | Full detail overlay — details, holdings (mkt value / weight / P&L), and history (live **equity curve** + trade log). |

## 3. Playback & time-travel

The status bar at the bottom is the market clock:

- **Open market** — seeks to the regular-session open (09:30 ET) and starts time.
- **Play / Pause**, single **step**, and a **speed slider** (1×–60× =
  market-minutes per second).
- **Timeline scrubber** — drag it. Dragging **back rewinds time and undoes every
  order placed after that moment** (deterministic replay). Dragging forward
  fast-forwards.

## 4. Options & the option chain

Switch the center panel to **Option chain**:

- Contracts are listed by **strike** for the selected underlying and expiry,
  with **last, IV, delta, volume**; the **ATM** strike is highlighted.
- Toggle **Calls / Puts** and pick an **expiry**.
- Click **B** / **S** on a row to trade that contract: the broker loads the
  contract into the session (`add_contracts`) and submits a market order.

Under the hood the chain comes from UPQ `/option/chain_query` (Black–Scholes
European greeks). Contract ids are OPRA, e.g. `O:AAPL240328C00170000`
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
