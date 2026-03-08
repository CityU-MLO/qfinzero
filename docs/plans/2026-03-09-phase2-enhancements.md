# Phase 2 Enhancements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix four issues in the overlay strategy backtesting pipeline: (1) UPQ stock split adjustment so NVDA data is usable, (2) ETF benchmark total return (include dividends), (3) PMB put spread support, (4) delta constraint in overlay scripts.

**Architecture:** Split adjustments are applied on-read in UPQ via a static JSON config loaded at startup (mirrors the DividendCalendar pattern). ETF dividends are queried via a new UPQ `/dividends/query` endpoint. Put spreads use a lightweight SpreadOrder model in PMB with atomic two-leg execution and net-width margin. Delta constraint is pure script logic using UPQ greeks.

**Tech Stack:** Rust (UPQ — Axum, DuckDB, Parquet), Python (PMB — FastAPI, Pydantic), TDD throughout.

---

## Key Design Decisions

### Split Adjustment: On-Read with Static Config

We use a JSON config file (`storage/splits.json`) instead of deriving from dividend ratios because:
- Not all stocks that split have dividends (e.g. GOOGL class C)
- Explicit config is auditable and deterministic
- Matches the DividendCalendar pattern (loaded at startup, held in `AppState`)
- Only needs ~10 entries for US large-caps that split 2020-2025

The `SplitCalendar` adjusts historical OHLCV at query time:
```
For each row: if trade_date < split.effective_date:
  close = close / split.ratio
  open  = open  / split.ratio
  high  = high  / split.ratio
  low   = low   / split.ratio
  volume = volume * split.ratio  (integer)
```

Option strikes are NOT adjusted — this is industry standard (OPRA encodes the original strike).

### Dividend Query: New Public Endpoint

Currently dividends are internal-only (used for greeks). We expose a new `/dividends/query` endpoint so demo scripts can compute ETF total return. This is a thin SQL query over the existing `dividends.parquet`.

### Put Spread: Lightweight Atomic Execution

Rather than a full multi-leg order framework, we add a minimal `SpreadOrder` concept:
- A spread is two linked single-leg orders with a shared `spread_id`
- Both legs execute atomically in one tick (both fill or both reject)
- Margin = spread width × 100 × qty (not sum of individual legs)
- No new API endpoint — demo scripts call two `POST /v1/orders` with a shared `spread_id` field

### Delta Constraint: Script-Level Check

Before opening a new option position, the overlay script:
1. Queries current option greeks from UPQ (`include_greeks=true`)
2. Computes effective delta = stock_qty + Σ(option_delta × option_qty × 100)
3. Skips if adding the new position would exceed the initial stock position (10,000)

---

## Task 1: UPQ SplitCalendar — Data Structure & Loading

**Files:**
- Create: `infra/upq/crates/upq-service/src/splits.rs`
- Create: `infra/upq/storage/splits.json` (seed data)
- Modify: `infra/upq/crates/upq-service/src/app.rs:39-44` (add to AppState)
- Modify: `infra/upq/crates/upq-service/src/app.rs:144-173` (load at startup)
- Modify: `infra/upq/crates/upq-service/src/lib.rs` (add `pub mod splits;`)

**Step 1: Write splits.json seed data**

```json
{
  "splits": [
    {"ticker": "NVDA", "effective_date": "2024-06-10", "ratio": 10},
    {"ticker": "TSLA", "effective_date": "2022-08-25", "ratio": 3},
    {"ticker": "AMZN", "effective_date": "2022-06-06", "ratio": 20},
    {"ticker": "GOOGL", "effective_date": "2022-07-18", "ratio": 20},
    {"ticker": "GOOG", "effective_date": "2022-07-18", "ratio": 20},
    {"ticker": "SHOP", "effective_date": "2022-06-29", "ratio": 10}
  ]
}
```

**Step 2: Write failing test for SplitCalendar**

Create `infra/upq/crates/upq-service/tests/splits_tests.rs`:

