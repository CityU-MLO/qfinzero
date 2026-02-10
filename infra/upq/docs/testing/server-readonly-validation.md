# Server Read-Only Validation

Date: 2026-02-10  
Host: `qlib`

## Command
```bash
./scripts/validate_server_readonly.sh qlib
```

## Results

### Paths
- `stock_path=ok`
- `options_path=ok`
- `rates_path=ok`

### File counts
- `stock_day_csv_gz=1003`
- `stock_minute_csv_gz=1003`
- `option_day_csv_gz=543`
- `option_minute_csv_gz=543`

### Python baseline routes (`rest_endpoint.py`)
- `/health`
- `/collect/tickers`
- `/collect/trading_days`
- `/query/stock_price`
- `/query/option_price`
- `/query/rates`
- `/query/chain`

### Python baseline health
- `health=unreachable` on `http://127.0.0.1:8000/health`

## Conclusion
- Server data paths and file inventory are validated in read-only mode.
- Python baseline API process is not currently reachable on the default port, so direct runtime parity calls were not executed in this run.
