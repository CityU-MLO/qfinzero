> 中文: [../../docs/cn/infra/pmb/README.md](../../docs/cn/infra/pmb/README.md)


# Paper Money Broker (PMB)

A step-driven paper trading broker for backtesting AI trading agents. Supports stocks and options with full margin accounting, deterministic replay, and comprehensive event streams.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the server (requires UPQ on port 19350)
python main.py

# 3. Run demos
python demos/daily_buy_close.py
```

Server will listen on **http://127.0.0.1:19380**

---

## Architecture

PMB is a **FastAPI-based paper broker** designed for deterministic backtesting with these principles:

- **Step-driven**: Time advances via `POST /sessions/{id}/step` (no wall-clock dependency)
- **In-memory state**: Sessions are ephemeral replay episodes (fast, no DB overhead)
- **Event-sourced**: Every step returns typed events (MARKET_TICK, ORDER_EVENT, TRADE_EVENT, etc.)
- **Margin-aware**: Full initial/maintenance margin tracking with margin calls
- **Idempotent orders**: `client_order_id` prevents duplicate submissions

---

## Features

### Core Capabilities

- **Assets**: Stocks + Options (OPRA contracts)
- **Order Types**: MARKET, LIMIT, STOP, STOP_LIMIT
- **Time-in-Force**: DAY, GTC, GTD
- **Margin**: Initial/maintenance margins, buying power, margin calls
- **Execution**: Configurable slippage, commission models, partial fills
- **History**: Full order/trade/equity curve export (JSON/CSV)

### Trading Frequencies

- **Minute (1m)**: Intraday strategies with minute bars
- **Daily (1d)**: Multi-day strategies with daily bars

### Data Source

Integrates with **UPQ** (Unified Price Query) service:
- REST API at http://127.0.0.1:19350
- Stocks: minute/daily OHLCV bars
- Options: contract data with OPRA IDs
- See: [infra/upq/docs/api-usage.md](../upq/docs/api-usage.md)

---

## Broker Accounts (day-gated) + Terminal UI

On top of the replay engine, PMB exposes a **self-contained broker account** designed
for AI agents to drive directly — no backtest session required.

- **Unique 10-digit account id** is allocated per account. The leading digit encodes
  the market (`1`→US, `6`→CN, `3`→HK), so the number is self-describing — like a real
  brokerage routing prefix.
- **Multi-market**: each account is opened against a `market` (`us` / `cn` / `hk`),
  which sets the base currency (USD / CNY / HKD) and the exchange timezone.
- **Query by id**: any user or agent can pull full status from just the account id.
- **Trading history by step**: every closed trading day is appended to the account's
  history as one record (opening/closing equity, day P&L, the day's fills, positions).
- **Day-gating / freeze**: trading is allowed while `ACTIVE`. Calling **end_day**
  freezes the account (`FROZEN`) and records the day; trades are rejected until the
  agent calls **next_day**, which advances the simulated calendar to the next weekday
  and re-opens the book.

### Terminal UI

A dependency-free single-page UI ships with the server (served same-origin, no build):

```
open  http://127.0.0.1:19380/        # redirects to /ui/
```

It supports **two themes** (toggle, top-right; preference persists):

- **Modern** — dark glassy trading terminal.
- **Windows 98** — classic silver chrome, beveled windows, navy title bars.

From the UI you can allocate an account, query status by id, place buy/sell tickets,
end the day (freeze), advance to the next day, and browse the step-by-step history.

### Broker API

```bash
# Allocate a US account → returns a 10-digit account_id
curl -X POST http://127.0.0.1:19380/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{"market": "us", "initial_cash": 100000, "open_date": "2024-01-02"}'

# Query status by id
curl http://127.0.0.1:19380/v1/accounts/1840293756/status

# Trade (immediate fill at supplied price; only while ACTIVE)
curl -X POST http://127.0.0.1:19380/v1/accounts/1840293756/trade \
  -H 'Content-Type: application/json' \
  -d '{"symbol": "AAPL", "side": "BUY", "qty": 100, "price": 187.4}'

# End the day (freeze) → records a history step
curl -X POST http://127.0.0.1:19380/v1/accounts/1840293756/end_day

# Next day (unfreeze + advance calendar)
curl -X POST http://127.0.0.1:19380/v1/accounts/1840293756/next_day

