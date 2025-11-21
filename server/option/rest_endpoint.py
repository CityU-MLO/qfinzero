#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import bisect
import math
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS

# ---------------------------------------------------------------------
# External Greeks / IV utilities
# ---------------------------------------------------------------------
try:
    # Greeks & IV utilities from the internal infra package.
    # These implement Black-Scholes pricing, implied volatility, and greeks.
    from infra.oql.utils.greeks import (
        yearfrac as greeks_yearfrac,
        build_rate_lookup as greeks_build_rate_lookup,
        implied_vol as greeks_implied_vol,
        bs_greeks as greeks_bs_greeks,
        compute_iv_and_greeks_timeseries,
    )
except ImportError as e:
    # The server can still start without these; endpoints that depend on them
    # will return a clear error to the client.
    greeks_import_error = e
    greeks_yearfrac = None
    greeks_build_rate_lookup = None
    greeks_implied_vol = None
    greeks_bs_greeks = None
    compute_iv_and_greeks_timeseries = None

try:
    # Optional helper - not strictly required in this file, but imported for
    # completeness and potential future use.
    from infra.oql.utils.iv_infer import compute_iv_series  # noqa: F401
except ImportError:
    compute_iv_series = None

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
OPTIONS_H5_PATH = os.getenv("OPTIONS_H5_PATH", "/home/hluo/OptionBench/data/assets/options_structured.h5")
PRICES_H5_PATH = os.getenv("PRICES_H5_PATH", "/home/hluo/OptionBench/data/assets/prices_2025.h5")
RATES_CSV_PATH = os.getenv("RATES_CSV_PATH", "/home/hluo/OptionBench/data/assets/treasury_yields.csv")

DATE_FMT = "%Y-%m-%d"

# ---------------------------------------------------------------------
# Small utils
# ---------------------------------------------------------------------
def respond_error(msg: str, status: int = 400):
    """Standard JSON error response helper."""
    return jsonify({"error": msg}), status


def parse_date_like(v: str) -> pd.Timestamp:
    """Parse anything date-like into a normalized (00:00) pandas Timestamp."""
    return pd.to_datetime(v).normalize()


def to_datestr(ts: pd.Timestamp) -> str:
    """Format a pandas Timestamp as YYYY-MM-DD."""
    return ts.strftime(DATE_FMT)


def _strip_prefix(s: str, prefix: str) -> str:
    """Remove a prefix from a string if present."""
    return s[len(prefix):] if isinstance(s, str) and s.startswith(prefix) else s


def _flatten_cols(cols) -> List[str]:
    """
    Return a list of string column names, flattening any MultiIndex columns
    into a single level joined by '::', e.g. ('Open','NVDA') -> 'Open::NVDA'.
    """
    out = []
    for c in cols:
        if isinstance(c, tuple):
            out.append("::".join(str(x) for x in c))
        else:
            out.append(str(c))
    return out


def _match_col(cols: List[str], candidates: List[str], pos_fallback: Optional[int] = None) -> str:
    """
    Case-insensitive column matcher with positional fallback.
    Returns the actual column name from 'cols'.

    Args:
        cols:       List of available column names.
        candidates: Candidate names to try, in priority order.
        pos_fallback:
            If no candidates match (case-insensitive), fall back to this
            positional index (e.g. 0 -> first column).

    Raises:
        KeyError if nothing matches and no valid fallback is provided.
    """
    lower_map = {c.lower().strip(): c for c in cols}
    for cand in candidates:
        key = str(cand).lower().strip()
        if key in lower_map:
            return lower_map[key]
    if pos_fallback is not None and 0 <= pos_fallback < len(cols):
        return cols[pos_fallback]
    raise KeyError(f"No column match in {cols} for {candidates}, and no valid fallback.")


def _to_float_or_none(x) -> Optional[float]:
    """Convert a value to float, mapping NaN / inf / None to None."""
    try:
        v = float(x)
    except Exception:
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v

# ---------------------------------------------------------------------
# OPRA parser (for option tickers)
# ---------------------------------------------------------------------
OPRA_PATTERN = re.compile(
    r"^(?:O:)?(?P<underlying>[A-Z0-9\.]+)"
    r"(?P<expiry>\d{6})(?P<type>[CP])(?P<strike>\d{8})$"
)


