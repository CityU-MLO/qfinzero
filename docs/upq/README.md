> **English** (below) · [中文](#中文文档) (在下方)

# UPQ — Unified Price Query

A high-performance Rust-based price query service providing REST API access to stock, option, and treasury rates data. Uses DuckDB + Parquet for efficient storage and querying.

## Server

- **Language**: Rust (Axum)
- **Default Port**: 19350
- **Entry Point**: `cargo run -p upq-service`

```bash
cd infra/upq
cargo build --release
cargo run -p upq-ingest -- ingest --raw-root ~/upq_data --storage-root ~/upq_storage
STORAGE_ROOT=~/upq_storage cargo run -p upq-service
# http://127.0.0.1:19350
```

## API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/stock` | GET | Stock minute OHLCV data (ISO datetime format) |
| `/stock/daily` | GET | Stock daily OHLCV data (date format) |
| `/option` | GET | Option endpoints metadata |
| `/option/ticker_query` | GET | Query option by OPRA contract |
| `/option/chain_query` | GET | Query option chain by underlying with filters |
| `/rates/query` | GET | Treasury yield curve data |

## Key Concepts

### Date/Time Formats

- **Minute endpoints** (`/stock`): ISO datetime `YYYY-MM-DDTHH:MM:SS`
- **Daily endpoints** (`/stock/daily`, `/rates/query`): Date `YYYY-MM-DD`
- **Option endpoints**: Accept both formats depending on resolution

### Data Types

- **Stock**: Minute and daily OHLCV with volume and transaction counts
- **Options**: Contract-level data with OPRA symbol support, chain queries with strike/expiry/type filters
- **Rates**: Treasury yields for tenors 1M, 3M, 1Y, 2Y, 5Y, 10Y, 30Y

### Workspace Crates

| Crate | Purpose |
|-------|---------|
| `upq-core` | Schema, validation, OPRA parser, SQL builders |
| `upq-service` | Axum API routes and request validation |
| `upq-ingest` | Data ingestion, manifest tracking, idempotency |
| `upq-bench` | Latency/throughput benchmarks |

## Quick Example

```bash
# Stock daily data
curl "http://127.0.0.1:19350/stock/daily?tickers=AAPL&start=2025-01-01&end=2025-01-31"

# Stock minute data
curl "http://127.0.0.1:19350/stock?tickers=AAPL&start=2025-01-06T09:30:00&end=2025-01-06T16:00:00"

# Option chain
curl "http://127.0.0.1:19350/option/chain_query?underlying=NVDA&date=2025-01-15&type=C"

# Treasury yields
curl "http://127.0.0.1:19350/rates/query?start=2025-01-01&end=2025-01-31&tenors=1M,10Y"
```

## Python Client

The UPQ client library (`clients/upq/`) wraps the REST API for clean Python usage.

### Basic Usage

```python
from qfinzero.clients.upq import UPQClient

with UPQClient() as upq:
    # Stock daily bars
    bars = upq.stock_daily(["AAPL", "MSFT"], "2025-01-06", "2025-01-31")
    for bar in bars:
        print(bar["ticker"], bar["date"], bar["close"])

    # Stock minute bars
    bars = upq.stock_minute(["AAPL"], "2025-01-06T09:30:00", "2025-01-06T16:00:00")

    # Option chain
    chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                              strike_min=130, strike_max=150)

    # Specific option contract
    bars = upq.option_contract("O:NVDA250117C00136000",
                                "2025-01-06", "2025-01-17", resolution="day")

    # Treasury yields
    yields = upq.rates("2025-01-02", "2025-01-31", tenors="1M,10Y")
```

### Client API

| Method | Description |
|--------|-------------|
| `stock_daily(tickers, start, end)` | Daily OHLCV bars (date format) |
| `stock_minute(tickers, start, end)` | Minute OHLCV bars (datetime format) |
| `option_chain(underlying, date, ...)` | Option chain with strike/expiry/type filters |
| `option_contract(contract, start, end, resolution)` | Specific contract price data |
| `rates(start, end, tenors)` | Treasury yield curve |
| `health()` | Health check |

### Utilities

```python
# Build OPRA contract ID
UPQClient.make_opra("NVDA", "2025-01-17", "C", 136.0)
# -> "O:NVDA250117C00136000"

# Convert nanosecond timestamp to datetime
UPQClient.ns_to_datetime(1736155800000000000)
# -> datetime(2025, 1, 6, 9, 30, tzinfo=UTC)
```

### Error Handling

```python
from qfinzero.clients.upq import UPQClient, UPQError

try:
    bars = upq.stock_daily(["INVALID"], "bad-date", "2025-01-31")
except UPQError as e:
    print(f"Error: {e}, code={e.code}, status={e.status_code}")
```

### Greeks Computation (Optional)

Both `/option/chain_query` and `/option/ticker_query` support optional realtime BSM-European Greeks computation via `include_greeks=true`.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `include_greeks` | bool | `false` | Enable Greeks computation |
| `greek_model` | string | `bsm` | Pricing model (only `bsm` in V1) |
| `greek_price_field` | string | `close` | Price field for IV inversion (only `close` in V1) |

**Response Fields (when `include_greeks=true`):**
Each option row is enriched with: `iv`, `delta`, `gamma`, `theta`, `vega`, `rho`, `greek_status`, `greek_meta`.

**Greek Status Values:**
- `ok` — Computation succeeded
- `below_intrinsic` — Option price is below intrinsic value, IV cannot be computed
- `no_bracket` — IV solver could not bracket a solution
- `no_convergence` — IV solver did not converge within iteration limit
- `non_finite_input` — Input values contain NaN or infinity
- `near_expiry_approx` — Near-expiry approximation used (may be less accurate)
- `missing_spot` — Spot price not available for this row
- `missing_rate` — Risk-free rate not available for this date
- `model_error` — General model computation error

**Important:** Greeks use European-style BSM approximation. This is an approximation for American-style options. The `greek_meta` field in each response row documents the exact model, conventions, and data sources used.

**Expiry Fallback & Greeks:** When an exact-expiry chain query triggers fallback (no rows for the requested expiry), Greeks are computed using the **actual returned expiry**, not the requested date. Always verify the `expiry` field in response rows to avoid misinterpreting which contract the Greeks belong to.

**Conventions:**
- `theta_unit`: per_day
- `vega_unit`: per_1pct_vol (per 1 percentage point of volatility)
- `rho_unit`: per_1pct_rate (per 1 percentage point of rate)
- `t_convention`: `calendar_days_over_365` (day-level), or `minute_precise` for minute resolution
- `expiry_anchor`: expiry_date_16_00_ET (4:00 PM Eastern Time on expiry date)

**Example with Greeks (curl):**
```bash
# Option chain with Greeks
curl "http://127.0.0.1:19350/option/chain_query?underlying=NVDA&date=2025-01-15&type=C&include_greeks=true"

# Contract history with Greeks
curl "http://127.0.0.1:19350/option/ticker_query?contract=O:NVDA250221C00140000&start=2025-01-06&end=2025-01-17&include_greeks=true"
```

**Example with Greeks (Python):**
```python
with UPQClient() as upq:
    # Chain with Greeks
    chain = upq.option_chain("NVDA", "2025-01-15", type="C",
                              strike_min=130, strike_max=150,
                              include_greeks=True)
    for row in chain:
        if row.get("greek_status") == "ok":
            print(f"K={row['strike']} IV={row['iv']:.4f} "
                  f"delta={row['delta']:.4f} theta={row['theta']:.4f}")
        else:
            print(f"K={row['strike']} status={row['greek_status']}")

    # Contract history with Greeks
    bars = upq.option_contract("O:NVDA250221C00140000",
                                "2025-01-06", "2025-01-17",
                                include_greeks=True)
```

## Configuration

| Environment Variable | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `STORAGE_ROOT` | Yes | — | Path to ingested Parquet data |
| `PORT` | No | 19350 | Server port |
| `RUST_LOG` | No | info | Log level |

## References

- [OpenAPI Specification](openapi.yaml)
- [Server Implementation](../../infra/upq/)
- [Client Library](../../clients/upq/)
- [Demos](../../demos/upq/)

---

<a id="中文文档"></a>

# 中文文档

# UPQ — 统一价格查询（Unified Price Query）

一个基于 Rust 的高性能价格查询服务，通过 REST API 提供对股票、期权和国债利率数据的访问。底层使用 DuckDB + Parquet 实现高效的存储与查询。

## 服务端

- **语言**：Rust (Axum)
- **默认端口**：19350
- **入口点**：`cargo run -p upq-service`

```bash
cd infra/upq
cargo build --release
cargo run -p upq-ingest -- ingest --raw-root ~/upq_data --storage-root ~/upq_storage
STORAGE_ROOT=~/upq_storage cargo run -p upq-service
# http://127.0.0.1:19350
```

## API 概览

| 端点 | 方法 | 说明 |
|----------|--------|-------------|
| `/health` | GET | 健康检查 |
| `/stock` | GET | 股票分钟级 OHLCV 数据（ISO 日期时间格式） |
| `/stock/daily` | GET | 股票日频 OHLCV 数据（日期格式） |
| `/option` | GET | 期权端点元数据 |
| `/option/ticker_query` | GET | 按 OPRA 合约查询期权 |
| `/option/chain_query` | GET | 按标的物查询期权链，支持筛选条件 |
| `/rates/query` | GET | 国债收益率曲线数据 |

## 关键概念

### 日期/时间格式

- **分钟级端点**（`/stock`）：ISO 日期时间 `YYYY-MM-DDTHH:MM:SS`
- **日频端点**（`/stock/daily`、`/rates/query`）：日期 `YYYY-MM-DD`
- **期权端点**：根据分辨率同时接受两种格式

### 数据类型

- **股票**：分钟级和日频 OHLCV，包含成交量与成交笔数
- **期权**：合约级数据，支持 OPRA 符号，期权链查询支持行权价/到期日/类型筛选
- **利率**：国债收益率，期限包括 1M、3M、1Y、2Y、5Y、10Y、30Y

### 工作区 Crate

| Crate | 用途 |
|-------|---------|
| `upq-core` | Schema、校验、OPRA 解析器、SQL 构造器 |
| `upq-service` | Axum API 路由与请求校验 |
| `upq-ingest` | 数据摄取、清单跟踪、幂等性 |
| `upq-bench` | 延迟/吞吐量基准测试 |

## 快速示例

```bash
# Stock daily data
curl "http://127.0.0.1:19350/stock/daily?tickers=AAPL&start=2025-01-01&end=2025-01-31"

# Stock minute data
curl "http://127.0.0.1:19350/stock?tickers=AAPL&start=2025-01-06T09:30:00&end=2025-01-06T16:00:00"

# Option chain
curl "http://127.0.0.1:19350/option/chain_query?underlying=NVDA&date=2025-01-15&type=C"

# Treasury yields
curl "http://127.0.0.1:19350/rates/query?start=2025-01-01&end=2025-01-31&tenors=1M,10Y"
```

## Python 客户端

UPQ 客户端库（`clients/upq/`）对 REST API 进行了封装，以便在 Python 中干净地调用。

### 基本用法

```python
from qfinzero.clients.upq import UPQClient

with UPQClient() as upq:
    # Stock daily bars
    bars = upq.stock_daily(["AAPL", "MSFT"], "2025-01-06", "2025-01-31")
    for bar in bars:
        print(bar["ticker"], bar["date"], bar["close"])

    # Stock minute bars
    bars = upq.stock_minute(["AAPL"], "2025-01-06T09:30:00", "2025-01-06T16:00:00")

    # Option chain
    chain = upq.option_chain("NVDA", "2025-01-06", type="C",
                              strike_min=130, strike_max=150)

    # Specific option contract
    bars = upq.option_contract("O:NVDA250117C00136000",
                                "2025-01-06", "2025-01-17", resolution="day")

    # Treasury yields
    yields = upq.rates("2025-01-02", "2025-01-31", tenors="1M,10Y")
```

### 客户端 API

| 方法 | 说明 |
|--------|-------------|
| `stock_daily(tickers, start, end)` | 日频 OHLCV bar（日期格式） |
| `stock_minute(tickers, start, end)` | 分钟级 OHLCV bar（日期时间格式） |
| `option_chain(underlying, date, ...)` | 期权链，支持行权价/到期日/类型筛选 |
| `option_contract(contract, start, end, resolution)` | 指定合约的价格数据 |
| `rates(start, end, tenors)` | 国债收益率曲线 |
| `health()` | 健康检查 |

### 实用工具

```python
# Build OPRA contract ID
UPQClient.make_opra("NVDA", "2025-01-17", "C", 136.0)
# -> "O:NVDA250117C00136000"

# Convert nanosecond timestamp to datetime
UPQClient.ns_to_datetime(1736155800000000000)
# -> datetime(2025, 1, 6, 9, 30, tzinfo=UTC)
```

### 错误处理

```python
from qfinzero.clients.upq import UPQClient, UPQError

try:
    bars = upq.stock_daily(["INVALID"], "bad-date", "2025-01-31")
except UPQError as e:
    print(f"Error: {e}, code={e.code}, status={e.status_code}")
```

### 希腊字母计算（可选）

`/option/chain_query` 和 `/option/ticker_query` 均支持通过 `include_greeks=true` 进行可选的实时 BSM-欧式希腊字母（Greeks）计算。

**查询参数：**
| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `include_greeks` | bool | `false` | 启用希腊字母计算 |
| `greek_model` | string | `bsm` | 定价模型（V1 中仅支持 `bsm`） |
| `greek_price_field` | string | `close` | 用于 IV 反演的价格字段（V1 中仅支持 `close`） |

**响应字段（当 `include_greeks=true` 时）：**
每一行期权数据都会附加以下字段：`iv`、`delta`、`gamma`、`theta`、`vega`、`rho`、`greek_status`、`greek_meta`。

**希腊字母状态值（Greek Status）：**
- `ok` — 计算成功
- `below_intrinsic` — 期权价格低于内在价值，无法计算 IV
- `no_bracket` — IV 求解器无法为解设定区间
- `no_convergence` — IV 求解器在迭代次数上限内未收敛
- `non_finite_input` — 输入值中包含 NaN 或无穷大
- `near_expiry_approx` — 使用了临近到期近似（准确性可能较低）
- `missing_spot` — 该行缺少现货价格
- `missing_rate` — 该日期缺少无风险利率
- `model_error` — 一般性模型计算错误

**重要提示：** 希腊字母使用欧式风格的 BSM 近似。对于美式期权而言这是一种近似。每一行响应中的 `greek_meta` 字段记录了所使用的确切模型、约定以及数据来源。

**到期回退与希腊字母：** 当精确到期日的期权链查询触发回退（请求的到期日没有数据行）时，希腊字母将基于**实际返回的到期日**计算，而非请求的日期。请始终核对响应行中的 `expiry` 字段，以避免误判希腊字母所属的合约。

**约定（Conventions）：**
- `theta_unit`：per_day
- `vega_unit`：per_1pct_vol（每 1 个百分点的波动率）
- `rho_unit`：per_1pct_rate（每 1 个百分点的利率）
- `t_convention`：`calendar_days_over_365`（日级别），或分钟分辨率下为 `minute_precise`
- `expiry_anchor`：expiry_date_16_00_ET（到期日美国东部时间下午 4:00）

**带希腊字母的示例（curl）：**
```bash
# Option chain with Greeks
curl "http://127.0.0.1:19350/option/chain_query?underlying=NVDA&date=2025-01-15&type=C&include_greeks=true"

# Contract history with Greeks
curl "http://127.0.0.1:19350/option/ticker_query?contract=O:NVDA250221C00140000&start=2025-01-06&end=2025-01-17&include_greeks=true"
```

**带希腊字母的示例（Python）：**
```python
with UPQClient() as upq:
    # Chain with Greeks
    chain = upq.option_chain("NVDA", "2025-01-15", type="C",
                              strike_min=130, strike_max=150,
                              include_greeks=True)
    for row in chain:
        if row.get("greek_status") == "ok":
            print(f"K={row['strike']} IV={row['iv']:.4f} "
                  f"delta={row['delta']:.4f} theta={row['theta']:.4f}")
        else:
            print(f"K={row['strike']} status={row['greek_status']}")

    # Contract history with Greeks
    bars = upq.option_contract("O:NVDA250221C00140000",
                                "2025-01-06", "2025-01-17",
                                include_greeks=True)
```

## 配置

| 环境变量 | 是否必需 | 默认值 | 说明 |
|---------------------|----------|---------|-------------|
| `STORAGE_ROOT` | 是 | — | 已摄取的 Parquet 数据路径 |
| `PORT` | 否 | 19350 | 服务端口 |
| `RUST_LOG` | 否 | info | 日志级别 |

## 参考资料

- [OpenAPI 规范](openapi.yaml)
- [服务端实现](../../infra/upq/)
- [客户端库](../../clients/upq/)
- [演示](../../demos/upq/)
