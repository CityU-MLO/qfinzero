> English: [../../../../../infra/pmb/demos/README.md](../../../../../infra/pmb/demos/README.md)

# PMB 交易策略演示

三个全面的演示，展示使用 Paper Money Broker（模拟资金券商）的不同交易策略。

## 前置条件

1. **UPQ 服务正在运行**（端口 19350）
   ```bash
   cd infra/upq
   cargo run -p upq-service
   ```

2. **PMB 服务正在运行**（端口 19380）
   ```bash
   cd infra/pmb
   python main.py
   ```

3. **市场数据**：确保 UPQ 拥有所需数据：
   - 演示 1：AAPL 2025 年 1 月的每日 K 线
   - 演示 2：AAPL 2025-01-06 的分钟 K 线
   - 演示 3：NVDA 2025 年 1 月的股票 + 期权数据

---

## 演示 1：每日收盘买入（Daily Buy-at-Close）

**策略**：在每个交易日的收盘时买入 10 股 AAPL，持续一个月。

**特性**：
- 每日频率（1d）
- 简单的累积策略
- 演示每日 K 线回放

**运行**：
```bash
python demos/daily_buy_close.py
```

**输出示例**：
```
Day | Date       | Price    | Shares |   Cash     |  Equity
  1 | 2025-01-06 | $182.50 |     10 | $48,175.00 | $48,825.00
  2 | 2025-01-07 | $183.20 |     10 | $46,342.00 | $48,664.00
...
```

**保存的结果**：
- `results/daily_buy_close_YYYYMMDD_HHMMSS/`
  - `summary.json` - 会话指标
  - `holdings.json` & `holdings.csv` - 最终持仓
  - `operations.json`、`orders.csv`、`trades.csv` - 所有订单/成交
  - `equity_curve.json` & `equity_curve.csv` - 随时间变化的权益
  - `report.txt` - 人类可读的摘要

---

## 演示 2：日内 5 分钟均值回归（Intraday 5-Minute Mean Reversion）

**策略**：
- 每 5 分钟，检查价格相对 5 分钟前是上涨还是下跌
- 如果下跌 → 买入 5 股（预期回归）
- 如果上涨 → 卖出 5 股（如有持仓则获利了结）

**特性**：
- 分钟频率（1m）
- 简单的均值回归信号
- 演示高频交易

**运行**：
```bash
python demos/intraday_5min_signal.py
```

**输出示例**：
```
Time   | Price    | Signal   | Action     | Pos  |   Cash     |  Equity
09:35  | $182.50 |   DOWN   |  BUY 5     |    5 | $24,087.50 | $24,912.50
09:40  | $183.00 |    UP    |  SELL 5    |    0 | $25,002.50 | $25,002.50
...
```

**保存的结果**：
- `results/intraday_5min_signal_YYYYMMDD_HHMMSS/`
  - 与演示 1 结构相同
  - 带时间戳的成交日志

---

## 演示 3：备兑看涨期权（Covered Call with Options）

**策略**：
- 第 1 天：买入 100 股 NVDA（整手）
- 第 1 天：卖出 1 张价外 10% 的看涨期权（备兑看涨）
- 每日监控持仓

**特性**：
- 期权交易（OPRA 合约）
- 卖出期权的保证金要求
- 演示复杂的多资产持仓

**运行**：
```bash
python demos/covered_call.py
```

**输出示例**：
```
Date       |   NVDA   |  Call    | Stock Pos | Option Pos |  Equity
2025-01-06 | $136.50 |  $3.20  |      100  |        -1  | $100,320.00
2025-01-07 | $138.20 |  $4.50  |      100  |        -1  | $100,170.00
...
```

**保存的结果**：
- `results/covered_call_YYYYMMDD_HHMMSS/`
  - 与演示 1 结构相同
  - 带保证金细节的账户状态

---

## 结果结构

每个演示都会在 `results/` 下创建一个带时间戳的文件夹，其中包含：

### 生成的文件

1. **summary.json** - 来自 PMB 的会话指标
   ```json
   {
     "session_id": "sess_abc123",
     "final_equity": 101234.5,
     "total_return": 0.012345,
     "max_drawdown": 0.0231,
     "fees_paid": 12.34,
     "num_orders": 120,
     "num_trades": 98
   }
   ```

2. **holdings.json/csv** - 最终持仓
   ```csv
   instrument_id,qty,avg_price,mark_price,unrealized_pnl,realized_pnl
   STOCK:AAPL,200,182.45,185.20,550.00,0.0
   ```

3. **operations.json** - 所有订单和成交
   - `orders`：完整的订单生命周期
   - `trades`：所有成交，含价格/费用

4. **orders.csv** - 订单历史（便于电子表格处理）

5. **trades.csv** - 成交历史（便于电子表格处理）

6. **equity_curve.json/csv** - 随时间变化的权益
   ```csv
   timestamp,equity
   2025-01-06T09:31:00-05:00,100125.50
   2025-01-06T09:32:00-05:00,100250.75
   ```

7. **report.txt** - 含所有关键指标的文本摘要

---

## 分析结果

### Excel / 电子表格
将 CSV 文件直接加载到 Excel/Google Sheets 中进行分析。

### Python 分析
```python
import json
import pandas as pd

# Load equity curve
df = pd.read_csv("results/daily_buy_close_20260216_221530/equity_curve.csv")
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.plot(x='timestamp', y='equity', title='Equity Curve')

# Load trades
trades = pd.read_csv("results/daily_buy_close_20260216_221530/trades.csv")
print(f"Total trades: {len(trades)}")
print(f"Total fees: ${trades['fees'].sum():.2f}")

# Load summary
with open("results/daily_buy_close_20260216_221530/summary.json") as f:
    summary = json.load(f)
print(f"Total return: {summary['total_return']*100:.2f}%")
print(f"Max drawdown: {summary['max_drawdown']*100:.2f}%")
```

---

## 故障排查

**"UPQ_NOT_RUNNING"**：
- 先启动 UPQ 服务
- 验证端口 19350 是否可访问：`curl http://127.0.0.1:19350/health`

**"session not found"**：
- 确保 PMB 服务正在运行
- 检查端口 19380：`curl http://127.0.0.1:19380/v1/health`

**"invalid_argument: limit_price required"**：
- 检查订单类型是否匹配所需字段
- LIMIT 订单需要 `limit_price`，STOP 订单需要 `stop_price`

**结果为空**：
- 验证 UPQ 拥有所请求标的和日期范围的数据
- 检查 UPQ 日志中的数据可用性

---

## 后续步骤

1. **修改策略**：编辑演示文件以测试你自己的逻辑
2. **添加新标的**：在创建会话时修改 `universe.stocks`
3. **尝试不同的时间粒度**：调整 `start_ts`/`end_ts` 和 `frequency`
4. **组合策略**：创建多策略组合
5. **添加风险管理**：实现止损、仓位管理

如需 API 参考，请参见 `infra/pmb/docs/api-usage.md`（待创建）或计划文档。
