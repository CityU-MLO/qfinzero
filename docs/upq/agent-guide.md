# UPQ Agent Tool Reference

This document describes the UPQ (Unified Price Query) client as a set of callable tools for an AI agent. Each tool maps to a `UPQClient` method.

## Setup

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from clients.upq import UPQClient, UPQError
upq = UPQClient()  # default: http://127.0.0.1:19350
```

---

## Tools

### 1. `stock_daily` — Get Stock Daily OHLCV

Fetch daily price bars for one or more stock tickers.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `tickers` | `list[str]` | Yes | Stock symbols, e.g. `["AAPL", "MSFT"]` |
| `start` | `str` | Yes | Start date `YYYY-MM-DD` |
| `end` | `str` | Yes | End date `YYYY-MM-DD` |
| `fields` | `str` | No | Comma-separated fields to return (reduces payload) |

**Example:**
```python
bars = upq.stock_daily(["AAPL", "MSFT"], "2025-01-06", "2025-01-17")
```

**Returns:** `list[dict]` — each dict:
```json
{
  "ticker": "AAPL",
  "date": "2025-01-06",
  "open": 243.74,
  "high": 244.13,
  "low": 241.35,
  "close": 242.21,
  "volume": 45036584,
  "transactions": 541072
}
```

**Available fields:** `ticker`, `date`, `open`, `high`, `low`, `close`, `volume`, `transactions`

**Field selection example:**
```python
bars = upq.stock_daily(["AAPL"], "2025-01-06", "2025-01-31", fields="ticker,date,close")
# Returns: [{"ticker": "AAPL", "date": "2025-01-06", "close": 242.21}, ...]
```

---

### 2. `stock_minute` — Get Stock Minute OHLCV

Fetch minute-level intraday price bars.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `tickers` | `list[str]` | Yes | Stock symbols |
| `start` | `str` | Yes | Start datetime `YYYY-MM-DDTHH:MM:SS` |
| `end` | `str` | Yes | End datetime `YYYY-MM-DDTHH:MM:SS` |
| `fields` | `str` | No | Comma-separated fields |
| `limit` | `int` | No | Max rows (1-100000, default 10000) |

**Example:**
```python
bars = upq.stock_minute(["AAPL"], "2025-01-06T09:30:00", "2025-01-06T10:00:00")
```

**Returns:** `list[dict]` — each dict:
```json
{
  "ticker": "AAPL",
  "window_start": 1736155800000000000,
  "open": 243.66,
  "high": 244.03,
  "low": 243.55,
  "close": 243.98,
  "volume": 1203845,
  "transactions": 14521
}
```

**Note:** `window_start` is nanoseconds since epoch. Convert with:
```python
from clients.upq import UPQClient
dt = UPQClient.ns_to_datetime(1736155800000000000)
# -> datetime(2025, 1, 6, 9, 30, tzinfo=UTC)
```

---

### 3. `option_chain` — Query Option Chain

Find option contracts for an underlying stock on a given date. Supports filtering by strike range, expiry range, and call/put type.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `underlying` | `str` | Yes | Underlying ticker, e.g. `"NVDA"` |
| `date` | `str` | Yes | Trade date `YYYY-MM-DD` |
| `type` | `str` | No | `"C"` for calls, `"P"` for puts |
| `strike_min` | `float` | No | Minimum strike price |
| `strike_max` | `float` | No | Maximum strike price |
| `expiry_min` | `str` | No | Earliest expiration date `YYYY-MM-DD` |
| `expiry_max` | `str` | No | Latest expiration date `YYYY-MM-DD` |
| `fields` | `str` | No | Comma-separated fields |

**Example:**
```python
chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                          strike_min=130, strike_max=150,
                          expiry_max="2025-02-21")
