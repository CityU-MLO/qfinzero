> **English** (below) · [中文](#中文文档) (在下方)

# PMB Demos

Trading strategy demos for the Paper Money Broker. Two versions of each demo: raw HTTP API calls and PMBClient-based.

## Prerequisites

1. **UPQ** running (port 19350) with market data
2. **PMB** running (port 19380)

```bash
# Terminal 1: UPQ
cd infra/upq && STORAGE_ROOT=~/upq_storage cargo run -p upq-service

# Terminal 2: PMB
cd infra/pmb && python main.py
```

## Demos

### Client-based (recommended)

Uses `PMBClient` from `clients/pmb/`. Cleaner, shorter, handles errors.

```bash
cd qfinzero  # run from project root

python demos/pmb/client_demos/daily_buy_close.py      # Daily AAPL accumulation
python demos/pmb/client_demos/intraday_5min_signal.py  # 5-min mean reversion
python demos/pmb/client_demos/covered_call.py          # NVDA covered call
```

### Raw API (reference)

Direct `requests` calls showing exactly what HTTP requests are made. Useful for understanding the API or porting to other languages.

```bash
cd infra/pmb  # run from pmb directory

python demos/pmb/api_raw/daily_buy_close.py
python demos/pmb/api_raw/intraday_5min_signal.py
python demos/pmb/api_raw/covered_call.py
python demos/pmb/api_raw/run_all.py                    # run all three
```

## Structure

```
demos/pmb/
├── README.md                              # This file
├── result_saver.py                        # Shared result saving utility
├── client_demos/                          # Client-based demos
│   ├── daily_buy_close.py
│   ├── intraday_5min_signal.py
│   └── covered_call.py
└── api_raw/                               # Raw HTTP API demos
    ├── README.md                          # Detailed API demo docs
    ├── daily_buy_close.py
    ├── intraday_5min_signal.py
    ├── covered_call.py
    └── run_all.py
```

## Strategies

| Demo | Symbol | Frequency | Description |
|------|--------|-----------|-------------|
| Daily Buy-at-Close | AAPL | Daily | Buy 10 shares every day for 1 month |
| 5-Min Mean Reversion | AAPL | Minute | Buy on dips, sell on rips (intraday) |
| Covered Call | NVDA | Daily | Buy stock + sell OTM calls bi-weekly (3 months) |

---

<a id="中文文档"></a>

# 中文文档

# PMB 演示

Paper Money Broker（模拟资金券商）的交易策略演示。每个演示都有两个版本：原始 HTTP API 调用和基于 PMBClient 的版本。

## 前置条件

1. **UPQ** 正在运行（端口 19350）且包含市场数据
2. **PMB** 正在运行（端口 19380）

```bash
# Terminal 1: UPQ
cd infra/upq && STORAGE_ROOT=~/upq_storage cargo run -p upq-service

# Terminal 2: PMB
cd infra/pmb && python main.py
```

## 演示

### 基于客户端（推荐）

使用来自 `clients/pmb/` 的 `PMBClient`。更简洁、更短，并能处理错误。

```bash
cd qfinzero  # run from project root

python demos/pmb/client_demos/daily_buy_close.py      # Daily AAPL accumulation
python demos/pmb/client_demos/intraday_5min_signal.py  # 5-min mean reversion
python demos/pmb/client_demos/covered_call.py          # NVDA covered call
```

### 原始 API（参考）

直接的 `requests` 调用，精确展示所发出的 HTTP 请求。有助于理解 API 或移植到其他语言。

```bash
cd infra/pmb  # run from pmb directory

python demos/pmb/api_raw/daily_buy_close.py
python demos/pmb/api_raw/intraday_5min_signal.py
python demos/pmb/api_raw/covered_call.py
python demos/pmb/api_raw/run_all.py                    # run all three
```

## 结构

```
demos/pmb/
├── README.md                              # This file
├── result_saver.py                        # Shared result saving utility
├── client_demos/                          # Client-based demos
│   ├── daily_buy_close.py
│   ├── intraday_5min_signal.py
│   └── covered_call.py
└── api_raw/                               # Raw HTTP API demos
    ├── README.md                          # Detailed API demo docs
    ├── daily_buy_close.py
    ├── intraday_5min_signal.py
    ├── covered_call.py
    └── run_all.py
```

## 策略

| 演示 | 标的 | 频率 | 说明 |
|------|--------|-----------|-------------|
| Daily Buy-at-Close | AAPL | 每日 | 每天买入 10 股，持续 1 个月 |
| 5-Min Mean Reversion | AAPL | 分钟 | 逢跌买入、逢涨卖出（日内） |
| Covered Call | NVDA | 每日 | 买入股票 + 每两周卖出价外看涨期权（3 个月） |
