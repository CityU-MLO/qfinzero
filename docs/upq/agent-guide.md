> **English** (below) · [中文](#中文文档) (在下方)

# UPQ Agent Tool Reference

This document describes the UPQ (Unified Price Query) client as a set of callable tools for an AI agent. Each tool maps to a `UPQClient` method.

## Setup

```python
from qfinzero.clients.upq import UPQClient, UPQError
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
from qfinzero.clients.upq import UPQClient
dt = UPQClient.ns_to_datetime(1736155800000000000)
# -> datetime(2025, 1, 6, 9, 30, tzinfo=UTC)
```

---

### 3. `option_chain` — Query Option Chain

Find option contracts for an underlying stock on a given date. Supports filtering by strike range, expiry range, and call/put type. Optionally compute BSM-European Greeks for each row.

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
| `include_greeks` | `bool` | No | When `True`, append BSM-European Greeks to each row (default `False`) |
| `greek_model` | `str` | No | Pricing model — only `"bsm"` supported in V1 |
| `greek_price_field` | `str` | No | Price field for IV inversion — only `"close"` supported in V1 |

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

Fetch daily or minute-level price data for a specific option contract. Optionally compute BSM-European Greeks for each row.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `contract` | `str` | Yes | OPRA contract ID, e.g. `"O:NVDA250117C00136000"` |
| `start` | `str` | Yes | Start date or datetime |
| `end` | `str` | Yes | End date or datetime |
| `resolution` | `str` | No | `"day"` (default) or `"minute"` |
| `fields` | `str` | No | Comma-separated fields |
| `include_greeks` | `bool` | No | When `True`, append BSM-European Greeks to each row (default `False`) |
| `greek_model` | `str` | No | Pricing model — only `"bsm"` supported in V1 |
| `greek_price_field` | `str` | No | Price field for IV inversion — only `"close"` supported in V1 |

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

## Greeks Parameters

Both `option_chain` and `option_contract` accept three optional Greeks parameters.

### `include_greeks` — Enable Greeks Computation

When set to `True`, each returned row is enriched with BSM-European Greeks fields: `iv`, `delta`, `gamma`, `theta`, `vega`, `rho`, `greek_status`, and `greek_meta`.

**Warning:** Greeks use European-style BSM approximation. This is an approximation for American-style options.

**Expiry Fallback & Greeks:** When an exact-expiry chain query triggers fallback, Greeks are computed using the actual returned expiry, not the requested date. Always check the `expiry` field in response rows.

### `greek_model` — Pricing Model

Selects the pricing model. Only `"bsm"` (Black-Scholes-Merton European) is supported in V1. Passing any other value returns a `400 invalid_argument` error.

### `greek_price_field` — Price Field for IV Inversion

Selects which option price field to use for implied volatility inversion. Only `"close"` is supported in V1. Passing any other value returns a `400 invalid_argument` error.

### Greek Status Values

The `greek_status` field in each enriched row indicates the outcome of the computation:

| Value | Meaning |
|-------|---------|
| `ok` | Computation succeeded |
| `below_intrinsic` | Option price is below intrinsic value, IV cannot be computed |
| `no_bracket` | IV solver could not bracket a solution |
| `no_convergence` | IV solver did not converge within iteration limit |
| `non_finite_input` | Input values contain NaN or infinity |
| `near_expiry_approx` | Near-expiry approximation used (may be less accurate) |
| `missing_spot` | Spot price not available for this row |
| `missing_rate` | Risk-free rate not available for this date |
| `model_error` | General model computation error |

### Conventions (from `greek_meta`)

| Field | Value |
|-------|-------|
| `theta_unit` | `per_day` |
| `vega_unit` | `per_1pct_vol` (per 1 percentage point of vol) |
| `rho_unit` | `per_1pct_rate` (per 1 percentage point of rate) |
| `t_convention` | `calendar_days_over_365` (day-level) or `minute_precise` for minute resolution |
| `expiry_anchor` | `expiry_date_16_00_ET` (4:00 PM Eastern Time on expiry date) |

### Example

```python
with UPQClient() as upq:
    chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                              strike_min=130, strike_max=150,
                              include_greeks=True)
    for row in chain:
        print(row["strike"], row.get("iv"), row.get("delta"), row.get("greek_status"))
```

### Greek Status Handling Pattern

When using Greeks, always check `greek_status` before using computed values:

```python
with UPQClient() as upq:
    chain = upq.option_chain("NVDA", "2025-01-15", type="C",
                              include_greeks=True)
    for row in chain:
        status = row.get("greek_status")
        if status == "ok":
            # Safe to use all Greek values
            iv = row["iv"]
            delta = row["delta"]
            theta = row["theta"]
        elif status in ("missing_spot", "missing_rate"):
            # Data gap — Greeks unavailable for this row
            print(f"Data gap: {status} for {row['ticker']}")
        elif status == "below_intrinsic":
            # Price below intrinsic — IV cannot be computed
            print(f"Below intrinsic: {row['ticker']}")
        else:
            # Other statuses: no_bracket, non_finite_input,
            # near_expiry_approx, model_error
            print(f"Status={status} for {row['ticker']}")
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
from qfinzero.clients.upq import UPQError

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
from qfinzero.clients.upq import UPQClient

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

---

<a id="中文文档"></a>

# 中文文档

# UPQ Agent 工具参考

本文档将 UPQ（统一价格查询，Unified Price Query）客户端描述为一组供 AI agent 调用的工具。每个工具对应一个 `UPQClient` 方法。

## 设置

```python
from qfinzero.clients.upq import UPQClient, UPQError
upq = UPQClient()  # default: http://127.0.0.1:19350
```

---

## 工具

### 1. `stock_daily` — 获取股票日频 OHLCV

获取一个或多个股票代码的日频价格 bar。

**参数：**

| 名称 | 类型 | 是否必需 | 说明 |
|------|------|----------|-------------|
| `tickers` | `list[str]` | 是 | 股票代码，例如 `["AAPL", "MSFT"]` |
| `start` | `str` | 是 | 起始日期 `YYYY-MM-DD` |
| `end` | `str` | 是 | 结束日期 `YYYY-MM-DD` |
| `fields` | `str` | 否 | 以逗号分隔的返回字段（可减少载荷体积） |

**示例：**
```python
bars = upq.stock_daily(["AAPL", "MSFT"], "2025-01-06", "2025-01-17")
```

**返回：** `list[dict]` — 每个 dict：
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

**可用字段：** `ticker`、`date`、`open`、`high`、`low`、`close`、`volume`、`transactions`

**字段选择示例：**
```python
bars = upq.stock_daily(["AAPL"], "2025-01-06", "2025-01-31", fields="ticker,date,close")
# Returns: [{"ticker": "AAPL", "date": "2025-01-06", "close": 242.21}, ...]
```

---

### 2. `stock_minute` — 获取股票分钟级 OHLCV

获取分钟级的盘中价格 bar。

**参数：**

| 名称 | 类型 | 是否必需 | 说明 |
|------|------|----------|-------------|
| `tickers` | `list[str]` | 是 | 股票代码 |
| `start` | `str` | 是 | 起始日期时间 `YYYY-MM-DDTHH:MM:SS` |
| `end` | `str` | 是 | 结束日期时间 `YYYY-MM-DDTHH:MM:SS` |
| `fields` | `str` | 否 | 以逗号分隔的字段 |
| `limit` | `int` | 否 | 最大行数（1-100000，默认 10000） |

**示例：**
```python
bars = upq.stock_minute(["AAPL"], "2025-01-06T09:30:00", "2025-01-06T10:00:00")
```

**返回：** `list[dict]` — 每个 dict：
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

**注意：** `window_start` 是自纪元（epoch）以来的纳秒数。转换方式：
```python
from qfinzero.clients.upq import UPQClient
dt = UPQClient.ns_to_datetime(1736155800000000000)
# -> datetime(2025, 1, 6, 9, 30, tzinfo=UTC)
```

---

### 3. `option_chain` — 查询期权链

查找某个标的股票在指定日期的期权合约。支持按行权价范围、到期日范围以及看涨/看跌类型进行筛选。可选地为每一行计算 BSM-欧式希腊字母。

**参数：**

| 名称 | 类型 | 是否必需 | 说明 |
|------|------|----------|-------------|
| `underlying` | `str` | 是 | 标的代码，例如 `"NVDA"` |
| `date` | `str` | 是 | 交易日 `YYYY-MM-DD` |
| `type` | `str` | 否 | `"C"` 表示看涨，`"P"` 表示看跌 |
| `strike_min` | `float` | 否 | 最小行权价 |
| `strike_max` | `float` | 否 | 最大行权价 |
| `expiry_min` | `str` | 否 | 最早到期日 `YYYY-MM-DD` |
| `expiry_max` | `str` | 否 | 最晚到期日 `YYYY-MM-DD` |
| `fields` | `str` | 否 | 以逗号分隔的字段 |
| `include_greeks` | `bool` | 否 | 当为 `True` 时，为每一行附加 BSM-欧式希腊字母（默认 `False`） |
| `greek_model` | `str` | 否 | 定价模型 — V1 中仅支持 `"bsm"` |
| `greek_price_field` | `str` | 否 | 用于 IV 反演的价格字段 — V1 中仅支持 `"close"` |

**示例：**
```python
chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                          strike_min=130, strike_max=150,
                          expiry_max="2025-02-21")
