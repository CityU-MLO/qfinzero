# PMB Demos

Trading strategy demos for the Paper Money Broker. Two versions of each demo: raw HTTP API calls and PMBClient-based.

## Prerequisites

1. **UPQ** running (port 19703) with market data
2. **PMB** running (port 19701)

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
