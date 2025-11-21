````markdown
# OptionBench Market Data API

A lightweight HTTP API (Flask) for querying:

- Daily **equity prices**
- **Option prices** (OPRA-style tickers)
- **Treasury yield curves**
- **Option chains** around a center price
- Available **tickers** and **trading days**

The service is read-only and stateless.

---

## 1. Base URL

By default, the app runs on:

```text
http://<host>:19019
````

(Port can be overridden with the `PORT` environment variable.)

---

## 2. Configuration & Data Files

The API reads market data from three files:

* `OPTIONS_H5_PATH` (HDF5): structured option data
  default: `/home/hluo/OptionBench/data/assets/options_structured.h5`

* `PRICES_H5_PATH` (HDF5): per-ticker daily price history
  default: `/home/hluo/OptionBench/data/assets/prices_2025.h5`

* `RATES_CSV_PATH` (CSV): daily treasury yields or risk-free rates
  default: `/home/hluo/OptionBench/data/assets/treasury_yields.csv`

All dates use the format:

```text
YYYY-MM-DD
```

---

## 3. Common Conventions

### 3.1 Error Response

All errors are returned as JSON:

```json
{
  "error": "<message>"
}
```

Typical HTTP status codes:

* `400` – Bad request (missing/invalid parameters)
* `404` – Data not found
* `200` – Success

---

## 4. Endpoints

### 4.1 `GET /health`

Simple health check and basic config probe.

**Description**

* Checks that the APIs can see the configured data files.
* Tries to detect whether a table for ticker `NVDA` exists in the prices HDF5.

**Request**

```http
GET /health
```

**Response**

```json
{
  "status": "ok",
  "options_h5": "/path/to/options_structured.h5",
  "prices_h5": "/path/to/prices_2025.h5",
  "rates_csv": "/path/to/treasury_yields.csv",
  "nvda_key": "/NVDA"    // or null if not found
}
```

---

### 4.2 `GET /collect/tickers`

Collect all **underlying** tickers or **option** tickers.

**Request**

```http
GET /collect/tickers?kind=<kind>
```

**Query Parameters**

| Name   | Type   | Default      | Description                                                                                 |
| ------ | ------ | ------------ | ------------------------------------------------------------------------------------------- |
| `kind` | string | `underlying` | `underlying` – list underlying symbols; `option` – list option tickers (full option codes). |

**Response**

```json
{
  "count": 123,
  "tickers": [
    "AAPL",
    "MSFT",
    "NVDA",
    ...
  ]
}
```

If `kind=option`, `tickers` will contain the raw option tickers as stored in the index (e.g. OPRA-style).

---

### 4.3 `GET /collect/trading_days`

Return all trading dates for which there is options data.

**Request**

```http
GET /collect/trading_days
```

**Response**

```json
{
  "count": 250,
  "trading_days": [
    "2025-01-02",
    "2025-01-03",
    ...
  ]
}
```

---

### 4.4 `GET /query/stock_price`

Query daily OHLC for a **stock ticker** on a given date, with optional “as-of” fallback.

**Request**

```http
GET /query/stock_price?ticker=<ticker>&date=<date>[&asof=<0|1|true|false>]
```

**Query Parameters**

| Name     | Type    | Required | Default | Description                                                                                                                       |
| -------- | ------- | -------- | ------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `ticker` | string  | yes      | –       | Stock ticker symbol (e.g. `NVDA`, `AAPL`). Case-insensitive.                                                                      |
| `date`   | string  | yes      | –       | Target date (parsed by pandas, normalized to `YYYY-MM-DD`).                                                                       |
| `asof`   | boolean | no       | `true`  | If true, returns the **latest available date ≤ requested date** when exact date is missing. If false, requires an exact date row. |

**Behavior**

* If the ticker is unknown, returns `404`.
* If `asof=true` and there is no data **on or before** the requested date, returns `404`.
* Columns are auto-matched even if stored in MultiIndex form (`Open`, `High`, `Low`, `Close`).

**Success Response**

```json
{
  "ticker": "NVDA",
  "date": "2025-01-10",
  "open": 120.5,
  "close": 123.7,
  "high": 125.3,
  "low": 119.8,
  "asof": "2025-01-09"   // only present if as-of fallback is used and date differs
}
```

If an exact row for `date` exists, `asof` is omitted.

**Error Examples**

* Missing params:

```json
{
  "error": "ticker and date required, e.g. ?ticker=NVDA&date=2025-01-10"
}
```

* No data:

```json
{
  "error": "not found: NVDA 2025-01-10"
}
```

---

### 4.5 `GET /query/option_price`

Query the **daily OHLC and volume** for a single option contract identified by its **OPRA-style ticker**.

**OPRA Ticker Format**

The API expects tickers matching:

```text
[O:]<UNDERLYING><YYMMDD><C|P><STRIKE_8DIGITS>
```

* Optional leading `"O:"` prefix.
* `UNDERLYING`: underlying symbol, e.g. `NVDA`, `SPY`, `BRK.B`.
* `YYMMDD`: expiry date (e.g. `250117` → `2025-01-17`).
* `C|P`: `C` = Call, `P` = Put.
* `STRIKE_8DIGITS`: strike × 1000, zero-padded to 8 digits.
  e.g. strike `120.0` → `"00120000"`.

Examples:

* `"NVDA250117C00120000"`
* `"O:NVDA250117P00100000"`

**Request**

```http
GET /query/option_price?ticker=<opra_ticker>&date=<date>
```

**Query Parameters**

| Name     | Type   | Required | Description                                               |
| -------- | ------ | -------- | --------------------------------------------------------- |
| `ticker` | string | yes      | OPRA-style option ticker (with or without `O:` prefix).   |
| `date`   | string | yes      | Observation date for prices (normalized to `YYYY-MM-DD`). |

**Behavior**

1. Parses the OPRA ticker (underlying, expiry, type, strike).
2. Loads the per-day options table for the underlying on `date`.
3. Searches for a matching `ticker` in the data, allowing presence/absence of `O:` prefix.

**Success Response**

```json
{
  "date": "2025-01-10",
  "ticker": "O:NVDA250117C00120000",
  "underlying": "NVDA",
  "expiry": "2025-01-17",
  "type": "call",
  "strike": 120.0,
  "open": 4.35,
  "close": 5.10,
  "high": 5.30,
  "low": 4.20,
  "volume": 1234
}
```

**Error Responses**

* Invalid OPRA format:

```json
{
  "error": "Invalid OPRA ticker format: NVDA_foo"
}
```

* No option table for that date/underlying:

```json
{
  "error": "no option data"
}
```

* Contract not found on that date:

```json
{
  "error": "not found"
}
```

---

### 4.6 `GET /query/rates`

Query the **treasury yield curve** (or generic rate table) on a given date, with “as-of” fallback.

**Request**

```http
GET /query/rates?date=<date>
```

**Query Parameters**

| Name   | Type   | Required | Description                                                                                        |
| ------ | ------ | -------- | -------------------------------------------------------------------------------------------------- |
| `date` | string | yes      | Target date. The API will use exact date if available, otherwise the latest date ≤ requested date. |

**Behavior**

* CSV is loaded once and cached.
* The first column named `"date"` (case-insensitive) is used as index; if none, uses the first column.
* If no row exists **on or before** the requested date, returns `404`.

**Success Response**

Example (columns depend on your CSV):

```json
{
  "asof": "2025-01-09",
  "rates": {
    "1M": 0.0523,
    "3M": 0.0531,
    "6M": 0.0540,
    "1Y": 0.0555,
    "2Y": 0.0567
  }
}
```

All numeric fields are converted to `float` where possible, otherwise `null`.

**Error Example**

```json
{
  "error": "date required"
}
```

or

```json
{
  "error": "no data on/before date"
}
```

---

### 4.7 `GET /query/chain`

Query the **option chain** for an underlying on a given date, with rich filtering:

* Call/put filter
* Max days to expiry
* Strike range
* Focusing on strikes near a **center price** (either provided or auto-detected from stock close)

**Request**

```http
GET /query/chain
  ?ticker=<underlying>
  &date=<date>
  [&type=<C|P|call|put>]
  [&level=<int>]
  [&expiry_days=<int>]
  [&strike_gt=<float>]
  [&strike_lt=<float>]
  [&price=<float>]
