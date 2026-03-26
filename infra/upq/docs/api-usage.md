# UPQ API Usage Guide

Base URL: `http://127.0.0.1:19703`

---

## Quick Reference

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/stock` | GET | Stock minute bars |
| `/stock/daily` | GET | Stock daily bars |
| `/option` | GET | Option endpoint metadata |
| `/option/ticker_query` | GET | Option contract data |
| `/option/chain_query` | GET | Option chain for underlying |
| `/rates/query` | GET | Treasury yield rates |

All endpoints return JSON arrays (except `/health` and `/option`). All errors return `400` with `{"code": "invalid_argument", "message": "..."}`.

---

## Endpoints

### GET /health

Returns `{"status": "ok"}` when the service is running.

```bash
curl http://127.0.0.1:19703/health
```

---

### GET /stock

Query minute-level stock price bars.

**Parameters:**

| Param | Required | Format | Example |
|---|---|---|---|
| `tickers` | yes | comma-separated symbols | `AAPL,MSFT` |
| `start` | yes | `YYYY-MM-DDTHH:MM:SS` | `2025-01-06T09:30:00` |
| `end` | yes | `YYYY-MM-DDTHH:MM:SS` | `2025-01-06T16:00:00` |
| `fields` | no | comma-separated | `close,volume` |
| `limit` | no | integer 1–100000 | `5000` (default: 10000) |

**Fields:** `ticker`, `window_start`, `open`, `high`, `low`, `close`, `volume`, `transactions`

**Example:**

```bash
curl "http://127.0.0.1:19703/stock?tickers=AAPL&start=2025-01-06T09:30:00&end=2025-01-06T16:00:00&fields=ticker,window_start,close,volume"
```

**Response:**

```json
[
  {
    "ticker": "AAPL",
    "window_start": 1736155800000000000,
    "close": 100.9,
    "volume": 5000000
  }
]
```

`window_start` is nanoseconds since Unix epoch. Sort order: `ticker, window_start`.

---

### GET /stock/daily

Query daily stock price bars.

**Parameters:**

| Param | Required | Format | Example |
|---|---|---|---|
| `tickers` | yes | comma-separated symbols | `AAPL,MSFT` |
| `start` | yes | `YYYY-MM-DD` | `2025-01-06` |
| `end` | yes | `YYYY-MM-DD` | `2025-01-10` |
| `fields` | no | comma-separated | `close,volume` |

**Fields:** `ticker`, `trade_date`, `date`, `open`, `high`, `low`, `close`, `volume`, `transactions`

`date` is an alias for `trade_date`.

**Example:**

```bash
curl "http://127.0.0.1:19703/stock/daily?tickers=AAPL,MSFT&start=2025-01-06&end=2025-01-10"
```

**Response:**

```json
[
  {
    "ticker": "AAPL",
    "date": "2025-01-06",
    "open": 100.5,
    "high": 101.2,
    "low": 99.8,
    "close": 100.9,
    "volume": 45000000,
    "transactions": 150000
  }
]
```

Sort order: `ticker, trade_date`.

---

### GET /option

Returns available option query paths.

```bash
curl http://127.0.0.1:19703/option
```

```json
{
  "ticker_query_path": "/option/ticker_query",
  "chain_query_path": "/option/chain_query"
}
```

---

### GET /option/ticker_query

Query price data for a specific option contract.

**Parameters:**

| Param | Required | Format | Example |
|---|---|---|---|
| `contract` | yes | OPRA contract ID | `O:NVDA250117C00136000` |
| `start` | yes | date or datetime | `2025-01-06` or `2025-01-06T09:30:00` |
| `end` | yes | date or datetime | `2025-01-10` or `2025-01-06T16:00:00` |
| `resolution` | no | `day` or `minute` | `day` (default: `day`) |
| `fields` | no | comma-separated | `close,volume` |

**OPRA contract format:** `O:{UNDERLYING}{YYMMDD}{C|P}{STRIKE×1000 zero-padded to 8 digits}`

Example: `O:NVDA250117C00136000` = NVDA call, expires 2025-01-17, strike $136.00

**Fields (minute):** `ticker`, `contract`, `window_start`, `open`, `high`, `low`, `close`, `volume`, `transactions`

**Fields (day):** all minute fields plus `underlying`, `expiry`, `strike`, `right`, `type`

`contract` is an alias for `ticker`. `type` is an alias for `right`.

**Example (day):**

```bash
curl "http://127.0.0.1:19703/option/ticker_query?contract=O:NVDA250117C00136000&start=2025-01-06&end=2025-01-10&resolution=day"
```

```json
[
  {
    "contract": "O:NVDA250117C00136000",
    "underlying": "NVDA",
    "expiry": "2025-01-17",
    "strike": 136.0,
    "type": "C",
    "open": 3.0,
    "high": 3.5,
    "low": 2.8,
    "close": 3.2,
    "volume": 100,
    "transactions": 5,
    "window_start": 1736496000000000000
  }
]
```

**Example (minute):**

```bash
curl "http://127.0.0.1:19703/option/ticker_query?contract=O:NVDA250117C00136000&start=2025-01-06T09:30:00&end=2025-01-06T16:00:00&resolution=minute"
```

Sort order: `window_start`.

---

### GET /option/chain_query

Query the full option chain for an underlying on a given date.

**Parameters:**

| Param | Required | Format | Example |
|---|---|---|---|
| `underlying` | yes | ticker symbol | `NVDA` |
| `date` | yes | `YYYY-MM-DD` | `2025-01-06` |
| `expiry_min` | no | `YYYY-MM-DD` | `2025-01-10` |
| `expiry_max` | no | `YYYY-MM-DD` | `2025-02-21` |
| `strike_min` | no | float | `130.0` |
| `strike_max` | no | float | `140.0` |
| `type` | no | `C` or `P` | `C` |
| `fields` | no | comma-separated | `close,volume,strike` |

**Fields:** `ticker`, `contract`, `underlying`, `expiry`, `strike`, `right`, `type`, `close`, `volume`

`contract` is an alias for `ticker`. `type` is an alias for `right`.

**Exact-expiry fallback behavior:**

- Trigger: `expiry_min` and `expiry_max` are both provided and equal, and the exact query returns no rows.
- Scope: fallback lookup is constrained by the same `underlying`, `type`, and strike filters from the request.
- Stage 1: search nearest available expiry within `target_expiry ± 7` calendar days.
- Stage 2: if stage 1 is empty, search nearest available expiry inside the same calendar month as `target_expiry`.
- Selection: choose smallest absolute day difference; if tied, choose earlier expiry.
- If neither stage finds candidates, response remains `[]` (HTTP 200).
- When `include_greeks=true`, Greeks are computed using the actual returned expiry, not the requested date. Always check the `expiry` field in response rows.

**Example:**

```bash
curl "http://127.0.0.1:19703/option/chain_query?underlying=NVDA&date=2025-01-06&type=C&strike_min=130&strike_max=140&expiry_max=2025-02-21"
```

```json
[
  {
    "underlying": "NVDA",
    "expiry": "2025-01-17",
    "strike": 136.0,
    "type": "C",
    "close": 3.2,
    "volume": 100
  }
]
```

Sort order: `expiry, strike`.

---

### GET /rates/query

Query U.S. Treasury yield rates.

**Parameters:**

| Param | Required | Format | Example |
|---|---|---|---|
| `start` | yes | `YYYY-MM-DD` | `2025-01-02` |
| `end` | yes | `YYYY-MM-DD` | `2025-01-31` |
| `tenors` | no | comma-separated | `1M,10Y` (default: all) |

**Supported tenors:** `1M`, `3M`, `1Y`, `2Y`, `5Y`, `10Y`, `30Y`

**Example:**

```bash
curl "http://127.0.0.1:19703/rates/query?start=2025-01-02&end=2025-01-10&tenors=1M,10Y"
```

```json
[
  {
    "date": "2025-01-02",
    "yield_1_month": 1.53,
    "yield_10_year": 1.88
  },
  {
    "date": "2025-01-03",
    "yield_1_month": 1.52,
    "yield_10_year": 1.80
  }
]
```

Sort order: `date`. Only dates present in source data are returned (no forward fill).

---

## Error Handling

All validation errors return HTTP 400:

```json
{
  "code": "invalid_argument",
  "message": "limit must be between 1 and 100000"
}
```

Internal errors return HTTP 500:

```json
{
  "code": "internal_error",
  "message": "duckdb error: ..."
}
```

**Common validation rules:**

| Rule | Detail |
|---|---|
| `tickers` empty | returns 400 |
| invalid date format | returns 400; use `YYYY-MM-DD` for dates, `YYYY-MM-DDTHH:MM:SS` for datetimes |
| unknown field name | returns 400 |
| `limit` out of range | must be 1–100000 |
| `resolution` invalid | must be `day` or `minute` |
| `type` invalid | must be `C` or `P` (case-insensitive) |
| bad OPRA contract | must match `O:{TICKER}{YYMMDD}{C|P}{8-digit strike}` |

---

## Agent Integration Guide

This section is for AI agents (LLM tool-use, automated pipelines) calling the UPQ API.

### Constructing Requests

All endpoints use GET with query parameters. URL-encode parameter values.

```python
import requests