```

**Returns:** `list[dict]` — each dict:
```json
{
  "ticker": "O:NVDA250117C00130000",
  "underlying": "NVDA",
  "expiry": "2025-01-17",
  "strike": 130.0,
  "type": "C",
  "open": 12.45,
  "high": 13.20,
  "low": 11.80,
  "close": 12.95,
  "volume": 5432,
  "transactions": 312
}
```

**Common workflow — find highest-volume contract:**
```python
chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                          strike_min=130, strike_max=140)
best = max(chain, key=lambda x: x.get("volume", 0))
contract_id = best["ticker"]  # -> "O:NVDA250117C00136000"
```

---

### 4. `option_contract` — Get Option Contract Price Data

Fetch daily or minute-level price data for a specific option contract.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `contract` | `str` | Yes | OPRA contract ID, e.g. `"O:NVDA250117C00136000"` |
| `start` | `str` | Yes | Start date or datetime |
| `end` | `str` | Yes | End date or datetime |
| `resolution` | `str` | No | `"day"` (default) or `"minute"` |
| `fields` | `str` | No | Comma-separated fields |

**Example (daily):**
```python
bars = upq.option_contract("O:NVDA250117C00136000",
                            "2025-01-06", "2025-01-17", resolution="day")
```

**Returns (day resolution):** `list[dict]` — each dict:
```json
{
  "ticker": "O:NVDA250117C00136000",
  "window_start": 1736155800000000000,
  "open": 5.20,
  "high": 5.50,
  "low": 5.00,
  "close": 5.30,
  "volume": 10234,
  "transactions": 521
}
```

**Example (minute):**
```python
bars = upq.option_contract("O:NVDA250117C00136000",
                            "2025-01-06T09:30:00", "2025-01-06T16:00:00",
                            resolution="minute")
```

---

### 5. `rates` — Get Treasury Yield Curve

Fetch treasury yield data for various tenors.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `start` | `str` | Yes | Start date `YYYY-MM-DD` |
| `end` | `str` | Yes | End date `YYYY-MM-DD` |
| `tenors` | `str` | No | Comma-separated: `"1M,3M,1Y,2Y,5Y,10Y,30Y"` (default: all) |

**Example:**
```python
yields = upq.rates("2025-01-02", "2025-01-31", tenors="1M,10Y")
```

**Returns:** `list[dict]` — each dict:
```json
{
  "date": "2025-01-02",
  "yield_1_month": 4.34,
  "yield_10_year": 4.57
}
```

When no tenor filter is applied, all fields are returned:
```json
{
  "date": "2025-01-02",
  "yield_1_month": 4.34,
  "yield_3_month": 4.32,
  "yield_1_year": 4.21,
  "yield_2_year": 4.28,
  "yield_5_year": 4.42,
  "yield_10_year": 4.57,
  "yield_30_year": 4.78
}
```

**Yield spread calculation:**
```python
for row in yields:
    spread = row["yield_10_year"] - row["yield_1_month"]
    print(f"{row['date']}: 10Y-1M spread = {spread:+.2f}%")
```

---

### 6. `health` — Health Check

**Example:**
```python
status = upq.health()
# -> {"status": "ok"}
```

---

## Utility Functions

### `UPQClient.make_opra(underlying, expiry, right, strike)` — Build OPRA Contract ID

Constructs the standard OPRA contract identifier from components. This is a static method (no client instance needed).

| Name | Type | Description |
|------|------|-------------|
| `underlying` | `str` | Ticker symbol, e.g. `"NVDA"` |
| `expiry` | `str` | Expiration date `YYYY-MM-DD` |
| `right` | `str` | `"C"` for call, `"P"` for put |
| `strike` | `float` | Strike price |

```python
UPQClient.make_opra("NVDA", "2025-01-17", "C", 136.0)
# -> "O:NVDA250117C00136000"