```

**返回：** `list[dict]` — 每个 dict：
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

**常见工作流 — 查找成交量最高的合约：**
```python
chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                          strike_min=130, strike_max=140)
best = max(chain, key=lambda x: x.get("volume", 0))
contract_id = best["ticker"]  # -> "O:NVDA250117C00136000"
```

---

### 4. `option_contract` — 获取期权合约价格数据

获取指定期权合约的日频或分钟级价格数据。可选地为每一行计算 BSM-欧式希腊字母。

**参数：**

| 名称 | 类型 | 是否必需 | 说明 |
|------|------|----------|-------------|
| `contract` | `str` | 是 | OPRA 合约 ID，例如 `"O:NVDA250117C00136000"` |
| `start` | `str` | 是 | 起始日期或日期时间 |
| `end` | `str` | 是 | 结束日期或日期时间 |
| `resolution` | `str` | 否 | `"day"`（默认）或 `"minute"` |
| `fields` | `str` | 否 | 以逗号分隔的字段 |
| `include_greeks` | `bool` | 否 | 当为 `True` 时，为每一行附加 BSM-欧式希腊字母（默认 `False`） |
| `greek_model` | `str` | 否 | 定价模型 — V1 中仅支持 `"bsm"` |
| `greek_price_field` | `str` | 否 | 用于 IV 反演的价格字段 — V1 中仅支持 `"close"` |

**示例（日频）：**
```python
bars = upq.option_contract("O:NVDA250117C00136000",
                            "2025-01-06", "2025-01-17", resolution="day")
