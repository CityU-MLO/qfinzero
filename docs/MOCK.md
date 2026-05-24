# QFinZero Mock API 配置

本文档包含 QFinZero 三个服务在 Apifox 的 Mock API 配置信息，供前端开发和其他 Agent 使用。

## 项目信息

| 服务 | 项目 ID | 说明 |
|------|---------|------|
| UPQ | 7841779 | Unified Price Query (价格查询服务) |
| ESP | 7841780 | News Pushing Pipeline (新闻事件服务) |
| PMB | 7841781 | Paper Money Broker (模拟交易服务) |

团队 ID: `3671673`

---

## UPQ - 价格查询服务

### Mock 配置
```
云端 Mock 前置 URL: https://m1.apifoxmock.com/m1/7841779-7590489-default
Token: ZOHwp5_uZLuaiLLASy_oe
```

### 接口列表
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/health/freshness` | 数据新鲜度 |
| GET | `/stock` | 股票分钟数据 |
| GET | `/stock/daily` | 股票日K数据 |
| GET | `/option` | 期权元数据 |
| GET | `/option/ticker_query` | 期权合约查询 |
| GET | `/option/chain_query` | 期权链查询 |
| GET | `/rates/query` | 国债收益率查询 |

### 使用示例
```bash
# 健康检查
curl "https://m1.apifoxmock.com/m1/7841779-7590489-default/health?apifoxToken=ZOHwp5_uZLuaiLLASy_oe"

# 查询股票日K
curl "https://m1.apifoxmock.com/m1/7841779-7590489-default/stock/daily?tickers=AAPL&start=2025-01-01&end=2025-01-10&apifoxToken=ZOHwp5_uZLuaiLLASy_oe"

# 查询国债收益率
curl "https://m1.apifoxmock.com/m1/7841779-7590489-default/rates/query?start=2025-01-01&end=2025-01-10&apifoxToken=ZOHwp5_uZLuaiLLASy_oe"
```

---

## ESP - 新闻事件服务

### Mock 配置
```
云端 Mock 前置 URL: https://m1.apifoxmock.com/m1/7841780-7590490-default
Token: v5Y_OQpiEusEy9_viqRx-
```

### 接口列表
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/esp/health` | 健康检查 |
| GET | `/esp/health/freshness` | 数据新鲜度 |
| POST | `/esp/events/query` | 统一事件查询 |
| GET | `/esp/events/{event_id}` | 获取单个事件 |
| POST | `/esp/events/stream` | 增量事件轮询 |
| POST | `/esp/triggers/next` | 获取即将到来的触发事件 |
| POST | `/esp/calendar/econ` | 经济日历 |
| POST | `/esp/calendar/earnings` | 财报日历 |
| GET | `/esp/calendar/coverage` | 日历数据覆盖统计 |
| GET | `/esp/news/{news_id}/body` | 获取完整新闻文章 |
| POST | `/esp/news/search` | 搜索新闻 |
| GET | `/esp/news/stats` | 新闻统计 |
| GET | `/esp/news/export` | 导出新闻 |
| GET | `/esp/calendar/earnings/export` | 导出财报数据 |
| GET | `/esp/calendar/economic/export` | 导出经济数据 |
| POST | `/esp/timeline` | 事件时间线 |
| GET | `/esp/admin/sanity` | 数据质量检查 |

### 使用示例
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

## PMB - 模拟交易服务

### Mock 配置
```
云端 Mock 前置 URL: https://m1.apifoxmock.com/m1/7841781-7590491-default
Token: WeT8ftd3Botqhc9L80xsC
```

### 接口列表
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/accounts` | 创建交易账户 |
| GET | `/accounts/{account_id}` | 获取账户快照 |
| POST | `/sessions` | 创建回话会话 |
| POST | `/sessions/{session_id}/step` | 推进模拟时钟 |
| GET | `/sessions/{session_id}/summary` | 获取会话性能摘要 |
| POST | `/orders` | 下单 |
| POST | `/orders/{order_id}/cancel` | 撤单 |

### 使用示例
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

## Token 使用说明

Apifox Token 有三种使用方式：

### 方式一：Query 参数
```
https://m1.apifoxmock.com/m1/{project-id}/path?apifoxToken={token}
```

### 方式二：Header 参数
```
Header: apifoxToken: {token}
```

### 方式三：Body 参数（仅支持 form-data 和 x-www-form-urlencoded）
```
apifoxToken={token}
```

---

## 前端配置示例

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

## 注意事项

1. **Mock 数据特性**：
   - 返回的数据结构和类型符合 OpenAPI Schema 定义
   - 字符串字段为随机生成的 Latin 文本
   - 数值字段为随机数值
   - 枚举字段为有效枚举值

2. **路径冲突已解决**：
   - 每个服务独立项目，不再有 `/health` 路径冲突
   - PMB 服务的 `/v1` 前缀已去除

3. **数据格式**：
   - 日期格式：`YYYY-MM-DD`
   - 时间格式：`YYYY-MM-DDTHH:MM:SS`
   - 时间戳：`window_start` 为数值型（纳秒）

---

## 相关文档

- [UPQ API 文档](./upq/README.md)
- [ESP API 文档](./esp/README.md)
- [PMB API 文档](./pmb/README.md)
- [UPQ OpenAPI](./upq/openapi.yaml)
- [ESP OpenAPI](./esp/openapi.yaml)
- [PMB OpenAPI](./pmb/openapi.yaml)
