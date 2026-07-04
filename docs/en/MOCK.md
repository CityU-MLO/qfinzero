> 中文: [../cn/MOCK.md](../cn/MOCK.md)

# QFinZero Mock API Configuration

This document contains the Apifox Mock API configuration for the three QFinZero services, for use by frontend development and other agents.

## Project Info

| Service | Project ID | Description |
|------|---------|------|
| UPQ | 7841779 | Unified Price Query (price query service) |
| ESP | 7841780 | News Pushing Pipeline (news & event service) |
| PMB | 7841781 | Paper Money Broker (paper trading service) |

Team ID: `3671673`

---

## UPQ - Price Query Service

### Mock Configuration
```
云端 Mock 前置 URL: https://m1.apifoxmock.com/m1/7841779-7590489-default
Token: ZOHwp5_uZLuaiLLASy_oe
```

### Endpoint List
| Method | Path | Description |
|------|------|------|
| GET | `/health` | Health check |
| GET | `/health/freshness` | Data freshness |
| GET | `/stock` | Stock minute data |
| GET | `/stock/daily` | Stock daily K data |
| GET | `/option` | Option metadata |
| GET | `/option/ticker_query` | Option contract query |
| GET | `/option/chain_query` | Option chain query |
| GET | `/rates/query` | Treasury yield query |

### Usage Examples
```bash
# 健康检查
curl "https://m1.apifoxmock.com/m1/7841779-7590489-default/health?apifoxToken=ZOHwp5_uZLuaiLLASy_oe"

# 查询股票日K
curl "https://m1.apifoxmock.com/m1/7841779-7590489-default/stock/daily?tickers=AAPL&start=2025-01-01&end=2025-01-10&apifoxToken=ZOHwp5_uZLuaiLLASy_oe"

# 查询国债收益率
curl "https://m1.apifoxmock.com/m1/7841779-7590489-default/rates/query?start=2025-01-01&end=2025-01-10&apifoxToken=ZOHwp5_uZLuaiLLASy_oe"
```

---

## ESP - News & Event Service

### Mock Configuration
```
云端 Mock 前置 URL: https://m1.apifoxmock.com/m1/7841780-7590490-default
Token: v5Y_OQpiEusEy9_viqRx-
```

### Endpoint List
| Method | Path | Description |
|------|------|------|
| GET | `/esp/health` | Health check |
| GET | `/esp/health/freshness` | Data freshness |
| POST | `/esp/events/query` | Unified event query |
| GET | `/esp/events/{event_id}` | Get a single event |
| POST | `/esp/events/stream` | Incremental event polling |
| POST | `/esp/triggers/next` | Get upcoming trigger events |
| POST | `/esp/calendar/econ` | Economic calendar |
| POST | `/esp/calendar/earnings` | Earnings calendar |
| GET | `/esp/calendar/coverage` | Calendar data coverage stats |
| GET | `/esp/news/{news_id}/body` | Get full news article |
| POST | `/esp/news/search` | Search news |
| GET | `/esp/news/stats` | News statistics |
| GET | `/esp/news/export` | Export news |
| GET | `/esp/calendar/earnings/export` | Export earnings data |
| GET | `/esp/calendar/economic/export` | Export economic data |
| POST | `/esp/timeline` | Event timeline |
| GET | `/esp/admin/sanity` | Data quality check |

### Usage Examples
```bash
# 健康检查
curl "https://m1.apifoxmock.com/m1/7841780-7590490-default/esp/health?apifoxToken=v5Y_OQpiEusEy9_viqRx-"

# 查询即将到来的事件
curl -X POST "https://m1.apifoxmock.com/m1/7841780-7590490-default/esp/events/query?apifoxToken=v5Y_OQpiEusEy9_viqRx-" \
  -H "Content-Type: application/json" \
  -d '{"mode": "upcoming", "horizon_minutes": 120}'

# 获取触发事件
curl -X POST "https://m1.apifoxmock.com/m1/7841780-7590490-default/esp/triggers/next?apifoxToken=v5Y_OQpiEusEy9_viqRx-" \
  -H "Content-Type: application/json" \
  -d '{"tickers": ["AAPL"], "min_importance": "high"}'
```

---

## PMB - Paper Trading Service

### Mock Configuration
```
云端 Mock 前置 URL: https://m1.apifoxmock.com/m1/7841781-7590491-default
Token: WeT8ftd3Botqhc9L80xsC
```