```

**Query Parameters**

| Name          | Type   | Required | Description                                                                                                                                  |
| ------------- | ------ | -------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `ticker`      | string | yes      | Underlying symbol for the option chain (must match how it appears in the options HDF5).                                                      |
| `date`        | string | yes      | Trading date (`YYYY-MM-DD`).                                                                                                                 |
| `type`        | string | no       | Filter by option type: `C` / `call` for calls; `P` / `put` for puts. If omitted, returns both.                                               |
| `level`       | int    | no       | If provided and > 0, keep only **strikes near the center price**: `level` strikes below and `level` strikes above.                           |
| `expiry_days` | int    | no       | Maximum days to expiry (i.e., keep contracts where `(expiry - date) ≤ expiry_days`).                                                         |
| `strike_gt`   | float  | no       | Keep only options with `strike > strike_gt`.                                                                                                 |
| `strike_lt`   | float  | no       | Keep only options with `strike < strike_lt`.                                                                                                 |
| `price`       | float  | no       | Override center price used for strike selection. If omitted, the API checks the stock close price on `date` **as-of** and uses it as center. |

**Center Price & Meta**

* If `price` is provided, it is used as `center_price` and no stock lookup is performed.
* If `price` is omitted:

  * The API calls `/query/stock_price` internally (as-of mode) to get the close price.
  * This close price becomes `center_price`.
  * `meta.asof` indicates which date’s stock price was used (may be ≤ requested `date`).

**Success Response**

```json
{
  "underlying": "NVDA",
  "date": "2025-01-10",
  "meta": {
    "center_price": 123.7,      // either provided or inferred from stock close
    "asof": "2025-01-10"        // null if `price` param is used or exact date used
  },
  "data": {
    "C": {
      "2025-01-17": [
        {
          "date": "2025-01-10",
          "ticker": "O:NVDA250117C00120000",
          "strike": 120.0,
          "volume": 1234,
          "open": 4.35,
          "close": 5.10,
          "high": 5.30,
          "low": 4.20,
          "expiry": "2025-01-17"
        },
        ...
      ],
      "2025-02-21": [
        ...
      ]
    },
    "P": {
      "2025-01-17": [
        ...
      ]
    }
  }
}
```

* Top-level `data` has keys `"C"` and `"P"` (always present but can be empty dicts).
* Under each type, keys are expiry dates (`YYYY-MM-DD`), and values are arrays of option records.

Each option record includes:

* `date` – observation date
* `ticker` – raw option ticker as stored in the HDF5
* `strike` – float
* `volume` – int or `null`
* `open`, `close`, `high`, `low` – float or `null`
* `expiry` – expiry date (`YYYY-MM-DD`)

**Error Examples**

* Missing parameters:

```json
{
  "error": "ticker and date required"
}
```

* No option data for date/ticker:

```json
{
  "error": "No option data for NVDA on 2025-01-10"
}
```

---

## 5. Notes on Data Layout

### 5.1 Options HDF5 (`OPTIONS_H5_PATH`)

* Index table: `"/index/ticker_first_seen"`
  Contains, at minimum, columns: `ticker`, `underlying`, `date`, `expiry`.
* Daily option data tables:
  Keys like: `"/data/<YYYY-MM-DD>/<UNDERLYING>"`.

Each daily table is expected to have columns including:

* `date`
* `ticker`
* `type` (`"C"` / `"P"`)
* `expiry`
* `strike`
* `open`, `high`, `low`, `close`
* `volume`

### 5.2 Prices HDF5 (`PRICES_H5_PATH`)

* Keys: `"/_meta"` (optional), and one key per ticker: `"/NVDA"`, `"/AAPL"`, etc.
* Each ticker table:

  * Index: date/time (can be timezone-aware or not; the API normalizes to date).
  * Columns typically: `Open`, `High`, `Low`, `Close`, `Adj Close`, `Volume`.
  * MultiIndex columns are also supported (flattened internally).

### 5.3 Rates CSV (`RATES_CSV_PATH`)

* One row per date.
* First column named `"date"` (any case) or the first unnamed column is treated as date.
* All other columns are returned as the `rates` dict.

---

## 6. CORS & Auth

* CORS is enabled for all routes (`flask_cors.CORS(app)`).
* There is **no authentication** built-in. If deployment requires auth, it should be added externally (reverse proxy) or by wrapping the Flask routes.

---

## 7. Running the Server

```bash
export OPTIONS_H5_PATH=/path/to/options_structured.h5
export PRICES_H5_PATH=/path/to/prices_2025.h5
export RATES_CSV_PATH=/path/to/treasury_yields.csv
export PORT=19019  # optional

python api_server.py
```

(Replace `api_server.py` with your actual filename.)

The service will listen on:

```text
http://0.0.0.0:19019
```