```rust
use upq_service::splits::SplitCalendar;
use std::io::Write;
use tempfile::NamedTempFile;

#[test]
fn test_load_splits_json() -> Result<(), Box<dyn std::error::Error>> {
    let json = r#"{"splits":[
        {"ticker":"NVDA","effective_date":"2024-06-10","ratio":10},
        {"ticker":"TSLA","effective_date":"2022-08-25","ratio":3}
    ]}"#;
    let mut f = NamedTempFile::new()?;
    f.write_all(json.as_bytes())?;

    let cal = SplitCalendar::load(f.path())?;
    assert!(cal.has_splits("NVDA"));
    assert!(cal.has_splits("TSLA"));
    assert!(!cal.has_splits("AAPL"));
    Ok(())
}

#[test]
fn test_cumulative_factor_before_split() -> Result<(), Box<dyn std::error::Error>> {
    let json = r#"{"splits":[
        {"ticker":"NVDA","effective_date":"2024-06-10","ratio":10}
    ]}"#;
    let mut f = NamedTempFile::new()?;
    f.write_all(json.as_bytes())?;

    let cal = SplitCalendar::load(f.path())?;
    // Before split: price should be divided by 10
    let factor = cal.adjustment_factor("NVDA", "2024-06-07");
    assert!((factor - 0.1).abs() < 1e-9, "pre-split factor should be 0.1, got {}", factor);
    Ok(())
}

#[test]
fn test_cumulative_factor_after_split() -> Result<(), Box<dyn std::error::Error>> {
    let json = r#"{"splits":[
        {"ticker":"NVDA","effective_date":"2024-06-10","ratio":10}
    ]}"#;
    let mut f = NamedTempFile::new()?;
    f.write_all(json.as_bytes())?;

    let cal = SplitCalendar::load(f.path())?;
    // After split: no adjustment needed
    let factor = cal.adjustment_factor("NVDA", "2024-06-10");
    assert!((factor - 1.0).abs() < 1e-9, "post-split factor should be 1.0, got {}", factor);
    Ok(())
}

#[test]
fn test_no_splits_returns_factor_one() -> Result<(), Box<dyn std::error::Error>> {
    let json = r#"{"splits":[]}"#;
    let mut f = NamedTempFile::new()?;
    f.write_all(json.as_bytes())?;

    let cal = SplitCalendar::load(f.path())?;
    let factor = cal.adjustment_factor("AAPL", "2024-01-01");
    assert!((factor - 1.0).abs() < 1e-9);
    Ok(())
}

#[test]
fn test_adjust_ohlcv() -> Result<(), Box<dyn std::error::Error>> {
    let json = r#"{"splits":[
        {"ticker":"NVDA","effective_date":"2024-06-10","ratio":10}
    ]}"#;
    let mut f = NamedTempFile::new()?;
    f.write_all(json.as_bytes())?;

    let cal = SplitCalendar::load(f.path())?;
    let (o, h, l, c, v) = cal.adjust_ohlcv("NVDA", "2024-06-07", 1200.0, 1220.0, 1180.0, 1210.0, 5_000_000);
    assert!((c - 121.0).abs() < 0.01, "close should be 121.0, got {}", c);
    assert!((o - 120.0).abs() < 0.01);
    assert_eq!(v, 50_000_000, "volume should be 10x");
    Ok(())
}
```

**Step 3: Run test to verify it fails**

Run: `cd infra/upq && cargo test -p upq-service --test splits_tests`
Expected: FAIL — `unresolved import upq_service::splits`

**Step 4: Implement SplitCalendar**

Create `infra/upq/crates/upq-service/src/splits.rs`:

