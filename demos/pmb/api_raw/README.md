# PMB Trading Strategy Demos

Three comprehensive demos showcasing different trading strategies using the Paper Money Broker.

## Prerequisites

1. **UPQ Service Running** (port 23333)
   ```bash
   cd infra/upq
   cargo run -p upq-service
   ```

2. **PMB Service Running** (port 19320)
   ```bash
   cd infra/pmb
   python main.py
   ```

3. **Market Data**: Ensure UPQ has the required data:
   - Demo 1: AAPL daily bars for January 2025
   - Demo 2: AAPL minute bars for 2025-01-06
   - Demo 3: NVDA stock + option data for Jan 2025

---

## Demo 1: Daily Buy-at-Close

**Strategy**: Buy 10 shares of AAPL at market close every trading day for one month.

**Features**:
- Daily frequency (1d)
- Simple accumulation strategy
- Demonstrates daily bar replay

**Run**:
```bash
python demos/daily_buy_close.py
```

**Output Example**:
```
Day | Date       | Price    | Shares |   Cash     |  Equity
  1 | 2025-01-06 | $182.50 |     10 | $48,175.00 | $48,825.00
  2 | 2025-01-07 | $183.20 |     10 | $46,342.00 | $48,664.00
...
```

**Results Saved**:
- `results/daily_buy_close_YYYYMMDD_HHMMSS/`
  - `summary.json` - session metrics
  - `holdings.json` & `holdings.csv` - final positions
  - `operations.json`, `orders.csv`, `trades.csv` - all orders/trades
  - `equity_curve.json` & `equity_curve.csv` - equity over time
  - `report.txt` - human-readable summary

---

## Demo 2: Intraday 5-Minute Mean Reversion

**Strategy**:
- Every 5 minutes, check if price is up or down from 5 minutes ago
- If DOWN → BUY 5 shares (expect reversion)
- If UP → SELL 5 shares (take profit if holding)

**Features**:
- Minute frequency (1m)
- Simple mean reversion signal
- Demonstrates high-frequency trading

**Run**:
```bash
python demos/intraday_5min_signal.py
```

**Output Example**:
```
Time   | Price    | Signal   | Action     | Pos  |   Cash     |  Equity
09:35  | $182.50 |   DOWN   |  BUY 5     |    5 | $24,087.50 | $24,912.50
09:40  | $183.00 |    UP    |  SELL 5    |    0 | $25,002.50 | $25,002.50
...
```

**Results Saved**:
- `results/intraday_5min_signal_YYYYMMDD_HHMMSS/`
  - Same structure as Demo 1
  - Trade log with timestamps

---

## Demo 3: Covered Call with Options

**Strategy**:
- Day 1: Buy 100 shares of NVDA (round lot)
- Day 1: Sell 1 call option 10% OTM (covered call)
- Daily monitoring of position

**Features**:
- Option trading (OPRA contracts)
- Margin requirements for short options
- Demonstrates complex multi-asset positions

**Run**:
```bash
python demos/covered_call.py
```

**Output Example**:
```
Date       |   NVDA   |  Call    | Stock Pos | Option Pos |  Equity
2025-01-06 | $136.50 |  $3.20  |      100  |        -1  | $100,320.00
2025-01-07 | $138.20 |  $4.50  |      100  |        -1  | $100,170.00
...
```

**Results Saved**:
- `results/covered_call_YYYYMMDD_HHMMSS/`
  - Same structure as Demo 1
  - Account state with margin details

---

## Results Structure

Each demo creates a timestamped folder under `results/` with:

### Files Generated

1. **summary.json** - Session metrics from PMB
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

2. **holdings.json/csv** - Final positions
   ```csv
   instrument_id,qty,avg_price,mark_price,unrealized_pnl,realized_pnl
   STOCK:AAPL,200,182.45,185.20,550.00,0.0
   ```

3. **operations.json** - All orders and trades
   - `orders`: full order lifecycle
   - `trades`: all executions with prices/fees

4. **orders.csv** - Order history (spreadsheet-friendly)

5. **trades.csv** - Trade history (spreadsheet-friendly)

6. **equity_curve.json/csv** - Equity over time
   ```csv
   timestamp,equity
   2025-01-06T09:31:00-05:00,100125.50
   2025-01-06T09:32:00-05:00,100250.75
   ```

7. **report.txt** - Text summary with all key metrics

---

## Analyzing Results

### Excel / Spreadsheet
Load the CSV files directly into Excel/Google Sheets for analysis.

### Python Analysis
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

## Troubleshooting

**"UPQ_NOT_RUNNING"**:
- Start UPQ service first
- Verify port 23333 is accessible: `curl http://127.0.0.1:23333/health`

**"session not found"**:
- Ensure PMB service is running
- Check port 19320: `curl http://127.0.0.1:19320/v1/health`

**"invalid_argument: limit_price required"**:
- Check order type matches required fields
- LIMIT orders need `limit_price`, STOP orders need `stop_price`

**Empty results**:
- Verify UPQ has data for the requested symbols and date range
- Check UPQ logs for data availability

---

## Next Steps

1. **Modify strategies**: Edit the demo files to test your own logic
2. **Add new symbols**: Change `universe.stocks` in session creation
3. **Try different timeframes**: Adjust `start_ts`/`end_ts` and `frequency`
4. **Combine strategies**: Create multi-strategy portfolios
5. **Add risk management**: Implement stop-losses, position sizing

For API reference, see `infra/pmb/docs/api-usage.md` (to be created) or the plan document.