def parse_option_ticker(ticker: str) -> Dict:
    """
    Parse an OPRA-style option ticker into its components.

    Example: O:NVDA250117C00300000

    Returns a dictionary with keys:
        - underlying: 'NVDA'
        - expiry:    '2025-01-17'
        - type:      'call' or 'put'
        - strike:    float strike price
    """
    m = OPRA_PATTERN.match(ticker)
    if not m:
        raise ValueError(f"Invalid OPRA ticker format: {ticker}")
    g = m.groupdict()
    expiry = pd.to_datetime(g["expiry"], format="%y%m%d")
    strike = float(g["strike"]) / 1000.0
    return {
        "underlying": g["underlying"],
        "expiry": expiry.strftime(DATE_FMT),
        "type": "call" if g["type"] == "C" else "put",
        "strike": strike,
    }

# ---------------------------------------------------------------------
# Options H5 helpers
# ---------------------------------------------------------------------
@lru_cache(maxsize=1)
def _opt_idx() -> pd.DataFrame:
    """Index of all option tickers, first seen dates, and expiries."""
    with pd.HDFStore(OPTIONS_H5_PATH, "r") as st:
        df = st["/index/ticker_first_seen"].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.normalize()
    return df


@lru_cache(maxsize=1)
def _opt_keys() -> List[str]:
    """List of all keys present in the options HDF5 file."""
    with pd.HDFStore(OPTIONS_H5_PATH, "r") as st:
        return st.keys()


@lru_cache(maxsize=1)
def _underlyings() -> List[str]:
    """Sorted list of all underlying tickers that have listed options."""
    return sorted(_opt_idx()["underlying"].astype(str).unique().tolist())


@lru_cache(maxsize=1)
def _option_tickers() -> List[str]:
    """Sorted list of all option tickers (OPRA format) in the dataset."""
    return sorted(_opt_idx()["ticker"].astype(str).unique().tolist())


@lru_cache(maxsize=1)
def _trading_days() -> List[str]:
    """
    Extract all available trading days from the options HDF5 structure.

    Keys are of the form '/data/YYYY-MM-DD/UNDERLYING'.
    """
    days = set()
    for k in _opt_keys():
        parts = k.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "data":
            days.add(parts[1])
    return sorted(days)


def _load_option_day(underlying: str, date_str: str) -> Optional[pd.DataFrame]:
    """
    Load all option contracts for a given underlying and trade date.

    Returns:
        DataFrame with (at least) columns:
            ['date', 'ticker', 'type', 'strike', 'expiry',
             'volume', 'open', 'close', 'high', 'low', ...]
        or None if the (date, underlying) pair is missing.
    """
    key = f"/data/{date_str}/{underlying}"
    with pd.HDFStore(OPTIONS_H5_PATH, "r") as st:
        if key not in st.keys():
            return None
        df = st[key].copy()
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.normalize()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df

# ---------------------------------------------------------------------
# Rates helpers
# ---------------------------------------------------------------------
@lru_cache(maxsize=1)
def _rates_df() -> pd.DataFrame:
    """
    Load the raw Treasury yield curve data.

    The CSV is expected to have at least a date column (exact name does not
    matter; it will be normalized to datetime and used as index). Other
    columns are treated as yield-curve pillars (e.g. yield_1_year, ...).
    """
    df = pd.read_csv(RATES_CSV_PATH)
    # Detect date column
    dcol = None
    for c in df.columns:
        if str(c).strip().lower() == "date":
            dcol = c
            break
    if dcol is None:
        dcol = df.columns[0]
    df[dcol] = pd.to_datetime(df[dcol]).dt.normalize()
    return df.set_index(dcol).sort_index()


@lru_cache(maxsize=1)
def _rates_curve_df() -> pd.DataFrame:
    """
    Convert the internal rates DataFrame (indexed by date) into the shape
    expected by infra.oql.utils.greeks.build_rate_lookup, i.e. a regular
    DataFrame with:
        - a 'date' column (datetime)
        - yield columns such as 'yield_1_year', 'yield_5_year', 'yield_10_year'
          expressed in percentage points.
    """
    base = _rates_df().reset_index()
    # Ensure there is a 'date' column
    if "date" not in base.columns:
        # If the index column name was different, rename the first column to 'date'
        base = base.rename(columns={base.columns[0]: "date"})
    return base


