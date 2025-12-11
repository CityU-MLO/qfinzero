# Financial Data & Options API Documentation

This API provides access to historical stock prices, option prices, option chains, Treasury rates, and calculated Greeks (Implied Volatility, Delta, Gamma, etc.).

## Base Configuration

  * **Default Host:** `0.0.0.0`
  * **Default Port:** `19019`
  * **Base URL:** `http://<host>:19019`
  * **Date Format:** All dates should be provided in `YYYY-MM-DD` format.
  * **Option Ticker Format:** OPRA standard (e.g., `O:NVDA250117C00300000`).

-----

## System

### Health Check

Checks the status of the service, configuration paths, and data availability.

  * **Endpoint:** `GET /health`
  * **Response:**
    ```json
    {
      "status": "ok",
      "options_h5": "/path/to/options.h5",
      "prices_h5": "/path/to/prices.h5",
      "rates_csv": "/path/to/rates.csv",
      "nvda_key": true,
      "greeks_available": true
    }
    ```

-----

## Metadata & Discovery

### Collect Tickers

Retrieve a list of available underlying symbols or specific option contract tickers.

  * **Endpoint:** `GET /collect/tickers`

  * **Parameters:**
    | Parameter | Type | Default | Description |
    | :--- | :--- | :--- | :--- |
    | `kind` | string | `underlying` | `underlying` for stock symbols, or `option` for full contract strings. |

  * **Response:**

    ```json
    {
      "count": 50,
      "tickers": ["AAPL", "NVDA", "TSLA", ...]
    }
    ```

### Collect Trading Days

Retrieve all calendar dates for which option data is available.

  * **Endpoint:** `GET /collect/trading_days`
  * **Response:**
    ```json
    {
      "count": 250,
      "trading_days": ["2024-01-02", "2024-01-03", ...]
    }
    ```

-----

## Market Data: Stocks

### Query Stock Price (Single Day)

Get OHLC (Open, High, Low, Close) data for a stock on a specific date.

  * **Endpoint:** `GET /query/stock_price`

  * **Parameters:**
    | Parameter | Type | Required | Description |
    | :--- | :--- | :--- | :--- |
    | `ticker` | string | Yes | The stock symbol (e.g., `NVDA`). |
    | `date` | string | Yes | The trade date. |
    | `asof` | boolean | No | If true (default), returns the most recent data on or before the date if exact match fails. |

  * **Response:**

    ```json
    {
      "ticker": "NVDA",
      "date": "2025-01-10",
      "open": 500.0,
      "close": 505.0,
      "high": 510.0,
      "low": 495.0,
      "volume": 1000000,
      "asof": "2025-01-10"
    }
    ```

### Query Stock History (Range)

Get OHLC data for a stock over a date range.

  * **Endpoint:** `GET /query/stock_history`

  * **Parameters:**
    | Parameter | Type | Required | Description |
    | :--- | :--- | :--- | :--- |
    | `ticker` | string | Yes | The stock symbol. |
    | `start_date` | string | Yes | Start of the range. |
    | `end_date` | string | No | End of the range. Defaults to `start_date`. |

  * **Response:**

    ```json
    {
      "ticker": "NVDA",
      "request_start": "2024-01-01",
      "request_end": "2024-01-31",
      "count": 20,
      "history": [
        { "date": "2024-01-02", "close": 480.0, ... },
        { "date": "2024-01-03", "close": 485.0, ... }
      ]
    }
    ```

-----

## Market Data: Options

### Query Option Price (Single Day)

Get OHLC data for a specific option contract on a specific date.

  * **Endpoint:** `GET /query/option_price`

  * **Parameters:**
    | Parameter | Type | Required | Description |
    | :--- | :--- | :--- | :--- |
    | `ticker` | string | Yes | OPRA option ticker (e.g., `O:NVDA250117C00300000`). |
    | `date` | string | Yes | The trade date. |

  * **Response:**

    ```json
    {
      "date": "2025-01-10",
      "ticker": "O:NVDA250117C00300000",
      "underlying": "NVDA",
      "strike": 300.0,
      "type": "C",
      "expiry": "2025-01-17",
      "close": 15.5,
      "volume": 500
      ...
    }
    ```

### Query Option History (Range)

Get OHLC data for a specific option contract over a date range. This endpoint uses multi-threading for performance.

  * **Endpoint:** `GET /query/option_history`

  * **Parameters:**
    | Parameter | Type | Required | Description |
    | :--- | :--- | :--- | :--- |
    | `ticker` | string | Yes | OPRA option ticker. |
    | `start_date` | string | Yes | Start of the range. |
    | `end_date` | string | No | End of the range. |

  * **Response:**

    ```json
    {
      "ticker": "O:NVDA250117C00300000",
      "underlying": "NVDA",
      "count": 5,
      "history": [
        { "date": "2025-01-10", "close": 15.5, ... },
        ...
      ]
    }
    ```

-----

## Analytics: Greeks & Chains

### Query Option Greeks (Single)

Compute Implied Volatility (IV) and Greeks (Delta, Gamma, Vega, Theta, Rho) for a single contract.

  * **Endpoint:** `GET /query/option_greeks`

  * **Parameters:**
    | Parameter | Type | Required | Description |
    | :--- | :--- | :--- | :--- |
    | `ticker` | string | Yes | OPRA option ticker. |
    | `date` | string | Yes | The trade date. |

  * **Response:** JSON object containing IV and Greek values.

### Query Option Chain (Snapshot)

Retrieve the full option chain for an underlying stock on a specific date. Supports filtering and Greek calculation.

  * **Endpoint:** `GET /query/chain`

  * **Parameters:**
    | Parameter | Type | Required | Description |
    | :--- | :--- | :--- | :--- |
    | `ticker` | string | Yes | Underlying symbol (e.g., `NVDA`). |
    | `date` | string | Yes | Trade date. |
    | `type` | string | No | Filter by `call` (`c`) or `put` (`p`). |
    | `level` | int | No | Number of strikes to retrieve above/below center price. |
    | `expiry_days` | int | No | Max days-to-expiry filter. |
    | `strike_gt` | float | No | Minimum strike price filter. |
    | `strike_lt` | float | No | Maximum strike price filter. |
    | `price` | float | No | Override the center price (defaults to underlying close). |
    | `require_greek` | boolean | No | If `true`, computes IV/Greeks for every option in the chain. |

  * **Response:**

    ```json
    {
      "underlying": "NVDA",
      "date": "2025-01-10",
      "meta": { "center_price": 500.0, "require_greek": true },
      "data": [
         { "strike": 500, "type": "C", "bid": 10.0, "ask": 10.5, "delta": 0.5, ... },
         ...
      ]
    }
    ```

### Query IV Surface

Computes the Volatility Surface for an underlying based on a reference option ticker. This serves as a specialized view of the option chain optimized for surface plotting.

  * **Endpoint:** `GET /query/iv_surface`
  * **Parameters:**
    | Parameter | Type | Required | Description |
    | :--- | :--- | :--- | :--- |
    | `ticker` | string | Yes | Reference OPRA ticker (used to identify underlying). |
    | `date` | string | Yes | Trade date. |

-----

## Treasury Rates

### Query Rates

Get the Treasury yield curve for a specific date.

  * **Endpoint:** `GET /query/rates`

  * **Parameters:**
    | Parameter | Type | Required | Description |
    | :--- | :--- | :--- | :--- |
    | `date` | string | Yes | The date to query. |

  * **Response:**

    ```json
    {
      "asof": "2025-01-10",
      "rates": {
        "1M": 0.052,
        "3M": 0.053,
        "1Y": 0.048,
        ...
      }
    }
    ```