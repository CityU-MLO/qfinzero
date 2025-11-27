#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS
from concurrent.futures import ThreadPoolExecutor
from config import OPTIONS_H5_PATH, PRICES_H5_PATH, RATES_CSV_PATH
from utils import respond_error, parse_date_like, to_datestr, _strip_prefix
from greeks_utils import (
    compute_iv_and_greeks_timeseries,
    greeks_build_rate_lookup,
)
from data_access.options_store import (
    parse_option_ticker,
    get_underlyings,
    get_option_tickers,
    get_trading_days,
    load_option_day,
)
from data_access.prices_store import lookup_stock_price, has_ticker_table, lookup_stock_price_range
from data_access.rates_store import get_rates_for_date
from services.option_chain import (
    attach_iv_and_greeks_to_chain,
    build_chain_json,
    compute_single_option_iv_and_greeks,
)

# ---------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------
app = Flask(__name__)
CORS(app)


@app.route("/health", methods=["GET"])
def health():
    """
    Lightweight health check endpoint.

    In addition to reporting config paths, we test whether a simple price
    table (NVDA) is present and whether greeks utilities are available.
    """
    nvda_key = has_ticker_table("NVDA")
    return jsonify(
        {
            "status": "ok",
            "options_h5": OPTIONS_H5_PATH,
            "prices_h5": PRICES_H5_PATH,
            "rates_csv": RATES_CSV_PATH,
            "nvda_key": nvda_key,
            "greeks_available": compute_iv_and_greeks_timeseries is not None,
        }
    )

# ------------ collect ------------
@app.route("/collect/tickers", methods=["GET"])
def collect_tickers():
    """
    Collect either underlying tickers or option tickers.

    Query params:
        kind = 'underlying' (default) or 'option'
    """
    kind = (request.args.get("kind") or "underlying").strip().lower()
    if kind == "option":
        tickers = get_option_tickers()
    else:
        tickers = get_underlyings()
    return jsonify({"count": len(tickers), "tickers": tickers})


@app.route("/collect/trading_days", methods=["GET"])
def collect_trading_days():
    """Return all trading days for which we have any option data."""
    days = get_trading_days()
    return jsonify({"count": len(days), "trading_days": days})

# ------------ stock prices ------------
@app.route("/query/stock_price", methods=["GET"])
def query_stock_price():
    """
    Query OHLC stock price for a given ticker and date.

    Example:
        /query/stock_price?ticker=NVDA&date=2025-01-10&asof=1
    """
    ticker = request.args.get("ticker")
    date = request.args.get("date")
    asof_flag = str(request.args.get("asof", "1")).lower() in ("1", "true", "yes")
    if not ticker or not date:
        return respond_error("ticker and date required, e.g. ?ticker=NVDA&date=2025-01-10")
    try:
        datestr = to_datestr(parse_date_like(date))
    except Exception:
        return respond_error(f"invalid date: {date}")
    data, used = lookup_stock_price(ticker, datestr, asof=asof_flag)
    if data is None:
        return respond_error(f"not found: {ticker} {datestr}", 404)
    out = {"ticker": ticker, "date": datestr, **data}
    if used and used != datestr:
        out["asof"] = used
    return jsonify(out)

# ------------ option_price ------------
@app.route("/query/option_price", methods=["GET"])
def query_option_price():
    """
    Query basic OHLC data for a *single* option contract on a given trade date.

    The ticker must be an OPRA-style option ticker, e.g.:
        O:NVDA250117C00300000
    """
    ticker = request.args.get("ticker")
    date = request.args.get("date")
    if not ticker or not date:
        return respond_error("ticker and date required")
    try:
        meta = parse_option_ticker(ticker)
    except ValueError as e:
        return respond_error(str(e))
    datestr = to_datestr(parse_date_like(date))
    df = load_option_day(meta["underlying"], datestr)
    if df is None or df.empty:
        return respond_error("no option data", 404)
    cand = {ticker, _strip_prefix(ticker, "O:"), f"O:{_strip_prefix(ticker, 'O:')}"}
    sub = df[df["ticker"].isin(cand)]
    if sub.empty:
        return respond_error("not found", 404)
    r = sub.iloc[0]
    return jsonify(
        {
            "date": datestr,
            "ticker": str(r["ticker"]),
            "underlying": meta["underlying"],
            "expiry": meta["expiry"],
            "type": meta["type"],
            "strike": float(meta["strike"]),
            "open": float(r["open"]) if pd.notna(r["open"]) else None,
            "close": float(r["close"]) if pd.notna(r["close"]) else None,
            "high": float(r["high"]) if pd.notna(r["high"]) else None,
            "low": float(r["low"]) if pd.notna(r["low"]) else None,
            "volume": int(r["volume"]) if pd.notna(r["volume"]) else None,
        }
    )