```

**返回（day 分辨率）：** `list[dict]` — 每个 dict：
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

**示例（分钟级）：**
```python
bars = upq.option_contract("O:NVDA250117C00136000",
                            "2025-01-06T09:30:00", "2025-01-06T16:00:00",
                            resolution="minute")
```

---

### 5. `rates` — 获取国债收益率曲线

获取各种期限的国债收益率数据。

**参数：**

| 名称 | 类型 | 是否必需 | 说明 |
|------|------|----------|-------------|
| `start` | `str` | 是 | 起始日期 `YYYY-MM-DD` |
| `end` | `str` | 是 | 结束日期 `YYYY-MM-DD` |
| `tenors` | `str` | 否 | 以逗号分隔：`"1M,3M,1Y,2Y,5Y,10Y,30Y"`（默认：全部） |

**示例：**
```python
yields = upq.rates("2025-01-02", "2025-01-31", tenors="1M,10Y")
```

**返回：** `list[dict]` — 每个 dict：
```json
{
  "date": "2025-01-02",
  "yield_1_month": 4.34,
  "yield_10_year": 4.57
}
```

当未应用期限筛选时，返回所有字段：
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

**收益率利差计算：**
```python
for row in yields:
    spread = row["yield_10_year"] - row["yield_1_month"]
    print(f"{row['date']}: 10Y-1M spread = {spread:+.2f}%")