# Step-by-step trading history
curl http://127.0.0.1:19380/v1/accounts/1840293756/history
```

Python client / MCP equivalents: `pmb.create_account(market=...)`, `pmb.get_status`,
`pmb.trade` / `broker_buy` / `broker_sell`, `pmb.end_day`, `pmb.next_day`,
`pmb.get_history`; MCP tools `pmb_create_account`, `pmb_get_status`, `pmb_trade`,
`pmb_end_day`, `pmb_next_day`, `pmb_get_history`.

---

## API Overview

**Base URL**: `http://127.0.0.1:19380/v1`

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/accounts` | POST | Allocate account (`market`, initial cash, open_date) → 10-digit id |
| `/accounts/{id}` | GET | Account snapshot (live session snapshot if attached, else broker book) |
| `/accounts/{id}/status` | GET | Canonical broker status (balances, P&L, day-gate state) |
| `/accounts/{id}/trade` | POST | Immediate paper fill (ACTIVE only) |
| `/accounts/{id}/end_day` | POST | Close trading day → freeze + record history step |
| `/accounts/{id}/next_day` | POST | Unfreeze + advance to next trading day |
| `/accounts/{id}/history` | GET | Step-by-step trading history (one record per day) |
| `/accounts/{id}/close` | POST | Permanently close the account |
| `/sessions` | POST | Create replay session (prefetches data) |
| `/sessions/{id}/step` | POST | Advance clock, return events |
| `/sessions/{id}/summary` | GET | Session metrics (return, drawdown, fees) |
| `/orders` | POST | Place order (idempotent via client_order_id) |
| `/orders/{id}/cancel` | POST | Cancel order |
| `/ui/` | GET | Broker Terminal UI (modern + Windows 98 themes) |

See full API spec in the [original design doc](../../.claude/plans/cozy-nibbling-wombat.md).

---

## Project Structure

```
pmb/
├── main.py                      # FastAPI app entry
├── config.py                    # Settings (ports, UPQ URL)
├── requirements.txt
│
├── models/                      # Pydantic models (no logic)
│   ├── enums.py                 # OrderSide, OrderType, OrderStatus, etc.
│   ├── instrument.py            # STOCK/OPTION instruments, OPRA helpers
│   ├── account.py               # Account, MarginConfig, AccountState
│   ├── session.py               # Session, ClockState, SessionSummary
│   ├── order.py                 # Order, OrderRequest
│   ├── trade.py                 # Trade (fill record)
│   ├── position.py              # Position
│   ├── event.py                 # Event payloads (6 event types)
│   └── market.py                # StockBar, OptionBar
│
├── domain/                      # Pure business logic (no I/O)
│   ├── session_clock.py         # Time management, step increments
│   ├── market_data_cache.py     # Prefetched bars, zero I/O during step
│   ├── order_manager.py         # Order state machine, idempotency
│   ├── execution_engine.py      # Match orders vs bars, fill logic
│   ├── margin_engine.py         # IM/MM calculation, margin calls
│   ├── ledger.py                # Cash, positions, P&L, avg cost
│   └── history_store.py         # Event/order/trade/snapshot log
│
├── clients/
│   └── upq_client.py            # Async UPQ HTTP client
│
├── services/                    # Orchestration (thin layer)
│   ├── account_service.py       # Account CRUD
│   ├── session_service.py       # Session lifecycle + step loop
│   ├── order_service.py         # Order placement/cancel/modify
│   └── history_service.py       # Query/export history
│
├── routes/                      # FastAPI routes (thin handlers)
│   ├── health.py
│   ├── accounts.py
│   ├── sessions.py
│   ├── orders.py
│   └── market.py
│
├── demos/                       # Strategy examples
│   ├── README.md                # Demo documentation
│   ├── result_saver.py          # Utility to save results
│   ├── daily_buy_close.py       # Daily accumulation strategy
│   ├── intraday_5min_signal.py  # Mean reversion (5-min signal)
│   ├── covered_call.py          # Option covered call
│   └── run_all.py               # Run all demos in sequence
│
└── results/                     # Demo outputs (gitignored)
    └── {strategy}_{timestamp}/
        ├── summary.json
        ├── holdings.json/csv
        ├── operations.json
        ├── orders.csv
        ├── trades.csv
        ├── equity_curve.json/csv
        └── report.txt
```

---

## Usage Examples

### 1. Create Account

```bash
curl -X POST http://127.0.0.1:19380/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{
    "account_type": "MARGIN",
    "initial_cash": 100000.0,
    "start_date": "2025-01-06"
  }'