@lru_cache(maxsize=1)
def _rate_lookup():
    """
    Build and cache a zero-rate lookup callable using the greeks utilities.

    Returns:
        A function r = f(trade_date, T_years) or None if the greeks module
        is not available.
    """
    if greeks_build_rate_lookup is None:
        return None
    curve_df = _rates_curve_df()
    return greeks_build_rate_lookup(curve_df)

# ---------------------------------------------------------------------
# PRICES: per-ticker layout
#
#   keys: "/_meta", "/NVDA", "/AAPL", ...
#   each table: DatetimeIndex, columns:
#       Open, High, Low, Close, Adj Close, Volume
#
#   NOTE: columns might be MultiIndex like ('Open','NVDA') depending on the
#   writer - we flatten them to a single level using '::' as a separator.
# ---------------------------------------------------------------------
@lru_cache(maxsize=1)
def _price_keys() -> List[str]:
    """Return all keys present in the price HDF5 file."""
    try:
        with pd.HDFStore(PRICES_H5_PATH, "r") as st:
            return st.keys()
    except Exception:
        return []


def _has_ticker_table(ticker: str) -> Optional[str]:
    """
    Return the HDF5 key that exists for this ticker, e.g. '/NVDA'.

    Matching is case-insensitive and tries '/TICKER', '/ticker', '/ticker'.
    """
    keys = set(_price_keys())
    for k in (f"/{ticker}", f"/{ticker.upper()}", f"/{ticker.lower()}"):
        if k in keys:
            return k
    return None


def _normalize_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    """
    Ensure the DataFrame has a tz-naive daily DatetimeIndex.

    This is robust to cases where the index is stored as a column or with a
    timezone attached.
    """
    try:
        idx = pd.to_datetime(df.index)
    except Exception:
        idx = None
    if idx is None or pd.isna(idx).all():
        for c in ("index", "Date", "date"):
            if c in df.columns:
                try:
                    idx = pd.to_datetime(df[c])
                    break
                except Exception:
                    pass
    if idx is None:
        raise ValueError("Could not determine datetime index for price table.")
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