```

---

### 6. `health` — 健康检查

**示例：**
```python
status = upq.health()
# -> {"status": "ok"}
```

---

## 希腊字母参数

`option_chain` 和 `option_contract` 都接受三个可选的希腊字母参数。

### `include_greeks` — 启用希腊字母计算

当设置为 `True` 时，每一返回行都会附加 BSM-欧式希腊字母字段：`iv`、`delta`、`gamma`、`theta`、`vega`、`rho`、`greek_status` 以及 `greek_meta`。

**警告：** 希腊字母使用欧式风格的 BSM 近似。对于美式期权而言这是一种近似。

**到期回退与希腊字母：** 当精确到期日的期权链查询触发回退时，希腊字母将基于实际返回的到期日计算，而非请求的日期。请始终核对响应行中的 `expiry` 字段。

### `greek_model` — 定价模型

选择定价模型。V1 中仅支持 `"bsm"`（Black-Scholes-Merton 欧式）。传入任何其他值都会返回 `400 invalid_argument` 错误。

### `greek_price_field` — 用于 IV 反演的价格字段

选择用于隐含波动率反演的期权价格字段。V1 中仅支持 `"close"`。传入任何其他值都会返回 `400 invalid_argument` 错误。

### 希腊字母状态值（Greek Status）

每一附加行中的 `greek_status` 字段指示计算结果：

| 值 | 含义 |
|-------|---------|
| `ok` | 计算成功 |
| `below_intrinsic` | 期权价格低于内在价值，无法计算 IV |
| `no_bracket` | IV 求解器无法为解设定区间 |
| `no_convergence` | IV 求解器在迭代次数上限内未收敛 |
| `non_finite_input` | 输入值中包含 NaN 或无穷大 |
| `near_expiry_approx` | 使用了临近到期近似（准确性可能较低） |
| `missing_spot` | 该行缺少现货价格 |
| `missing_rate` | 该日期缺少无风险利率 |
| `model_error` | 一般性模型计算错误 |

### 约定（来自 `greek_meta`）

| 字段 | 值 |
|-------|-------|
| `theta_unit` | `per_day` |
| `vega_unit` | `per_1pct_vol`（每 1 个百分点的波动率） |
| `rho_unit` | `per_1pct_rate`（每 1 个百分点的利率） |
| `t_convention` | `calendar_days_over_365`（日级别），或分钟分辨率下为 `minute_precise` |
| `expiry_anchor` | `expiry_date_16_00_ET`（到期日美国东部时间下午 4:00） |

### 示例

```python
with UPQClient() as upq:
    chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                              strike_min=130, strike_max=150,
                              include_greeks=True)
    for row in chain:
        print(row["strike"], row.get("iv"), row.get("delta"), row.get("greek_status"))
```

### 希腊字母状态处理模式

使用希腊字母时，请始终在使用计算值之前检查 `greek_status`：

```python
with UPQClient() as upq:
    chain = upq.option_chain("NVDA", "2025-01-15", type="C",
                              include_greeks=True)
    for row in chain:
        status = row.get("greek_status")
        if status == "ok":
            # Safe to use all Greek values
            iv = row["iv"]
            delta = row["delta"]
            theta = row["theta"]
        elif status in ("missing_spot", "missing_rate"):
            # Data gap — Greeks unavailable for this row
            print(f"Data gap: {status} for {row['ticker']}")
        elif status == "below_intrinsic":
            # Price below intrinsic — IV cannot be computed
            print(f"Below intrinsic: {row['ticker']}")
        else:
            # Other statuses: no_bracket, non_finite_input,
            # near_expiry_approx, model_error
            print(f"Status={status} for {row['ticker']}")
