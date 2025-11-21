# OQL (Options Query Language) — Refactored Package

This package provides a small DSL and an execution engine to query option strategies
like vertical spreads, calendar spreads, and straddles, using a SQL-like syntax.

## Features
- Modular structure: parsing, executor, strategy packages.
- Robust parser: strips `--` comments, supports multi-column `ORDER BY`,
  and operators: `>`, `<`, `=`, `>=`, `<=`, `!=`, `~` (approx).
- Role-aware leg filters in `WHERE`: `L`, `S`, `F`, `B`, `C`, `P`.
- Moneyness shortcuts: `ITM`, `ATM`, `OTM` with a small tolerance window.
- Net Greeks calculation (including `rho` if present).
- Case-insensitive, multi-key ordering (works with suffixed columns like `price_L`).

## Requirements
- Python 3.9+
- `pandas`, `requests`

```
pip install -r requirements.txt
```

## Usage

Run demo queries:
```
python engine.py --demo --date 2025-06-10
```

Run a custom query:
```
python engine.py -q "SELECT STRADDLE FROM NVDA WHERE C.Moneyness = ATM AND C.Dte ~ 30 AND P.Dte ~ 30 ORDER BY net_vega DESC LIMIT 5" -d 2025-06-10
```

Query grammar (simplified):
```
SELECT <STRATEGY>
FROM   <TICKER>
[WHERE <Role.Field OP Value> [AND ...]]
[HAVING <Field OP Value> [AND ...]]
[ORDER BY <col> [ASC|DESC] [, <col> [ASC|DESC] ...]]
[LIMIT <N>]
```

Where roles depend on the strategy:
- Vertical spreads: `L` (long), `S` (short)
- Calendar: `F` (front/short), `B` (back/long)
- Straddle: `C` (call), `P` (put)

Approx operator `~` uses `±5` days tolerance for `dte` and `±10%` for other numeric fields.
Moneyness categories:
- Calls: `ITM` (ratio > 1.01), `ATM` (0.98–1.02), `OTM` (ratio < 0.99)
- Puts : `ITM` (ratio < 0.99), `ATM` (0.98–1.02), `OTM` (ratio > 1.01)
The ratio is defined as `spot / strike`.
