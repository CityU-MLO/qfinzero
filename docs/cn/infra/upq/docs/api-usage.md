> English: [../../../../../infra/upq/docs/api-usage.md](../../../../../infra/upq/docs/api-usage.md)

# UPQ API 使用指南

Base URL: `http://127.0.0.1:19350`

---

## 快速参考

| Endpoint | Method | 说明 |
|---|---|---|
| `/health` | GET | 健康检查 |
| `/stock` | GET | 股票分钟 K 线 |
| `/stock/daily` | GET | 股票日 K 线 |
| `/option` | GET | 期权端点元数据 |
| `/option/ticker_query` | GET | 期权合约数据 |
| `/option/chain_query` | GET | 标的的期权链 |
| `/rates/query` | GET | 国债收益率 |

所有端点均返回 JSON 数组（`/health` 和 `/option` 除外）。所有错误都返回 `400`，格式为 `{"code": "invalid_argument", "message": "..."}`。

---

## 端点

### GET /health

当服务运行时返回 `{"status": "ok"}`。

```bash
curl http://127.0.0.1:19350/health
```

---

### GET /stock

查询分钟级股票价格 K 线。

**参数：**

| Param | 必填 | 格式 | 示例 |
|---|---|---|---|
| `tickers` | 是 | 逗号分隔的代码 | `AAPL,MSFT` |
| `start` | 是 | `YYYY-MM-DDTHH:MM:SS` | `2025-01-06T09:30:00` |
| `end` | 是 | `YYYY-MM-DDTHH:MM:SS` | `2025-01-06T16:00:00` |
| `fields` | 否 | 逗号分隔 | `close,volume` |
| `limit` | 否 | 整数 1–100000 | `5000`（默认：10000） |

**字段：** `ticker`、`window_start`、`open`、`high`、`low`、`close`、`volume`、`transactions`

**示例：**

```bash
curl "http://127.0.0.1:19350/stock?tickers=AAPL&start=2025-01-06T09:30:00&end=2025-01-06T16:00:00&fields=ticker,window_start,close,volume"
```

**响应：**

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

`window_start` 为自 Unix 纪元起的纳秒数。排序顺序：`ticker, window_start`。

---

### GET /stock/daily

查询每日股票价格 K 线。

**参数：**

| Param | 必填 | 格式 | 示例 |
|---|---|---|---|
| `tickers` | 是 | 逗号分隔的代码 | `AAPL,MSFT` |
| `start` | 是 | `YYYY-MM-DD` | `2025-01-06` |
| `end` | 是 | `YYYY-MM-DD` | `2025-01-10` |
| `fields` | 否 | 逗号分隔 | `close,volume` |

**字段：** `ticker`、`trade_date`、`date`、`open`、`high`、`low`、`close`、`volume`、`transactions`

`date` 是 `trade_date` 的别名。

**示例：**

```bash
curl "http://127.0.0.1:19350/stock/daily?tickers=AAPL,MSFT&start=2025-01-06&end=2025-01-10"
```

**响应：**

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

排序顺序：`ticker, trade_date`。

---

### GET /option

返回可用的期权查询路径。

```bash
curl http://127.0.0.1:19350/option
```

```json
{
  "ticker_query_path": "/option/ticker_query",
  "chain_query_path": "/option/chain_query"
}
```

---

### GET /option/ticker_query

查询特定期权合约的价格数据。

**参数：**

| Param | 必填 | 格式 | 示例 |
|---|---|---|---|
| `contract` | 是 | OPRA 合约 ID | `O:NVDA250117C00136000` |
| `start` | 是 | 日期或日期时间 | `2025-01-06` 或 `2025-01-06T09:30:00` |
| `end` | 是 | 日期或日期时间 | `2025-01-10` 或 `2025-01-06T16:00:00` |
| `resolution` | 否 | `day` 或 `minute` | `day`（默认：`day`） |
| `fields` | 否 | 逗号分隔 | `close,volume` |

**OPRA 合约格式：** `O:{UNDERLYING}{YYMMDD}{C|P}{STRIKE×1000 zero-padded to 8 digits}`

示例：`O:NVDA250117C00136000` = NVDA 看涨期权，到期日 2025-01-17，行权价 $136.00

**字段（minute）：** `ticker`、`contract`、`window_start`、`open`、`high`、`low`、`close`、`volume`、`transactions`

**字段（day）：** 所有 minute 字段，外加 `underlying`、`expiry`、`strike`、`right`、`type`

`contract` 是 `ticker` 的别名。`type` 是 `right` 的别名。

**示例（day）：**