```

---

## 实用函数

### `UPQClient.make_opra(underlying, expiry, right, strike)` — 构建 OPRA 合约 ID

从各组成部分构造标准的 OPRA 合约标识符。这是一个静态方法（无需客户端实例）。

| 名称 | 类型 | 说明 |
|------|------|-------------|
| `underlying` | `str` | 代码符号，例如 `"NVDA"` |
| `expiry` | `str` | 到期日 `YYYY-MM-DD` |
| `right` | `str` | `"C"` 表示看涨，`"P"` 表示看跌 |
| `strike` | `float` | 行权价 |

```python
UPQClient.make_opra("NVDA", "2025-01-17", "C", 136.0)
# -> "O:NVDA250117C00136000"

UPQClient.make_opra("AAPL", "2025-02-21", "P", 230.0)
# -> "O:AAPL250221P00230000"
```

**格式：** `O:{TICKER}{YYMMDD}{C|P}{STRIKE*1000 zero-padded to 8 digits}`

### `UPQClient.ns_to_datetime(ns)` — 转换纳秒时间戳

将 `window_start` 纳秒时间戳转换为 Python `datetime`（UTC）。

```python
UPQClient.ns_to_datetime(1736155800000000000)
# -> datetime(2025, 1, 6, 9, 30, tzinfo=UTC)
```

---

## 错误处理

所有方法在失败时都会抛出 `UPQError`：

```python
from qfinzero.clients.upq import UPQError

try:
    bars = upq.stock_daily(["INVALID"], "bad-date", "2025-01-31")
except UPQError as e:
    print(e)              # Human-readable message
    print(e.status_code)  # HTTP status (400, 500, etc.)
    print(e.code)         # Error code: "invalid_argument" | "internal_error"
```

---

## Agent 工作流示例

### 示例 1：获取当前股票价格

```python
from qfinzero.clients.upq import UPQClient

with UPQClient() as upq:
    bars = upq.stock_daily(["AAPL"], "2025-01-31", "2025-01-31")
    if bars:
        print(f"AAPL closed at ${bars[0]['close']:.2f} on {bars[0]['date']}")
```

### 示例 2：比较多只股票

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

### 示例 3：查找平值（ATM）期权并获取其价格历史

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

### 示例 4：收益率曲线分析

```python
with UPQClient() as upq:
    yields = upq.rates("2025-01-02", "2025-01-31")
    for row in yields:
        spread_2s10s = row["yield_10_year"] - row["yield_2_year"]
        spread_3m10y = row["yield_10_year"] - row["yield_3_month"]
        print(f"{row['date']}: 2s10s={spread_2s10s:+.2f}  3m10y={spread_3m10y:+.2f}")
```

---

## 日期/时间格式速查

| 端点 | 日期格式 | 示例 |
|----------|------------|---------|
| `stock_daily` | `YYYY-MM-DD` | `"2025-01-06"` |
| `stock_minute` | `YYYY-MM-DDTHH:MM:SS` | `"2025-01-06T09:30:00"` |
| `option_chain` | `YYYY-MM-DD` | `"2025-01-06"` |
| `option_contract`（day） | `YYYY-MM-DD` | `"2025-01-06"` |
| `option_contract`（minute） | `YYYY-MM-DDTHH:MM:SS` | `"2025-01-06T09:30:00"` |
| `rates` | `YYYY-MM-DD` | `"2025-01-02"` |

美国市场交易时段：美东时间 09:30 至 16:00（UTC 14:30 至 21:00）。