# ------------ option_greeks ------------
@app.route("/query/option_greeks", methods=["GET"])
def query_option_greeks():
    """
    Compute implied volatility and greeks for a single option contract.

    Query params:
        ticker: OPRA option ticker, e.g. O:NVDA250117C00300000
        date:   trade date (YYYY-MM-DD)
    """
    ticker = request.args.get("ticker")
    date = request.args.get("date")
    if not ticker or not date:
        return respond_error("ticker and date required")
    try:
        trade_date = parse_date_like(date)
    except Exception:
        return respond_error(f"invalid date: {date}")

    payload, err = compute_single_option_iv_and_greeks(ticker, trade_date)
    if err is not None:
        # For data / configuration issues, use 400; for missing data, 404.
        status = 404 if "No option data" in err or "underlying price" in err else 400
        return respond_error(err, status=status)
    return jsonify(payload)

# ------------ rates ------------
@app.route("/query/rates", methods=["GET"])
def query_rates():
    """
    Query the Treasury yield curve for a given date.

    If the exact date is missing, we fall back to the most recent available
    date *on or before* the requested one.
    """
    date = request.args.get("date")
    if not date:
        return respond_error("date required")
    try:
        asof_dt, rates = get_rates_for_date(date)
    except KeyError:
        return respond_error("no data on/before date", 404)
    return jsonify({"asof": to_datestr(asof_dt), "rates": rates})

# ------------ chain ------------
@app.route("/query/chain", methods=["GET"])
def query_chain():
    """
    Query an option chain snapshot for a given underlying and trade date.

    Query params:
        ticker:       underlying ticker, e.g. NVDA
        date:         trade date, e.g. 2025-01-10
        type:         'call' / 'c' or 'put' / 'p' (optional filter)
        level:        int, number of strikes above/below center price
        expiry_days:  int, max days-to-expiry filter (T <= expiry_days)
        strike_gt:    float, minimum strike
        strike_lt:    float, maximum strike
        price:        float, override used as center price instead of
                      looking up the underlying close
        require_greek:
                      'true' / '1' / 'yes' to compute IV + greeks and
                      attach them to each option in the chain.
    """
    ticker = request.args.get("ticker")
    date = request.args.get("date")
    if not ticker or not date:
        return respond_error("ticker and date required")

    date_ts = parse_date_like(date)
    datestr = to_datestr(date_ts)

    type_raw = (request.args.get("type") or "").lower()
    tfilter = "C" if type_raw in ("c", "call") else "P" if type_raw in ("p", "put") else None

    level_param = request.args.get("level")
    level = int(level_param) if level_param and str(level_param).strip().isdigit() else None

    expiry_days_param = request.args.get("expiry_days")
    expiry_days = int(expiry_days_param) if expiry_days_param and str(expiry_days_param).strip().isdigit() else None

    strike_gt = float(request.args.get("strike_gt")) if request.args.get("strike_gt") not in (None, "") else None
    strike_lt = float(request.args.get("strike_lt")) if request.args.get("strike_lt") not in (None, "") else None

    require_greek_raw = request.args.get("require_greek")
    require_greek = str(require_greek_raw or "false").lower() in ("1", "true", "yes", "y", "on")

    # Center price: explicit override or underlying close (as-of).
    price_param = request.args.get("price")
    asof_used = None
    if price_param not in (None, ""):
        center_price = float(price_param)
    else:
        px, asof_used = lookup_stock_price(ticker, datestr, asof=True)
        center_price = float(px["close"]) if px else None

    df = load_option_day(ticker, datestr)
    if df is None or df.empty:
        return respond_error(f"No option data for {ticker} on {datestr}", 404)

    # Optional filters: type, strike range, max days-to-expiry
    if tfilter:
        df = df[df["type"] == tfilter]
    if strike_gt is not None:
        df = df[df["strike"] > strike_gt]
    if strike_lt is not None:
        df = df[df["strike"] < strike_lt]
    if expiry_days is not None:
        dte = (df["expiry"] - date_ts).dt.days
        df = df[dte <= expiry_days]

    # Optionally enrich with IV + greeks.
    if require_greek:
        if compute_iv_and_greeks_timeseries is None or greeks_build_rate_lookup is None:
            return respond_error("Greeks utilities are not available (infra.oql.utils.greeks import failed).", 500)
        df = attach_iv_and_greeks_to_chain(df, ticker, date_ts)

    data = build_chain_json(df, center_price, level, include_greeks=require_greek)
    meta = {"center_price": center_price, "asof": asof_used, "require_greek": require_greek}
    return jsonify({"underlying": ticker, "date": datestr, "meta": meta, "data": data})