@lru_cache(maxsize=4096)
def _lookup_stock_price(ticker: str, date_str: str, asof: bool = True) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Look up OHLC prices for a stock ticker on a given date.

    The function reads '/{ticker}' directly from the prices HDF5 file,
    flattens columns, and then selects the exact (or as-of) row.

    Args:
        ticker: Stock ticker symbol, e.g. 'NVDA'.
        date_str: String date 'YYYY-MM-DD'.
        asof:
            If True, use the last available price before or on the given
            date when there is no exact match.

    Returns:
        (data_dict, used_date_str)
            - data_dict: {'open','high','low','close'} or None if missing.
            - used_date_str: actual date string used for the lookup, or None.
    """
    key = _has_ticker_table(ticker)
    if not key:
        return None, None

    with pd.HDFStore(PRICES_H5_PATH, "r") as st:
        df = st[key]

    if df is None or df.empty:
        return None, None

    # 1) Normalize index
    idx = _normalize_index(df)
    df = df.copy()
    df.index = idx

    # 2) Flatten columns and assign (important when written with MultiIndex)
    cols_flat = _flatten_cols(df.columns)
    df.columns = cols_flat

    # 3) Build robust candidate names for OHLC
    #    try plain ('Open') and both flatten orders ('Open::NVDA', 'NVDA::Open')
    open_cands = ["Open", "open", f"Open::{ticker}", f"open::{ticker}", f"{ticker}::Open", f"{ticker}::open"]
    high_cands = ["High", "high", f"High::{ticker}", f"high::{ticker}", f"{ticker}::High", f"{ticker}::high"]
    low_cands = ["Low", "low", f"Low::{ticker}", f"low::{ticker}", f"{ticker}::Low", f"{ticker}::low"]
    close_cands = ["Close", "close", f"Close::{ticker}", f"close::{ticker}", f"{ticker}::Close", f"{ticker}::close"]

    #    fall back to the standard yfinance order [Open, High, Low, Close, ...]
    try:
        col_open = _match_col(df.columns.tolist(), open_cands, pos_fallback=0)
        col_high = _match_col(df.columns.tolist(), high_cands, pos_fallback=1)
        col_low = _match_col(df.columns.tolist(), low_cands, pos_fallback=2)
        col_close = _match_col(df.columns.tolist(), close_cands, pos_fallback=3)
    except Exception:
        return None, None

    # 4) Exact date else as-of
    target = pd.to_datetime(date_str)
    if target in df.index:
        r = df.loc[target]
        used_ts = target
    else:
        if not asof:
            return None, None
        prior = df[df.index <= target]
        if prior.empty:
            return None, None
        r = prior.iloc[-1]
        used_ts = prior.index[-1]

    # 5) Build payload (handle possible duplicate rows -> DataFrame)
    if isinstance(r, pd.DataFrame):
        r = r.iloc[-1]
    try:
        o = float(r[col_open])
        h = float(r[col_high])
        l = float(r[col_low])
        c = float(r[col_close])
    except KeyError:
        # If the row's index is somehow not flattened (shouldn't happen),
        # try one more time by re-flattening the series index:
        r2 = r.copy()
        r2.index = _flatten_cols(r2.index)
        o = float(r2[col_open])
        h = float(r2[col_high])
        l = float(r2[col_low])
        c = float(r2[col_close])

    return {"open": o, "close": c, "high": h, "low": l}, used_ts.strftime(DATE_FMT)

# ---------------------------------------------------------------------
# Chain helpers
# ---------------------------------------------------------------------
def _nearest_strikes(strikes: List[float], price: float, level: int) -> List[float]:
    """
    Given a list of strikes and a center price, pick strikes in a symmetric
    window around the price (level on each side).
    """
    if level is None or level <= 0 or not strikes:
        return strikes
    uniq = sorted(set(strikes))
    i = bisect.bisect_left(uniq, price)
    below = uniq[max(0, i - level):i]
    above = uniq[i:i + level]
    return sorted(set(below + above))


def _build_chain_json(
    df: pd.DataFrame,
    center_price: Optional[float],
    level: Optional[int],
    include_greeks: bool = False,
) -> Dict[str, Dict[str, List[Dict]]]:
    """
    Convert a raw options DataFrame into a nested JSON-friendly structure:

    {
      "C": {
        "2025-01-17": [ { ... per-contract fields ... }, ... ],
        ...
      },
      "P": {
        "2025-01-17": [ ... ],
        ...
      }
    }

    When include_greeks=True and the columns ['iv','delta','gamma','theta',
    'vega','rho'] are present, these values are attached to each contract
    record (NaNs become null in JSON).
    """
    result: Dict[str, Dict[str, List[Dict]]] = {"C": {}, "P": {}}
    if df is None or df.empty:
        return result

    for t, dft in df.groupby("type"):
        # Normalise group key to 'C' / 'P' if necessary
        t_key = t
        if isinstance(t, str):
            tl = t.strip().lower()
            if tl in ("c", "call"):
                t_key = "C"
            elif tl in ("p", "put"):
                t_key = "P"

        for exp, dfe in dft.groupby("expiry"):
            grp = dfe.sort_values("strike").copy()

            # Level-based strike selection (symmetric around center_price)
            if center_price is not None and level is not None and level > 0:
                keep = _nearest_strikes(grp["strike"].tolist(), center_price, level)
                grp = grp[grp["strike"].isin(keep)]

            payload: List[Dict] = []
            for _, r in grp.iterrows():
                item: Dict[str, Optional[float]] = {
                    "date": pd.to_datetime(r["date"]).strftime(DATE_FMT),
                    "ticker": str(r["ticker"]),
                    "strike": float(r["strike"]),
                    "volume": int(r["volume"]) if pd.notna(r["volume"]) else None,
                    "open": float(r["open"]) if pd.notna(r["open"]) else None,
                    "close": float(r["close"]) if pd.notna(r["close"]) else None,
                    "high": float(r["high"]) if pd.notna(r["high"]) else None,
                    "low": float(r["low"]) if pd.notna(r["low"]) else None,
                    "expiry": pd.to_datetime(r["expiry"]).strftime(DATE_FMT),
                }

                if include_greeks:
                    # Attach IV + greeks if present; map NaNs -> null
                    for gname in ("iv", "delta", "gamma", "theta", "vega", "rho"):
                        if gname in r.index:
                            item[gname] = _to_float_or_none(r[gname])
                        else:
                            item[gname] = None

                payload.append(item)

            result.setdefault(t_key, {})[exp.strftime(DATE_FMT)] = payload

    return result


def _attach_iv_and_greeks_to_chain(df: pd.DataFrame, underlying: str, trade_date: pd.Timestamp) -> pd.DataFrame:
    """
    Compute per-row implied volatility and Black-Scholes greeks for a snapshot
    option chain and attach the results as new columns.

    This uses the compute_iv_and_greeks_timeseries() helper from
    infra.oql.utils.greeks. If the greeks utilities or the rate curve are not
    available, the input DataFrame is returned unchanged.
    """
    if df is None or df.empty:
        return df

    if compute_iv_and_greeks_timeseries is None or greeks_build_rate_lookup is None:
        # Greeks library not available; return raw chain.
        return df

    dt_norm = trade_date.normalize()
    datestr = to_datestr(dt_norm)

    # Underlying price S for this trade date (as-of).
    spot, _ = _lookup_stock_price(underlying, datestr, asof=True)
    if spot is None:
        # Cannot compute greeks without a spot price.
        return df
    S_val = float(spot["close"])

    # Prepare a working copy for the greeks library (so we do not mutate
    # the original chain).
    df_calc = df.copy()

    # Normalize basic fields.
    df_calc["date"] = pd.to_datetime(dt_norm)
    df_calc["expiry"] = pd.to_datetime(df_calc["expiry"]).dt.normalize()
    df_calc["S"] = S_val

    # Map type to 'call' / 'put' for the greeks library.
    def _to_call_put(x):
        if isinstance(x, str):
            xl = x.strip().lower()
            if xl in ("c", "call"):
                return "call"
            if xl in ("p", "put"):
                return "put"
        return x

    df_calc["type"] = df_calc["type"].apply(_to_call_put)

    # Provide a price column name that the helper knows how to use.
    # Priority: bid/ask mid -> option_mid -> option_close -> close.
    if "bid" in df_calc.columns and "ask" in df_calc.columns:
        df_calc["option_mid"] = (df_calc["bid"] + df_calc["ask"]) / 2.0
    elif "option_mid" not in df_calc.columns:
        if "option_close" in df_calc.columns:
            df_calc["option_mid"] = df_calc["option_close"]
        else:
            df_calc["option_mid"] = df_calc["close"]

    curve_df = _rates_curve_df()

    # Ask the library to compute IV and greeks in place.
    df_enriched = compute_iv_and_greeks_timeseries(df_calc, curve_df)

    # Attach IV + greeks back onto a copy of the original chain (preserving
    # the original 'type' codes 'C' / 'P').
    out = df.copy()
    for col in ("iv", "delta", "gamma", "theta", "vega", "rho"):
        if col in df_enriched.columns:
            out[col] = df_enriched[col]
    return out


def _find_option_row_for_ticker(
    contract_ticker: str, trade_date: pd.Timestamp
) -> Tuple[Optional[pd.Series], Optional[pd.DataFrame], Optional[Dict]]:
    """
    Locate the row corresponding to a given OPRA option ticker on a specific
    trade date.

    Returns:
        (row, full_day_df, meta)
            - row:          pandas Series for the contract, or None.
            - full_day_df:  full option chain DataFrame for that date, or None.
            - meta:         parsed OPRA components (underlying, expiry, type, strike).
    """
    try:
        meta = parse_option_ticker(contract_ticker)
    except ValueError:
        return None, None, None

    datestr = to_datestr(trade_date)
    df_day = _load_option_day(meta["underlying"], datestr)
    if df_day is None or df_day.empty:
        return None, None, meta

    cand = {
        contract_ticker,
        _strip_prefix(contract_ticker, "O:"),
        f"O:{_strip_prefix(contract_ticker, 'O:')}",
    }
    sub = df_day[df_day["ticker"].isin(cand)]
    if sub.empty:
        return None, df_day, meta

    row = sub.iloc[0]
    return row, df_day, meta


def _compute_single_option_iv_and_greeks(
    contract_ticker: str, trade_date: pd.Timestamp
) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Compute implied volatility and Black-Scholes greeks for a single option
    contract on a given trade date.

    The function automatically:
        - parses the OPRA ticker to obtain underlying / expiry / type / strike
        - looks up the option close (or mid) price for that date
        - looks up the underlying's spot/close price (as-of)
        - interpolates the risk-free rate from the Treasury curve
        - runs an IV solver + greeks calculator

    Returns:
        (payload, error_message)
            - payload: dict with iv + greeks and meta fields, or None on error
            - error_message: human-readable message when payload is None
    """
    if (
        greeks_yearfrac is None
        or greeks_build_rate_lookup is None
        or greeks_implied_vol is None
        or greeks_bs_greeks is None
    ):
        return None, "Greeks utilities are not available (infra.oql.utils.greeks import failed)."

    row, _, meta = _find_option_row_for_ticker(contract_ticker, trade_date)
    if meta is None:
        return None, f"Invalid OPRA ticker: {contract_ticker}"
    if row is None:
        return None, f"No option data for {contract_ticker} on {to_datestr(trade_date)}."

    datestr = to_datestr(trade_date)

    # Option market price: prefer mid if bid/ask, then 'option_mid', then 'option_close', then 'close'.
    price_source = None
    if "bid" in row.index and "ask" in row.index and pd.notna(row["bid"]) and pd.notna(row["ask"]):
        opt_price = float((row["bid"] + row["ask"]) / 2.0)
        price_source = "mid(bid/ask)"
    elif "option_mid" in row.index and pd.notna(row["option_mid"]):
        opt_price = float(row["option_mid"])
        price_source = "option_mid"
    elif "option_close" in row.index and pd.notna(row["option_close"]):
        opt_price = float(row["option_close"])
        price_source = "option_close"
    elif "close" in row.index and pd.notna(row["close"]):
        opt_price = float(row["close"])
        price_source = "close"
    else:
        return None, "No usable option price column (need bid/ask, option_mid, option_close, or close)."

    # Underlying spot/close
    spot_data, spot_asof = _lookup_stock_price(meta["underlying"], datestr, asof=True)
    if spot_data is None:
        return None, f"No underlying price for {meta['underlying']} on/before {datestr}."
    S = float(spot_data["close"])

    # Expiry date: use the stored 'expiry' if available; fall back to OPRA meta.
    if "expiry" in row.index and pd.notna(row["expiry"]):
        expiry_ts = pd.to_datetime(row["expiry"]).normalize()
    else:
        expiry_ts = pd.to_datetime(meta["expiry"]).normalize()

    # Time to expiry in years (ACT/365).
    T = greeks_yearfrac(trade_date, expiry_ts)

    # Risk-free rate lookup: piecewise-linear interpolation on 1Y/5Y/10Y pillars.
    rate_fn = _rate_lookup()
    if rate_fn is None:
        return None, "Failed to construct rate lookup from Treasury curve."

    r = float(rate_fn(trade_date, max(T, 1e-6)))

    # Implied volatility (via Brent root finder + Newton fallback).
    is_call = (meta["type"].lower() == "call")
    iv = greeks_implied_vol(opt_price, S, float(meta["strike"]), max(T, 1e-6), r, is_call=is_call)

    # Greeks at the solved IV (delta/gamma/theta/vega/rho).
    greeks_dict = greeks_bs_greeks(S, float(meta["strike"]), max(T, 1e-6), r, iv, is_call=is_call)

    payload = {
        "date": datestr,
        "ticker": str(row["ticker"]),
        "underlying": meta["underlying"],
        "expiry": expiry_ts.strftime(DATE_FMT),
        "type": meta["type"],  # 'call' or 'put'
        "strike": float(meta["strike"]),
        "option_price": _to_float_or_none(opt_price),
        "price_source": price_source,
        "underlying_price": _to_float_or_none(S),
        "underlying_price_asof": spot_asof,
        "T": _to_float_or_none(T),
        "rate": _to_float_or_none(r),
        "iv": _to_float_or_none(iv),
        "delta": _to_float_or_none(greeks_dict.get("delta")),
        "gamma": _to_float_or_none(greeks_dict.get("gamma")),
        "theta": _to_float_or_none(greeks_dict.get("theta")),
        "vega": _to_float_or_none(greeks_dict.get("vega")),
        "rho": _to_float_or_none(greeks_dict.get("rho")),
    }
    return payload, None

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
    nvda_key = _has_ticker_table("NVDA")
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
        tickers = _option_tickers()
    else:
        tickers = _underlyings()
    return jsonify({"count": len(tickers), "tickers": tickers})