```

### 2. Create Session

```bash
curl -X POST http://127.0.0.1:19380/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{
    "account_id": "acct_abc123",
    "frequency": "1m",
    "start_ts": "2025-01-06T09:30:00",
    "end_ts": "2025-01-06T16:00:00",
    "universe": {"stocks": ["AAPL"]},
    "reproducibility": {"seed": 42}
  }'
```

### 3. Step Simulation

```bash
curl -X POST http://127.0.0.1:19380/v1/sessions/sess_xyz/step \
  -H 'Content-Type: application/json' \
  -d '{"step": 1}'
```

Returns:
```json
{
  "ok": true,
  "clock": {
    "current_ts": "2025-01-06T09:31:00-05:00",
    "status": "RUNNING"
  },
  "events": [
    {"type": "MARKET_TICK", "payload": {...}},
    {"type": "ACCOUNT_SNAPSHOT", "payload": {...}}
  ]
}
```

### 4. Place Order

```bash
curl -X POST http://127.0.0.1:19380/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "sess_xyz",
    "account_id": "acct_abc123",
    "client_order_id": "my_buy_1",
    "order": {
      "instrument": {"type": "STOCK", "symbol": "AAPL"},
      "side": "BUY",
      "order_type": "MARKET",
      "qty": 10,
      "time_in_force": "DAY"
    }
  }'
```

### 5. Get Summary

```bash
curl http://127.0.0.1:19380/v1/sessions/sess_xyz/summary
```

Returns:
```json
{
  "final_equity": 101234.5,
  "total_return": 0.012345,
  "max_drawdown": 0.0231,
  "fees_paid": 12.34,
  "num_orders": 120,
  "num_trades": 98
}
```

---

## Demos

Three complete strategy examples under `demos/`:

1. **Daily Buy-at-Close** ([daily_buy_close.py](demos/daily_buy_close.py))
   - Buy 10 shares AAPL every day at close for one month
   - Demonstrates daily frequency + accumulation

2. **Intraday 5-Min Mean Reversion** ([intraday_5min_signal.py](demos/intraday_5min_signal.py))
   - Every 5 minutes: if price down → buy, if price up → sell
   - Demonstrates minute frequency + signal-based trading

3. **Covered Call** ([covered_call.py](demos/covered_call.py))
   - Buy 100 NVDA shares + sell 1 OTM call
   - Demonstrates option trading + margin

Each demo saves detailed results to `results/` folder (holdings, operations, equity curve).

See [demos/README.md](demos/README.md) for full documentation.

---

## Configuration

Edit [config.py](config.py) or set environment variables:

```bash
export PMB_HOST=127.0.0.1
export PMB_PORT=19380
export PMB_UPQ_BASE_URL=http://127.0.0.1:19350
export PMB_LOG_LEVEL=INFO
```

---

## Development

### Run Server

```bash
python main.py
# or with reload:
uvicorn main:app --host 127.0.0.1 --port 19380 --reload
```

### Run Tests

```bash
# Import check
python -c "from main import app; print('OK')"

# Manual API test
curl http://127.0.0.1:19380/v1/health
```

---

## Key Design Decisions

| Aspect | Choice | Rationale |
|---|---|---|
| **Web Framework** | FastAPI | Async, Pydantic validation, auto OpenAPI docs |
| **State Storage** | In-memory | Fast, deterministic, no DB overhead for ephemeral sessions |
| **Time Model** | Step-driven | Agent controls time progression (no wall-clock race conditions) |
| **Data Source** | UPQ prefetch | Fetch all bars at session creation (zero I/O during stepping) |
| **Order Idempotency** | client_order_id | Replay-safe, prevents duplicate submissions |
| **Event Order** | Fixed sequence | MARKET_TICK → ORDER → TRADE → SNAPSHOT → RISK (predictable) |

---

## Limitations (v0.1)

- No database persistence (sessions lost on server restart)
- No portfolio optimization / rebalancing endpoints
- Options: simplified margin (no spread recognition)
- No real-time mode (step-driven only)
- No order modify endpoint yet (use cancel + new order)

---

## References

- [Plan Document](../../.claude/plans/cozy-nibbling-wombat.md) - Full implementation plan
- [UPQ API Docs](../upq/docs/api-usage.md) - Market data service API
- [Demo Guide](demos/README.md) - Strategy examples + result analysis

---

## License

Internal tool for qfinzero project.