# ------------ IV surface ------------
@app.route("/query/iv_surface", methods=["GET"])
def query_iv_surface():
    """
    Compute an implied-volatility surface for the underlying associated
    with a given OPRA option ticker on a specified trade date.

    Query params:
        ticker: OPRA option ticker, e.g. O:NVDA250117C00300000
        date:   trade date (YYYY-MM-DD)
    """
    ticker = request.args.get("ticker")
    date = request.args.get("date")
    if not ticker or not date:
        return respond_error("ticker and date required")

    try:
        meta = parse_option_ticker(ticker)
    except ValueError as e:
        return respond_error(str(e))

    try:
        date_ts = parse_date_like(date)
    except Exception:
        return respond_error(f"invalid date: {date}")

    datestr = to_datestr(date_ts)

    df = load_option_day(meta["underlying"], datestr)
    if df is None or df.empty:
        return respond_error(f"No option data for {meta['underlying']} on {datestr}", 404)

    if compute_iv_and_greeks_timeseries is None or greeks_build_rate_lookup is None:
        return respond_error("Greeks utilities are not available (infra.oql.utils.greeks import failed).", 500)

    # Enrich the full chain with IV + greeks.
    df = attach_iv_and_greeks_to_chain(df, meta["underlying"], date_ts)

    # Underlying close (used as center price for strike selection and for
    # client-side plotting convenience).
    px, asof_used = lookup_stock_price(meta["underlying"], datestr, asof=True)
    center_price = float(px["close"]) if px else None

    data = build_chain_json(df, center_price, level=None, include_greeks=True)
    out = {
        "underlying": meta["underlying"],
        "date": datestr,
        "meta": {
            "center_price": center_price,
            "underlying_price_asof": asof_used,
            "n_contracts": int(len(df)),
        },
        "data": data,
    }
    return jsonify(out)


@app.route("/query/stock_history", methods=["GET"])
def query_stock_history():
    """
    Query OHLC stock price history for a given ticker and date range.

    Example:
        /query/stock_history?ticker=NVDA&start_date=2024-01-01&end_date=2024-01-31
    """
    ticker = request.args.get("ticker")
    start_date_raw = request.args.get("start_date")
    end_date_raw = request.args.get("end_date")

    # 1. Validation
    if not ticker:
        return respond_error("ticker is required")
    
    if not start_date_raw:
        return respond_error("start_date is required")

    # If end_date is missing, default to start_date (single day range) or today
    # Here we default to start_date for safety, or you could raise an error.
    if not end_date_raw:
        end_date_raw = start_date_raw

    # 2. Date Parsing
    try:
        start_datestr = to_datestr(parse_date_like(start_date_raw))
        end_datestr = to_datestr(parse_date_like(end_date_raw))
    except Exception:
        return respond_error(f"invalid date format. Start: {start_date_raw}, End: {end_date_raw}")

    # 3. Lookup Data
    # Uses the 'lookup_stock_price_range' function created previously
    data_list, actual_bounds = lookup_stock_price_range(ticker, start_datestr, end_datestr)

    if data_list is None:
        return respond_error(f"No data found for {ticker} between {start_datestr} and {end_datestr}", 404)

    actual_start, actual_end = actual_bounds

    # 4. Construct Response
    out = {
        "ticker": ticker,
        "request_start": start_datestr,
        "request_end": end_datestr,
        "actual_start": actual_start,
        "actual_end": actual_end,
        "count": len(data_list),
        "history": data_list
    }

    return jsonify(out)


