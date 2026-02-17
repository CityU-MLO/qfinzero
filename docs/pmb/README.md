# PMB — Paper Money Broker

A step-driven paper trading broker for backtesting AI trading agents. Supports stocks and options with full margin accounting, deterministic replay, and comprehensive event streams.

## Server

- **Language**: Python (FastAPI)
- **Default Port**: 24444
- **Entry Point**: `infra/pmb/main.py`
- **Dependency**: Requires UPQ service running for market data

```bash
cd infra/pmb
pip install -r requirements.txt
python main.py
# http://127.0.0.1:24444
```

## API Overview

**Base URL**: `http://127.0.0.1:24444/v1`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/accounts` | POST | Create account with initial cash + margin config |
| `/accounts/{id}` | GET | Get account snapshot (cash, positions, equity) |
| `/sessions` | POST | Create replay session (prefetches market data from UPQ) |
| `/sessions/{id}/step` | POST | Advance simulation clock, return events |
| `/sessions/{id}/summary` | GET | Session metrics (return, drawdown, fees) |
| `/orders` | POST | Place order (idempotent via `client_order_id`) |
| `/orders/{id}/cancel` | POST | Cancel a pending order |

## Key Concepts

### Step-Driven Simulation

Time advances only via `POST /sessions/{id}/step`. No wall-clock dependency — the agent controls time progression. Each step returns typed events in a fixed order:

```
MARKET_TICK → ORDER_EVENT → TRADE_EVENT → ACCOUNT_SNAPSHOT → RISK_EVENT
```

### Supported Assets

- **Stocks**: OHLCV bars at minute/daily resolution
- **Options**: OPRA contracts with full chain data

### Order Types

- `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`
- Time-in-force: `DAY`, `GTC`, `GTD`
- Idempotent via `client_order_id`

### Margin Accounting

- Initial margin / maintenance margin tracking
- Buying power computation
- Margin call events

### Trading Frequencies

- `1m` — Intraday strategies with minute bars
- `1d` — Multi-day strategies with daily bars

## Quick Example

```bash
# Create account
curl -X POST http://127.0.0.1:24444/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{"account_type": "MARGIN", "initial_cash": 100000.0, "start_date": "2025-01-06"}'

# Create session
curl -X POST http://127.0.0.1:24444/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{
    "account_id": "<account_id>",
    "frequency": "1d",
    "start_ts": "2025-01-06",
    "end_ts": "2025-02-06",
    "universe": {"stocks": ["AAPL"]}
  }'

# Step simulation
curl -X POST http://127.0.0.1:24444/v1/sessions/<session_id>/step \
  -H 'Content-Type: application/json' \
  -d '{"step": 1}'

# Place order
curl -X POST http://127.0.0.1:24444/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "<session_id>",
    "account_id": "<account_id>",
    "client_order_id": "buy_1",
    "order": {
      "instrument": {"type": "STOCK", "symbol": "AAPL"},
      "side": "BUY", "order_type": "MARKET", "qty": 10, "time_in_force": "DAY"
    }
  }'
```

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `PMB_HOST` | 127.0.0.1 | Bind host |
| `PMB_PORT` | 24444 | Bind port |
| `PMB_UPQ_BASE_URL` | http://127.0.0.1:23333 | UPQ service URL |
| `PMB_LOG_LEVEL` | INFO | Log level |

## References

- [OpenAPI Specification](openapi.yaml)
- [Server Implementation](../../infra/pmb/)
- [Client Library](../../clients/pmb/)
- [Demos](../../demos/pmb/)