```rust
use std::collections::HashMap;
use std::path::Path;

use serde::Deserialize;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SplitError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Deserialize)]
struct SplitEntry {
    ticker: String,
    effective_date: String, // YYYY-MM-DD
    ratio: u32,             // e.g. 10 for 10:1
}

#[derive(Debug, Deserialize)]
struct SplitsFile {
    splits: Vec<SplitEntry>,
}

#[derive(Debug, Clone)]
struct SplitEvent {
    effective_date: String,
    ratio: u32,
}

/// Holds stock-split metadata and applies on-read price adjustments.
/// Splits are stored per-ticker sorted by effective_date descending
/// so we can iterate newest-first when computing cumulative factor.
#[derive(Debug)]
pub struct SplitCalendar {
    events: HashMap<String, Vec<SplitEvent>>,
}

impl SplitCalendar {
    pub fn empty() -> Self {
        Self {
            events: HashMap::new(),
        }
    }

    pub fn load(path: &Path) -> Result<Self, SplitError> {
        let content = std::fs::read_to_string(path)?;
        let file: SplitsFile = serde_json::from_str(&content)?;

        let mut events: HashMap<String, Vec<SplitEvent>> = HashMap::new();
        for entry in file.splits {
            events.entry(entry.ticker).or_default().push(SplitEvent {
                effective_date: entry.effective_date,
                ratio: entry.ratio,
            });
        }
        // Sort each ticker's splits by date ascending
        for v in events.values_mut() {
            v.sort_by(|a, b| a.effective_date.cmp(&b.effective_date));
        }

        Ok(Self { events })
    }

    pub fn has_splits(&self, ticker: &str) -> bool {
        self.events.get(ticker).is_some_and(|v| !v.is_empty())
    }

    /// Returns the price adjustment factor for a given trade_date.
    /// Factor < 1.0 means the price needs to be divided (pre-split data).
    /// Factor = 1.0 means no adjustment needed.
    ///
    /// For a 10:1 split on 2024-06-10:
    ///   trade_date < 2024-06-10 → factor = 1/10 = 0.1
    ///   trade_date >= 2024-06-10 → factor = 1.0
    pub fn adjustment_factor(&self, ticker: &str, trade_date: &str) -> f64 {
        let splits = match self.events.get(ticker) {
            Some(v) => v,
            None => return 1.0,
        };

        let mut factor = 1.0;
        // For each split that happens AFTER this trade_date,
        // the historical price needs to be divided by that split ratio.
        for split in splits {
            if trade_date < split.effective_date.as_str() {
                factor /= split.ratio as f64;
            }
        }
        factor
    }

    /// Adjust OHLCV values for a given trade_date.
    /// Returns (open, high, low, close, volume) adjusted.
    pub fn adjust_ohlcv(
        &self,
        ticker: &str,
        trade_date: &str,
        open: f64,
        high: f64,
        low: f64,
        close: f64,
        volume: i64,
    ) -> (f64, f64, f64, f64, i64) {
        let factor = self.adjustment_factor(ticker, trade_date);
        if (factor - 1.0).abs() < 1e-12 {
            return (open, high, low, close, volume);
        }
        let vol_factor = (1.0 / factor).round() as i64;
        (
            open * factor,
            high * factor,
            low * factor,
            close * factor,
            volume * vol_factor,
        )
    }
}
```

Add `pub mod splits;` to `lib.rs`.

**Step 5: Run tests to verify they pass**

Run: `cd infra/upq && cargo test -p upq-service --test splits_tests`
Expected: All 5 tests PASS

**Step 6: Commit**

```bash
git add infra/upq/crates/upq-service/src/splits.rs \
        infra/upq/crates/upq-service/src/lib.rs \
        infra/upq/crates/upq-service/tests/splits_tests.rs \
        infra/upq/storage/splits.json
git commit -m "feat(upq): add SplitCalendar for on-read stock split adjustment"
```

---

## Task 2: UPQ — Wire SplitCalendar Into `/stock/daily`

**Files:**
- Modify: `infra/upq/crates/upq-service/src/app.rs:39-44` (AppState)
- Modify: `infra/upq/crates/upq-service/src/app.rs:144-173` (startup)
- Modify: `infra/upq/crates/upq-service/src/app.rs:309-358` (stock_daily handler)
- Test: `infra/upq/crates/upq-service/tests/api_contract_tests.rs` (add test)

**Step 1: Write failing API test**

Add to `api_contract_tests.rs`:

```rust
#[tokio::test]
async fn test_stock_daily_applies_split_adjustment() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;

    // Write splits.json with NVDA 10:1 split on 2024-06-10
    let splits_json = r#"{"splits":[{"ticker":"NVDA","effective_date":"2024-06-10","ratio":10}]}"#;
    std::fs::write(tmp.path().join("splits.json"), splits_json)?;

    // Create stock_daily parquet with pre-split NVDA price ($1200)
    let daily_dir = tmp.path().join("stock_daily").join("trade_date=2024-06-07");
    std::fs::create_dir_all(&daily_dir)?;
    let conn = duckdb::Connection::open_in_memory()?;
    let parquet_path = daily_dir.join("data.parquet");
    conn.execute_batch(&format!(
        "COPY (SELECT 'NVDA' AS ticker, 1200.0 AS open, 1220.0 AS high, \
         1180.0 AS low, 1210.0 AS close, BIGINT '5000000' AS volume, \
         BIGINT '100000' AS transactions, DATE '2024-06-07' AS trade_date) \
         TO '{}' (FORMAT PARQUET)",
        parquet_path.to_string_lossy().replace('\'', "''")
    ))?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/stock/daily?tickers=NVDA&start=2024-06-07&end=2024-06-07&fields=ticker,date,close,volume")
        .body(Body::empty())?;
    let response = app.oneshot(request).await?;
    assert_eq!(response.status(), StatusCode::OK);

    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let arr = payload.as_array().unwrap();
    assert_eq!(arr.len(), 1);

    let close = arr[0]["close"].as_f64().unwrap();
    // Pre-split $1210 / 10 = $121.0
    assert!((close - 121.0).abs() < 0.01, "split-adjusted close should be ~121.0, got {}", close);

    let volume = arr[0]["volume"].as_i64().unwrap();
    // Pre-split 5M × 10 = 50M
    assert_eq!(volume, 50_000_000, "split-adjusted volume should be 50M, got {}", volume);

    Ok(())
}
```

**Step 2: Run test to verify it fails**

Run: `cd infra/upq && cargo test -p upq-service --test api_contract_tests test_stock_daily_applies_split_adjustment`
Expected: FAIL — close=1210.0 (unadjusted)

**Step 3: Wire SplitCalendar into AppState and stock_daily**

In `app.rs`:
1. Add `split_calendar: Arc<SplitCalendar>` to `AppState`
2. At startup, load from `{storage_root}/splits.json` (fall back to `SplitCalendar::empty()` if missing)
3. In `stock_daily()`, after the SQL query returns rows, apply `split_calendar.adjust_ohlcv()` to each row

The adjustment is applied **post-query** in Rust, not in SQL, to keep the SQL simple and parquet data untouched.

Implementation notes:
- `build_router_with_storage_root()` also needs to load splits.json
- The JSON rows from DuckDB are `serde_json::Value` — mutate close/open/high/low/volume in-place
- Only adjust if `split_calendar.has_splits(ticker)` for performance

**Step 4: Run test to verify it passes**

Run: `cd infra/upq && cargo test -p upq-service --test api_contract_tests test_stock_daily_applies_split_adjustment`
Expected: PASS

**Step 5: Also apply split adjustment to `/stock` (minute data)**

Same pattern: post-query adjustment in the `stock()` handler. Add a corresponding test.

**Step 6: Commit**

```bash
git add infra/upq/crates/upq-service/src/app.rs \
        infra/upq/crates/upq-service/tests/api_contract_tests.rs
git commit -m "feat(upq): apply split adjustment to /stock/daily and /stock endpoints"
```

---

## Task 3: UPQ — Add `/dividends/query` Endpoint

**Files:**
- Modify: `infra/upq/crates/upq-service/src/app.rs` (add route + handler)
- Modify: `infra/upq/docs/openapi.yaml` (add endpoint spec)
- Test: `infra/upq/crates/upq-service/tests/api_contract_tests.rs`

**Step 1: Write failing test**

```rust
#[tokio::test]
async fn test_dividends_query_returns_data() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;

    // Create dividends parquet
    let div_dir = tmp.path().join("dividends");
    std::fs::create_dir_all(&div_dir)?;
    let conn = duckdb::Connection::open_in_memory()?;
    conn.execute_batch(&format!(
        "COPY (SELECT 'JEPQ' AS ticker, DATE '2024-02-01' AS ex_dividend_date, 0.3417 AS amount \
         UNION ALL \
         SELECT 'JEPQ', DATE '2024-03-01', 0.3804) \
         TO '{}' (FORMAT PARQUET)",
        div_dir.join("dividends.parquet").to_string_lossy().replace('\'', "''")
    ))?;

    let app = upq_service::app::build_router_with_storage_root(tmp.path());
    let request = Request::builder()
        .uri("/dividends/query?tickers=JEPQ&start=2024-01-01&end=2024-12-31")
        .body(Body::empty())?;
    let response = app.oneshot(request).await?;
    assert_eq!(response.status(), StatusCode::OK);

    let bytes = to_bytes(response.into_body(), usize::MAX).await?;
    let payload: Value = serde_json::from_slice(&bytes)?;
    let arr = payload.as_array().unwrap();
    assert_eq!(arr.len(), 2);
    assert_eq!(arr[0]["ticker"], "JEPQ");
    assert!((arr[0]["amount"].as_f64().unwrap() - 0.3417).abs() < 0.001);
    Ok(())
}
```