@app.route("/query/option_history", methods=["GET"])
def query_option_history():
    """
    Query OHLC history for a single option contract over a date range using Multi-Threading.
    """
    ticker = request.args.get("ticker")
    start_date_raw = request.args.get("start_date")
    end_date_raw = request.args.get("end_date")

    # 1. Validation
    if not ticker or not start_date_raw:
        return respond_error("ticker and start_date required")
    
    if not end_date_raw:
        end_date_raw = start_date_raw

    try:
        meta = parse_option_ticker(ticker)
        s_dt = parse_date_like(start_date_raw)
        e_dt = parse_date_like(end_date_raw)
    except ValueError as e:
        return respond_error(f"Input error: {str(e)}")

    try:
        all_dates = pd.date_range(start=s_dt, end=e_dt, freq='D')
    except Exception:
        return respond_error("Invalid date range")

    # Pre-calculate candidates to avoid doing it inside every thread
    cand = {ticker, _strip_prefix(ticker, "O:"), f"O:{_strip_prefix(ticker, 'O:')}"}
    underlying = meta["underlying"]

    # ---------------------------------------------------------
    # WORKER FUNCTION
    # ---------------------------------------------------------
    def fetch_single_day(dt):
        """
        Helper function to be run in a separate thread.
        Returns a dict if data exists, or None.
        """
        d_str = to_datestr(dt)
        try:
            # Assuming load_option_day is thread-safe (read-only file I/O usually is)
            df = load_option_day(underlying, d_str)
            
            if df is None or df.empty:
                return None
            
            # Filter for specific option
            sub = df[df["ticker"].isin(cand)]
            if sub.empty:
                return None
            
            r = sub.iloc[0]
            
            # Return valid record
            return {
                "date": d_str,
                "open": float(r["open"]) if pd.notna(r["open"]) else None,
                "high": float(r["high"]) if pd.notna(r["high"]) else None,
                "low": float(r["low"]) if pd.notna(r["low"]) else None,
                "close": float(r["close"]) if pd.notna(r["close"]) else None,
                "volume": int(r["volume"]) if pd.notna(r["volume"]) else None,
            }
        except Exception:
            # If a file is corrupt or read fails, just skip this day
            return None

    # ---------------------------------------------------------
    # MULTI-THREADED EXECUTION
    # ---------------------------------------------------------
    # Cap workers at 20 (or similar) to avoid opening too many file handles at once
    max_workers = min(20, len(all_dates))
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # executor.map executes calls asynchronously but yields results 
        # in the SAME order as the input 'all_dates'
        results_iter = executor.map(fetch_single_day, all_dates)

    # Filter out None results (days with no data)
    history = [r for r in results_iter if r is not None]

    # ---------------------------------------------------------
    # RESPONSE
    # ---------------------------------------------------------
    if not history:
        return respond_error(f"No data found for {ticker} in range {start_date_raw} to {end_date_raw}", 404)

    return jsonify({
        "ticker": ticker,
        "underlying": underlying,
        "expiry": meta["expiry"],
        "type": meta["type"],
        "strike": float(meta["strike"]),
        "request_start": to_datestr(s_dt),
        "request_end": to_datestr(e_dt),
        "actual_start": history[0]["date"],
        "actual_end": history[-1]["date"],
        "count": len(history),
        "history": history
    })

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # By default the server listens on all interfaces on port 19019.
    # Set PORT in the environment to override.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "19019")), debug=False)