@app.route("/collect/trading_days", methods=["GET"])
def collect_trading_days():
    """Return all trading days for which we have any option data."""
    days = _trading_days()
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
    data, used = _lookup_stock_price(ticker, datestr, asof=asof_flag)
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
    df = _load_option_day(meta["underlying"], datestr)
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

# ------------ option_greeks (new) ------------
@app.route("/query/option_greeks", methods=["GET"])
def query_option_greeks():
    """
    Compute implied volatility and greeks for a single option contract.

    Query params:
        ticker: OPRA option ticker, e.g. O:NVDA250117C00300000
        date:   trade date (YYYY-MM-DD)

    The backend will:
        - parse the OPRA ticker,
        - look up option and underlying prices,
        - interpolate the risk-free rate from the Treasury curve,
        - solve for IV, and
        - compute BS greeks (delta, gamma, theta, vega, rho).

    Example:
        /query/option_greeks?ticker=O:NVDA250117C00300000&date=2025-01-10
    """
    ticker = request.args.get("ticker")
    date = request.args.get("date")
    if not ticker or not date:
        return respond_error("ticker and date required")
    try:
        trade_date = parse_date_like(date)
    except Exception:
        return respond_error(f"invalid date: {date}")

    payload, err = _compute_single_option_iv_and_greeks(ticker, trade_date)
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
    dt = parse_date_like(date)
    df = _rates_df()
    if dt not in df.index:
        prior = df.index[df.index <= dt]
        if prior.empty:
            return respond_error("no data on/before date", 404)
        dt = prior.max()
    rec = df.loc[dt].to_dict()
    out = {k: (float(v) if pd.notna(v) else None) for k, v in rec.items()}
    return jsonify({"asof": to_datestr(dt), "rates": out})

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

    Example:
        /query/chain?ticker=NVDA&date=2025-01-10&type=put&expiry_days=7&level=2&require_greek=true
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
        px, asof_used = _lookup_stock_price(ticker, datestr, asof=True)
        center_price = float(px["close"]) if px else None

    df = _load_option_day(ticker, datestr)
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
        df = _attach_iv_and_greeks_to_chain(df, ticker, date_ts)

    data = _build_chain_json(df, center_price, level, include_greeks=require_greek)
    meta = {"center_price": center_price, "asof": asof_used, "require_greek": require_greek}
    return jsonify({"underlying": ticker, "date": datestr, "meta": meta, "data": data})