UPQClient.make_opra("AAPL", "2025-02-21", "P", 230.0)
# -> "O:AAPL250221P00230000"
```

**Format:** `O:{TICKER}{YYMMDD}{C|P}{STRIKE*1000 zero-padded to 8 digits}`

### `UPQClient.ns_to_datetime(ns)` — Convert Nanosecond Timestamp

Converts `window_start` nanosecond timestamp to Python `datetime` (UTC).

```python
UPQClient.ns_to_datetime(1736155800000000000)
# -> datetime(2025, 1, 6, 9, 30, tzinfo=UTC)
```

---

## Error Handling

All methods raise `UPQError` on failure:

```python
from clients.upq import UPQError

try:
    bars = upq.stock_daily(["INVALID"], "bad-date", "2025-01-31")
except UPQError as e:
    print(e)              # Human-readable message
    print(e.status_code)  # HTTP status (400, 500, etc.)
    print(e.code)         # Error code: "invalid_argument" | "internal_error"
```

---

## Agent Workflow Examples

### Example 1: Get Current Stock Price

```python
from clients.upq import UPQClient

with UPQClient() as upq:
    bars = upq.stock_daily(["AAPL"], "2025-01-31", "2025-01-31")
    if bars:
        print(f"AAPL closed at ${bars[0]['close']:.2f} on {bars[0]['date']}")
```

### Example 2: Compare Multiple Stocks

```python
with UPQClient() as upq:
    bars = upq.stock_daily(["AAPL", "MSFT", "NVDA"], "2025-01-06", "2025-01-31",
                           fields="ticker,date,close")
    # Group by ticker
    by_ticker = {}
    for bar in bars:
        by_ticker.setdefault(bar["ticker"], []).append(bar)

    for ticker, data in by_ticker.items():
        first, last = data[0]["close"], data[-1]["close"]
        ret = (last - first) / first * 100
        print(f"{ticker}: {ret:+.2f}% ({first:.2f} -> {last:.2f})")
```

### Example 3: Find ATM Option and Get Its Price History

```python
with UPQClient() as upq:
    # Get stock price
    stock = upq.stock_daily(["NVDA"], "2025-01-06", "2025-01-06")
    spot = stock[0]["close"]  # e.g. 140.14

    # Find near-ATM calls
    chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                              strike_min=spot - 5, strike_max=spot + 5,
                              expiry_max="2025-02-21")

    # Pick the one closest to spot
    atm = min(chain, key=lambda x: abs(x["strike"] - spot))
    contract = atm["ticker"]

    # Get its daily history
    history = upq.option_contract(contract, "2025-01-06", "2025-01-17",
                                   resolution="day")
    for bar in history:
        dt = UPQClient.ns_to_datetime(bar["window_start"])
        print(f"{dt.date()}: close=${bar['close']:.2f}, vol={bar['volume']}")
```

### Example 4: Yield Curve Analysis

```python
with UPQClient() as upq:
    yields = upq.rates("2025-01-02", "2025-01-31")
    for row in yields:
        spread_2s10s = row["yield_10_year"] - row["yield_2_year"]
        spread_3m10y = row["yield_10_year"] - row["yield_3_month"]
        print(f"{row['date']}: 2s10s={spread_2s10s:+.2f}  3m10y={spread_3m10y:+.2f}")
```

---

## Date/Time Format Quick Reference

| Endpoint | Date Format | Example |
|----------|------------|---------|
| `stock_daily` | `YYYY-MM-DD` | `"2025-01-06"` |
| `stock_minute` | `YYYY-MM-DDTHH:MM:SS` | `"2025-01-06T09:30:00"` |
| `option_chain` | `YYYY-MM-DD` | `"2025-01-06"` |
| `option_contract` (day) | `YYYY-MM-DD` | `"2025-01-06"` |
| `option_contract` (minute) | `YYYY-MM-DDTHH:MM:SS` | `"2025-01-06T09:30:00"` |
| `rates` | `YYYY-MM-DD` | `"2025-01-02"` |

US market hours: 09:30 to 16:00 ET (14:30 to 21:00 UTC).