```bash
curl "http://127.0.0.1:19350/option/ticker_query?contract=O:NVDA250117C00136000&start=2025-01-06&end=2025-01-10&resolution=day"
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

**示例（minute）：**

```bash
curl "http://127.0.0.1:19350/option/ticker_query?contract=O:NVDA250117C00136000&start=2025-01-06T09:30:00&end=2025-01-06T16:00:00&resolution=minute"
```

排序顺序：`window_start`。

---

### GET /option/chain_query

查询某标的在给定日期的完整期权链。

**参数：**

| Param | 必填 | 格式 | 示例 |
|---|---|---|---|
| `underlying` | 是 | 代码符号 | `NVDA` |
| `date` | 是 | `YYYY-MM-DD` | `2025-01-06` |
| `expiry_min` | 否 | `YYYY-MM-DD` | `2025-01-10` |
| `expiry_max` | 否 | `YYYY-MM-DD` | `2025-02-21` |
| `strike_min` | 否 | float | `130.0` |
| `strike_max` | 否 | float | `140.0` |
| `type` | 否 | `C` 或 `P` | `C` |
| `fields` | 否 | 逗号分隔 | `close,volume,strike` |

**字段：** `ticker`、`contract`、`underlying`、`expiry`、`strike`、`right`、`type`、`close`、`volume`

`contract` 是 `ticker` 的别名。`type` 是 `right` 的别名。

**精确到期日回退行为：**

- 触发条件：`expiry_min` 和 `expiry_max` 均提供且相等，且精确查询未返回任何行。
- 范围：回退查找受请求中相同的 `underlying`、`type` 和行权价筛选条件约束。
- 阶段 1：在 `target_expiry ± 7` 日历天内搜索最接近的可用到期日。
- 阶段 2：若阶段 1 为空，则在与 `target_expiry` 相同的日历月内搜索最接近的可用到期日。
- 选择：选择绝对天数差最小者；若相等，则选择较早的到期日。
- 若两个阶段都未找到候选，响应仍为 `[]`（HTTP 200）。
- 当 `include_greeks=true` 时，希腊字母使用实际返回的到期日计算，而非请求的日期。请始终检查响应行中的 `expiry` 字段。

**示例：**

```bash
curl "http://127.0.0.1:19350/option/chain_query?underlying=NVDA&date=2025-01-06&type=C&strike_min=130&strike_max=140&expiry_max=2025-02-21"
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

排序顺序：`expiry, strike`。

---

### GET /rates/query

查询美国国债收益率。

**参数：**

| Param | 必填 | 格式 | 示例 |
|---|---|---|---|
| `start` | 是 | `YYYY-MM-DD` | `2025-01-02` |
| `end` | 是 | `YYYY-MM-DD` | `2025-01-31` |
| `tenors` | 否 | 逗号分隔 | `1M,10Y`（默认：全部） |

**支持的期限：** `1M`、`3M`、`1Y`、`2Y`、`5Y`、`10Y`、`30Y`

**示例：**

```bash
curl "http://127.0.0.1:19350/rates/query?start=2025-01-02&end=2025-01-10&tenors=1M,10Y"
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

排序顺序：`date`。仅返回源数据中存在的日期（不做前向填充）。

---

## 错误处理

所有校验错误均返回 HTTP 400：

```json
{
  "code": "invalid_argument",
  "message": "limit must be between 1 and 100000"
}
```

内部错误返回 HTTP 500：

```json
{
  "code": "internal_error",
  "message": "duckdb error: ..."
}
```

**常见校验规则：**

| 规则 | 详情 |
|---|---|
| `tickers` 为空 | 返回 400 |
| 日期格式无效 | 返回 400；日期使用 `YYYY-MM-DD`，日期时间使用 `YYYY-MM-DDTHH:MM:SS` |
| 未知字段名 | 返回 400 |
| `limit` 超出范围 | 必须为 1–100000 |
| `resolution` 无效 | 必须为 `day` 或 `minute` |
| `type` 无效 | 必须为 `C` 或 `P`（不区分大小写） |
| OPRA 合约错误 | 必须匹配 `O:{TICKER}{YYMMDD}{C|P}{8-digit strike}` |

---

## Agent 集成指南

本节面向调用 UPQ API 的 AI agent（LLM 工具调用、自动化流水线）。

### 构造请求

所有端点均使用 GET 和查询参数。请对参数值进行 URL 编码。

```python
import requests

BASE = "http://127.0.0.1:19350"

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

### 解析时间戳

`window_start` 为自 Unix 纪元起的纳秒数。转换为 datetime：

```python
from datetime import datetime, timezone

ns = 1736155800000000000
dt = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
# 2025-01-06 09:30:00+00:00
```

### 构建 OPRA 合约 ID

以编程方式构造 OPRA 合约字符串：

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

### 工作流：先获取期权链再查询合约

一种常见模式是先通过链查询发现合约，然后获取详细数据：

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

### Agent 最佳实践

1. **使用 `fields` 限制列** —— 减小响应大小并加快查询。
2. **遵守 `/stock` 上 10 万行的限制** —— 若触及上限，请缩小日期范围或减少 ticker 数量。
3. **检查 HTTP 状态码** —— 400 表示输入错误（请修正请求），500 表示服务端问题（重试或上报）。
4. **日期格式很重要** —— minute 端点需要 `YYYY-MM-DDTHH:MM:SS`，daily/chain/rates 需要 `YYYY-MM-DD`。混用会返回 400。
5. **利率不做前向填充** —— 缺失日期（周末、节假日）在结果中直接不存在。
6. **`type` 筛选不区分大小写** —— `C` 和 `c` 都可用于看涨期权。
7. **空结果是有效的** —— HTTP 200 且为空 `[]` 表示该查询没有数据，而非错误。