### Endpoint List
| Method | Path | Description |
|------|------|------|
| GET | `/health` | Health check |
| POST | `/accounts` | Create trading account |
| GET | `/accounts/{account_id}` | Get account snapshot |
| POST | `/sessions` | Create replay session |
| POST | `/sessions/{session_id}/step` | Advance simulation clock |
| GET | `/sessions/{session_id}/summary` | Get session performance summary |
| POST | `/orders` | Place order |
| POST | `/orders/{order_id}/cancel` | Cancel order |

### Usage Examples
```bash
# 健康检查
curl "https://m1.apifoxmock.com/m1/7841781-7590491-default/health?apifoxToken=WeT8ftd3Botqhc9L80xsC"

# 创建账户
curl -X POST "https://m1.apifoxmock.com/m1/7841781-7590491-default/accounts?apifoxToken=WeT8ftd3Botqhc9L80xsC" \
  -H "Content-Type: application/json" \
  -d '{"initial_cash": 100000, "start_date": "2025-01-06", "account_type": "MARGIN"}'

# 创建会话
curl -X POST "https://m1.apifoxmock.com/m1/7841781-7590491-default/sessions?apifoxToken=WeT8ftd3Botqhc9L80xsC" \
  -H "Content-Type: application/json" \
  -d '{"account_id": "acc_123", "frequency": "1d", "start_ts": "2025-01-06", "end_ts": "2025-01-31", "universe": {"stocks": ["AAPL"]}}'

# 下单
curl -X POST "https://m1.apifoxmock.com/m1/7841781-7590491-default/orders?apifoxToken=WeT8ftd3Botqhc9L80xsC" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "sess_123",
    "account_id": "acc_123",
    "client_order_id": "order_001",
    "order": {
      "instrument": {"type": "STOCK", "symbol": "AAPL"},
      "side": "BUY",
      "order_type": "MARKET",
      "qty": 100,
      "time_in_force": "DAY"
    }
  }'
```

---

## Token Usage

The Apifox Token can be used in three ways:

### Method 1: Query Parameter
```
https://m1.apifoxmock.com/m1/{project-id}/path?apifoxToken={token}
```

### Method 2: Header Parameter
```
Header: apifoxToken: {token}
```

### Method 3: Body Parameter (only form-data and x-www-form-urlencoded supported)
```
apifoxToken={token}
```

---

## Frontend Configuration Examples

### JavaScript/Fetch
```javascript
const UPQ_BASE = 'https://m1.apifoxmock.com/m1/7841779-7590489-default';
const UPQ_TOKEN = 'ZOHwp5_uZLuaiLLASy_oe';

// 查询股票数据
fetch(`${UPQ_BASE}/stock/daily?tickers=AAPL&start=2025-01-01&end=2025-01-10&apifoxToken=${UPQ_TOKEN}`)
  .then(res => res.json())
  .then(data => console.log(data));
```

### Python
```python
import requests

UPQ_BASE = "https://m1.apifoxmock.com/m1/7841779-7590489-default"
UPQ_TOKEN = "ZOHwp5_uZLuaiLLASy_oe"

# 查询股票数据
response = requests.get(
    f"{UPQ_BASE}/stock/daily",
    params={
        "tickers": "AAPL",
        "start": "2025-01-01",
        "end": "2025-01-10",
        "apifoxToken": UPQ_TOKEN
    }
)
data = response.json()
```

---

## Notes

1. **Mock data characteristics**:
   - The returned data structure and types conform to the OpenAPI Schema definitions
   - String fields are randomly generated Latin text
   - Numeric fields are random numeric values
   - Enum fields are valid enum values

2. **Path conflicts resolved**:
   - Each service is an independent project; there is no longer a `/health` path conflict
   - The `/v1` prefix of the PMB service has been removed

3. **Data formats**:
   - Date format: `YYYY-MM-DD`
   - Time format: `YYYY-MM-DDTHH:MM:SS`
   - Timestamp: `window_start` is numeric (nanoseconds)

---

## Related Documents

- [UPQ API 文档](./upq/README.md)
- [ESP API 文档](./esp/README.md)
- [PMB API 文档](./pmb/README.md)
- [UPQ OpenAPI](./upq/openapi.yaml)
- [ESP OpenAPI](./esp/openapi.yaml)
- [PMB OpenAPI](./pmb/openapi.yaml)
