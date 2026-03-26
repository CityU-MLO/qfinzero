# UPQ Demos

Demos for querying stock, option, and treasury rate data via `UPQClient`.

## Prerequisites

UPQ service running with data loaded:

```bash
cd infra/upq
STORAGE_ROOT=~/upq_storage cargo run -p upq-service
# Verify: curl http://127.0.0.1:19703/health
```

## Demos

```bash
cd qfinzero  # run from project root

python demos/upq/stock_query.py    # Daily + minute stock bars
python demos/upq/option_query.py   # Option chain + contract queries
python demos/upq/rates_query.py    # Treasury yield curve data
```

### stock_query.py

- Fetch daily OHLCV for AAPL & MSFT
- Select specific fields to reduce payload
- Fetch minute-level intraday bars
- Convert nanosecond timestamps to datetime

### option_query.py

- Query option chain with strike/expiry/type filters
- Build OPRA contract IDs with `UPQClient.make_opra()`
- Fetch daily and minute bars for a specific contract
- Chain discovery → contract detail workflow

### rates_query.py

- Fetch full yield curve (all tenors)
- Filter specific tenors (1M, 10Y)
- Compute yield spread

## Structure

```
demos/upq/
├── README.md           # This file
├── stock_query.py      # Stock price queries
├── option_query.py     # Option chain + contract queries
└── rates_query.py      # Treasury yield queries
```