# ------------ IV surface (new) ------------
@app.route("/query/iv_surface", methods=["GET"])
def query_iv_surface():
    """
    Compute an implied-volatility surface for the underlying associated
    with a given OPRA option ticker on a specified trade date.

    Query params:
        ticker: OPRA option ticker, e.g. O:NVDA250117C00300000
        date:   trade date (YYYY-MM-DD)

    Internally we:
        - parse the OPRA ticker to obtain the underlying,
        - load the full option chain for that underlying and date,
        - look up the underlying close,
        - compute IV + greeks for every contract, and
        - return a chain-like JSON structure with per-contract IV attached.

    This endpoint focuses on the surface of IV; the charting is expected to
    be done by the client based on the returned JSON.
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

    df = _load_option_day(meta["underlying"], datestr)
    if df is None or df.empty:
        return respond_error(f"No option data for {meta['underlying']} on {datestr}", 404)

    if compute_iv_and_greeks_timeseries is None or greeks_build_rate_lookup is None:
        return respond_error("Greeks utilities are not available (infra.oql.utils.greeks import failed).", 500)

    # Enrich the full chain with IV + greeks.
    df = _attach_iv_and_greeks_to_chain(df, meta["underlying"], date_ts)

    # Underlying close (used as center price for strike selection and for
    # client-side plotting convenience).
    px, asof_used = _lookup_stock_price(meta["underlying"], datestr, asof=True)
    center_price = float(px["close"]) if px else None

    data = _build_chain_json(df, center_price, level=None, include_greeks=True)
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

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # By default the server listens on all interfaces on port 19019.
    # Set PORT in the environment to override.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "19019")), debug=False)