BASE = "http://127.0.0.1:19703"

# Stock minute bars
resp = requests.get(f"{BASE}/stock", params={
    "tickers": "AAPL,MSFT",
    "start": "2025-01-06T09:30:00",
    "end": "2025-01-06T16:00:00",
    "fields": "ticker,window_start,close,volume",
})
rows = resp.json()  # list of dicts

# Stock daily bars
resp = requests.get(f"{BASE}/stock/daily", params={
    "tickers": "AAPL",
    "start": "2025-01-06",
    "end": "2025-01-10",
})

# Option contract (minute)
resp = requests.get(f"{BASE}/option/ticker_query", params={
    "contract": "O:NVDA250117C00136000",
    "start": "2025-01-06T09:30:00",
    "end": "2025-01-06T16:00:00",
    "resolution": "minute",
})

# Option chain
resp = requests.get(f"{BASE}/option/chain_query", params={
    "underlying": "NVDA",
    "date": "2025-01-06",
    "type": "C",
    "strike_min": "130",
    "strike_max": "140",
})

# Treasury rates
resp = requests.get(f"{BASE}/rates/query", params={
    "start": "2025-01-02",
    "end": "2025-01-31",
    "tenors": "1M,10Y",
})
```

### Parsing Timestamps

`window_start` is nanoseconds since Unix epoch. Convert to datetime:

```python
from datetime import datetime, timezone