**Step 2: Run → FAIL (404, endpoint doesn't exist)**

**Step 3: Implement `/dividends/query` handler**

- Route: `.route("/dividends/query", get(dividends_query))`
- Query params: `tickers` (CSV), `start` (date), `end` (date)
- SQL: `SELECT ticker, ex_dividend_date, amount FROM dividends.parquet WHERE ticker IN (...) AND ex_dividend_date BETWEEN ...`
- Response: JSON array of `{ticker, ex_dividend_date, amount}`

**Step 4: Run → PASS**

**Step 5: Update OpenAPI spec**

Add `/dividends/query` to `infra/upq/docs/openapi.yaml`.

**Step 6: Commit**

```bash
git commit -m "feat(upq): add /dividends/query endpoint for ETF total return"
```

---

## Task 4: Update MCP Server & Python Client

**Files:**
- Modify: `clients/upq/client.py` (add `dividends()` method)
- Modify: `mcp/server.py` (add `upq_dividends` tool)

**Step 1: Add dividends method to UPQClient**

```python
def dividends(self, tickers: str, start: str, end: str) -> list[dict]:
    """Query dividend data for given tickers and date range."""
    resp = self._get("/dividends/query", params={
        "tickers": tickers, "start": start, "end": end,
    })
    return resp
```

**Step 2: Add MCP tool**

```python
@mcp.tool()
def upq_dividends(tickers: str, start: str, end: str) -> str:
    """Query dividend history for stocks/ETFs. Returns ex-dates and amounts."""
    with UPQClient(UPQ_URL) as client:
        return json.dumps(client.dividends(tickers, start, end))
```

**Step 3: Commit**

```bash
git commit -m "feat: add dividends query to UPQ Python client and MCP server"
```

---

## Task 5: Fix ETF Benchmark Total Return in Overlay Scripts

**Files:**
- Modify: `infra/pmb/demos/overlay_helpers.py` (add `get_etf_total_return()`)
- Modify: `infra/pmb/demos/overlay_profit_increase_v2.py` (use total return)

**Step 1: Add helper that computes total return including dividends**

```python
def get_etf_total_return(ticker: str, start_date: str, end_date: str) -> float | None:
    """Compute ETF total return (price + reinvested dividends).

    Uses price return + cumulative dividends / start price.
    """
    prices = get_etf_daily_prices(ticker, start_date, end_date)
    if len(prices) < 2:
        return None
    start_price = prices[0]["close"]
    end_price = prices[-1]["close"]

    # Query dividends
    try:
        resp = requests.get(f"{UPQ_CHAIN}/dividends/query", params={
            "tickers": ticker, "start": start_date, "end": end_date,
        }, timeout=30)
        divs = resp.json() if resp.status_code == 200 else []
    except Exception:
        divs = []

    total_divs = sum(d.get("amount", 0) for d in divs)
    return (end_price - start_price + total_divs) / start_price
```

**Step 2: Update overlay_profit_increase_v2.py ETF benchmark calculation**

Replace the price-only ETF return with `get_etf_total_return()`.

**Step 3: Smoke test on qlib**

Run: `ssh qlib "cd /home/qlib/qfinzero/infra/pmb && python3 demos/overlay_profit_increase_v2.py --ticker QQQ"`
Expected: JEPQ return ~24.7% (not 13.7%)

**Step 4: Commit**

```bash
git commit -m "fix(pmb): use total return (price + dividends) for ETF benchmarks"
```

---

## Task 6: PMB SpreadOrder Model

**Files:**
- Modify: `infra/pmb/models/order.py` (add SpreadOrderSpec, spread_id field)
- Create: `infra/pmb/tests/test_spread_order.py`

**Step 1: Write failing test**

```python
def test_spread_order_spec_has_two_legs():
    from models.order import SpreadOrderSpec, OrderSpec
    from models.instrument import Instrument
    from models.enums import Side, OrderType, InstrumentType

    leg1 = OrderSpec(
        instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
        side=Side.BUY, order_type=OrderType.MARKET, qty=1,
    )
    leg2 = OrderSpec(
        instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00380000"),
        side=Side.SELL, order_type=OrderType.MARKET, qty=1,
    )
    spread = SpreadOrderSpec(legs=[leg1, leg2], spread_type="PUT_DEBIT_SPREAD")
    assert len(spread.legs) == 2
    assert spread.spread_type == "PUT_DEBIT_SPREAD"
    assert spread.max_loss_per_unit() == 10.0  # $390 - $380 = $10 width


def test_spread_order_spec_validates_same_underlying():
    from models.order import SpreadOrderSpec, OrderSpec
    from models.instrument import Instrument
    from models.enums import Side, OrderType, InstrumentType

    leg1 = OrderSpec(
        instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
        side=Side.BUY, order_type=OrderType.MARKET, qty=1,
    )
    leg2 = OrderSpec(
        instrument=Instrument(type=InstrumentType.OPTION, contract="O:NVDA240119P00130000"),
        side=Side.SELL, order_type=OrderType.MARKET, qty=1,
    )
    spread = SpreadOrderSpec(legs=[leg1, leg2], spread_type="PUT_DEBIT_SPREAD")
    err = spread.validate()
    assert err is not None
    assert "underlying" in err.lower()
```

**Step 2: Run → FAIL (SpreadOrderSpec not defined)**

**Step 3: Implement SpreadOrderSpec**

Add to `models/order.py`:

```python
class SpreadOrderSpec(BaseModel):
    """Multi-leg order specification for spreads."""
    legs: list[OrderSpec]
    spread_type: str  # PUT_DEBIT_SPREAD, PUT_CREDIT_SPREAD, etc.

    def max_loss_per_unit(self) -> float:
        """Max loss per spread unit = width between strikes."""
        strikes = []
        for leg in self.legs:
            contract = leg.instrument.contract or ""
            # Extract strike from OPRA: last 8 digits / 1000
            if len(contract) >= 8:
                try:
                    strikes.append(int(contract[-8:]) / 1000.0)
                except ValueError:
                    pass
        if len(strikes) == 2:
            return abs(strikes[0] - strikes[1])
        return 0.0

    def validate(self) -> str | None:
        """Validate spread legs. Returns error message or None."""
        if len(self.legs) != 2:
            return "Spread must have exactly 2 legs"
        # Check same underlying
        underlyings = set()
        for leg in self.legs:
            contract = leg.instrument.contract or ""
            # O:QQQ240119P00390000 → underlying = QQQ
            if contract.startswith("O:"):
                parts = contract[2:]
                # Extract letters before first digit
                underlying = ""
                for ch in parts:
                    if ch.isalpha():
                        underlying += ch
                    else:
                        break
                underlyings.add(underlying)
        if len(underlyings) > 1:
            return f"Spread legs must have same underlying, got {underlyings}"
        return None
```

Also add `spread_id: Optional[str] = None` field to `CreateOrderRequest`.

**Step 4: Run → PASS**

**Step 5: Commit**

```bash
git commit -m "feat(pmb): add SpreadOrderSpec model for multi-leg option orders"
```

---

## Task 7: PMB Spread Margin Calculation

**Files:**
- Modify: `infra/pmb/domain/margin_engine.py` (add `margin_for_spread()`)
- Create: `infra/pmb/tests/test_spread_margin.py`

**Step 1: Write failing test**

```python
def test_spread_margin_uses_width_not_individual():
    from domain.margin_engine import MarginEngine
    from models.account import MarginConfig

    engine = MarginEngine(MarginConfig())

    # Put spread: sell 390 put, buy 380 put → width = $10 → max loss = $1000
    spread_margin = engine.margin_for_spread(
        spread_width=10.0,  # $10 between strikes
        qty=1,
        multiplier=100,
    )
    assert spread_margin == 1000.0  # $10 × 100 × 1

    # Compare: individual margin would be much higher
    # sell 390 put: 0.20 × 390 × 100 = $7,800
    individual = engine.initial_margin_for_order("SELL", "OPTION", 1, 390.0 * 100)
    assert spread_margin < individual
```

**Step 2: Run → FAIL**

**Step 3: Implement**

Add to `margin_engine.py`:

```python
def margin_for_spread(self, spread_width: float, qty: int, multiplier: int = 100) -> float:
    """Margin for a spread = max loss = width × qty × multiplier."""
    return spread_width * qty * multiplier
```

**Step 4: Run → PASS**

**Step 5: Commit**

```bash
git commit -m "feat(pmb): add spread margin calculation (width × qty × multiplier)"
```

---

## Task 8: PMB Atomic Spread Execution

**Files:**
- Modify: `infra/pmb/domain/execution_engine.py` (add `process_spread()`)
- Create: `infra/pmb/tests/test_spread_execution.py`

**Step 1: Write failing test**

```python
def test_spread_execution_fills_both_legs_atomically():
    """Both legs of a spread should fill in the same tick or neither fills."""
    from domain.execution_engine import ExecutionEngine
    from domain.ledger import Ledger
    from domain.order_manager import OrderManager
    from domain.margin_engine import MarginEngine
    from models.order import Order, CreateOrderRequest, OrderSpec
    from models.instrument import Instrument
    from models.enums import Side, OrderType, InstrumentType, OrderStatus
    from models.session import FeeModel
    from models.account import MarginConfig

    engine = ExecutionEngine(seed=42, slippage_bps=0.0, fee_model=FeeModel())
    ledger = Ledger(initial_cash=100_000.0)
    om = OrderManager()
    me = MarginEngine(MarginConfig())

    # Two option bars
    option_bars = {
        "OPTION:O:QQQ240119P00390000": {"open": 5.0, "high": 5.5, "low": 4.5, "close": 5.0},
        "OPTION:O:QQQ240119P00380000": {"open": 2.0, "high": 2.5, "low": 1.5, "close": 2.0},
    }

    # Submit two linked orders (buy long put, sell short put)
    req1 = CreateOrderRequest(
        session_id="s1", account_id="a1", client_order_id="spread_leg1",
        order=OrderSpec(
            instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
            side=Side.BUY, order_type=OrderType.MARKET, qty=1,
        ),
        spread_id="spread_001",
    )
    req2 = CreateOrderRequest(
        session_id="s1", account_id="a1", client_order_id="spread_leg2",
        order=OrderSpec(
            instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00380000"),
            side=Side.SELL, order_type=OrderType.MARKET, qty=1,
        ),
        spread_id="spread_001",
    )
    o1, _ = om.submit(req1, "2024-01-02")
    om.accept(o1.order_id, "2024-01-02")
    o2, _ = om.submit(req2, "2024-01-02")
    om.accept(o2.order_id, "2024-01-02")

    events, trades = engine.process_step(
        "2024-01-02", 0, {}, option_bars, om, ledger, me)

    # Both should be filled
    assert om.get_order(o1.order_id).status == OrderStatus.FILLED
    assert om.get_order(o2.order_id).status == OrderStatus.FILLED
    assert len(trades) == 2

    # Net cash impact: bought put at $5 (-$500), sold put at $2 (+$200) = -$300 net debit
    # Plus fees
    assert ledger.cash < 100_000.0
```

**Step 2: Run → FAIL**

**Step 3: Implement spread-aware execution in `process_step()`**

Key change: before executing orders individually, group orders by `spread_id`. For spread groups:
1. Check both legs have bars available
2. Check combined margin (use `margin_for_spread` instead of individual)
3. Fill both atomically or reject both

For non-spread orders, existing logic is unchanged.

**Step 4: Run → PASS**

**Step 5: Commit**

```bash
git commit -m "feat(pmb): atomic spread execution in ExecutionEngine.process_step()"
```

---

## Task 9: Delta Constraint in Overlay Scripts

**Files:**
- Modify: `infra/pmb/demos/overlay_helpers.py` (add `query_option_greeks()`, `compute_effective_delta()`)
- Modify: `infra/pmb/demos/overlay_profit_increase_v2.py` (add delta check before opening)
- Modify: `infra/pmb/demos/overlay_hedging_v2.py` (add delta check)
- Modify: `infra/pmb/demos/overlay_llm_agent.py` (add delta to prompt)

**Step 1: Add delta helper functions**

```python
def query_option_greeks(contract: str, date: str) -> dict | None:
    """Get greeks for a specific option contract from UPQ."""
    try:
        resp = requests.get(f"{UPQ_CHAIN}/option/ticker_query", params={
            "contract": contract, "start": date, "end": date,
            "resolution": "day", "include_greeks": "true",
            "fields": "ticker,close,delta",
        }, timeout=10)
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return rows[0]
    except Exception:
        pass
    return None


def compute_effective_delta(stock_qty: int, option_positions: list[dict]) -> float:
    """Compute portfolio effective delta.

    Args:
        stock_qty: Number of shares held (positive = long)
        option_positions: List of {contract, qty, delta} where qty is signed
            (negative = short), delta is per-share delta from greeks

    Returns:
        Effective delta in share-equivalents.
    """
    delta = float(stock_qty)
    for pos in option_positions:
        # Each contract covers 100 shares
        # qty is signed: -1 = short 1 contract
        contract_delta = pos.get("delta", 0.0) * pos["qty"] * 100
        delta += contract_delta
    return delta
```

**Step 2: Add delta check to overlay scripts**

Before opening a new position in the trading loop:

```python
# Delta constraint: skip if adding this position exceeds initial stock qty
if active_call_contract is None and contract_idx < len(contracts):
    # ... find next contract ...
    # Query delta for the candidate contract
    greeks = query_option_greeks(c["ticker"], current_date)
    if greeks and greeks.get("delta"):
        candidate_delta = greeks["delta"]
        # For a short call: delta contribution = -delta × 1 × 100
        new_delta = compute_effective_delta(stock_pos, current_option_positions)
        new_delta += (-candidate_delta) * 1 * 100  # short call
        if abs(new_delta) > STOCK_QTY:
            print(f"  DELTA CONSTRAINT: skip, effective delta would be {new_delta:.0f}")
            continue
```

**Step 3: Add delta to LLM prompt**

In `overlay_llm_agent.py`, add to the user prompt:
```
- Current effective delta: {delta:.0f} (target ≤ {STOCK_QTY:,})
```

**Step 4: Commit**

```bash
git commit -m "feat(pmb): add delta constraint to overlay strategies and LLM prompt"
```

---

## Task 10: Smoke Test Full Pipeline on qlib

**Files:** None (verification only)

**Step 1: Push all changes, pull on qlib**

```bash
git push origin feat/overlay-strategy-backtest
ssh qlib "cd /home/qlib/qfinzero && git pull"
```

**Step 2: Verify UPQ split adjustment**

```bash
ssh qlib "curl -s 'http://127.0.0.1:19703/stock/daily?tickers=NVDA&start=2024-06-07&end=2024-06-10&fields=ticker,date,close'"
# Expected: 2024-06-07 close ~$121 (not $1210)
```

**Step 3: Verify dividends endpoint**

```bash
ssh qlib "curl -s 'http://127.0.0.1:19703/dividends/query?tickers=JEPQ&start=2024-01-01&end=2024-12-31'"
# Expected: 12 dividend entries
```

**Step 4: Run NVDA covered call**

```bash
ssh qlib "cd /home/qlib/qfinzero/infra/pmb && python3 demos/overlay_profit_increase_v2.py --ticker NVDA"
# Expected: positive return (not -60%), max drawdown reasonable
```

**Step 5: Verify ETF total return**

```bash
# JEPQ should show ~24.7% total return (not 13.7%)
```

**Step 6: Commit verification results (optional)**

```bash
git commit -m "test(pmb): verify Phase 2 enhancements on qlib"
```

---

## Summary

| Task | Component | Type | Description |
|------|-----------|------|-------------|
| 1 | UPQ | Rust | SplitCalendar data structure + unit tests |
| 2 | UPQ | Rust | Wire split adjustment into `/stock/daily` and `/stock` |
| 3 | UPQ | Rust | New `/dividends/query` endpoint |
| 4 | Client/MCP | Python | Add dividends to UPQClient + MCP server |
| 5 | Overlay | Python | ETF benchmark total return (price + dividends) |
| 6 | PMB | Python | SpreadOrderSpec model |
| 7 | PMB | Python | Spread margin calculation |
| 8 | PMB | Python | Atomic spread execution |
| 9 | Overlay | Python | Delta constraint in strategies + LLM prompt |
| 10 | E2E | — | Smoke test full pipeline on qlib |

**Dependencies:** Task 2 depends on 1. Task 5 depends on 3-4. Tasks 7-8 depend on 6. Task 10 depends on all others. Tasks 1-4 and 6-9 can be parallelized across UPQ and PMB tracks.