ns = 1736155800000000000
dt = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
# 2025-01-06 09:30:00+00:00
```

### Building OPRA Contract IDs

To construct an OPRA contract string programmatically:

```python
def make_opra(underlying: str, expiry: str, right: str, strike: float) -> str:
    """
    underlying: "NVDA"
    expiry: "2025-01-17" (YYYY-MM-DD)
    right: "C" or "P"
    strike: 136.0
    """
    yy, mm, dd = expiry[2:4], expiry[5:7], expiry[8:10]
    strike_int = int(round(strike * 1000))
    return f"O:{underlying}{yy}{mm}{dd}{right}{strike_int:08d}"

# O:NVDA250117C00136000
make_opra("NVDA", "2025-01-17", "C", 136.0)
```

### Workflow: Get Option Chain Then Query Contracts

A common pattern is to first discover contracts via chain query, then fetch detailed data:

```python
# Step 1: Get the chain
chain = requests.get(f"{BASE}/option/chain_query", params={
    "underlying": "NVDA",
    "date": "2025-01-06",
    "type": "C",
    "strike_min": "130",
    "strike_max": "140",
    "expiry_max": "2025-02-21",
}).json()

# Step 2: Query minute data for each contract
for row in chain:
    contract = row["ticker"]  # or row["contract"]
    bars = requests.get(f"{BASE}/option/ticker_query", params={
        "contract": contract,
        "start": "2025-01-06T09:30:00",
        "end": "2025-01-06T16:00:00",
        "resolution": "minute",
    }).json()
    # process bars...
```

### Best Practices for Agents

1. **Use `fields` to limit columns** — reduces response size and speeds up queries.
2. **Respect the 100k row limit** on `/stock` — narrow your date range or use fewer tickers if you hit it.
3. **Check HTTP status** — 400 means bad input (fix the request), 500 means server issue (retry or report).
4. **Date format matters** — minute endpoints require `YYYY-MM-DDTHH:MM:SS`, daily/chain/rates require `YYYY-MM-DD`. Mixing them up returns 400.
5. **Rates have no forward fill** — missing dates (weekends, holidays) are simply absent from results.
6. **`type` filter is case-insensitive** — both `C` and `c` work for calls.
7. **Empty results are valid** — an empty `[]` with HTTP 200 means no data exists for that query, not an error.
