from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import PRICES_H5_PATH
from utils import _flatten_cols, _match_col


@lru_cache(maxsize=1)
def _price_keys() -> List[str]:
    """Return all keys present in the price HDF5 file."""
    try:
        with pd.HDFStore(PRICES_H5_PATH, "r") as st:
            return st.keys()
    except Exception:
        return []


def get_price_keys() -> List[str]:
    return list(_price_keys())


def has_ticker_table(ticker: str) -> Optional[str]:
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
def lookup_stock_price(
    ticker: str,
    date_str: str,
    asof: bool = True,
) -> Tuple[Optional[Dict], Optional[str]]:
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
    key = has_ticker_table(ticker)
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

    return {"open": o, "close": c, "high": h, "low": l}, used_ts.strftime("%Y-%m-%d")

@lru_cache(maxsize=4096)
def lookup_stock_price_range(
    ticker: str,
    start_date_str: str,
    end_date_str: str,
) -> Tuple[Optional[List[Dict]], Optional[Tuple[str, str]]]:
    """
    Look up OHLC prices for a stock ticker within a date range.
    
    Automatically handles out-of-bounds dates by clamping the start and end 
    to the available data limits (min/max index).

    Args:
        ticker: Stock ticker symbol.
        start_date_str: Request start date 'YYYY-MM-DD'.
        end_date_str: Request end date 'YYYY-MM-DD'.

    Returns:
        (data_list, (actual_start_str, actual_end_str))
            - data_list: List of dicts [{'date', 'open', 'high'...}, ...]
            - actual_start/end: The actual dates used (after clamping), or None if no overlap.
    """
    key = has_ticker_table(ticker)
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
    
    # Ensure index is sorted for efficient slicing
    df.sort_index(inplace=True)

    # 2) Flatten columns 
    cols_flat = _flatten_cols(df.columns)
    df.columns = cols_flat

    # 3) Build robust candidate names for OHLC
    open_cands = ["Open", "open", f"Open::{ticker}", f"open::{ticker}", f"{ticker}::Open", f"{ticker}::open"]
    high_cands = ["High", "high", f"High::{ticker}", f"high::{ticker}", f"{ticker}::High", f"{ticker}::high"]
    low_cands = ["Low", "low", f"Low::{ticker}", f"low::{ticker}", f"{ticker}::Low", f"{ticker}::low"]
    close_cands = ["Close", "close", f"Close::{ticker}", f"close::{ticker}", f"{ticker}::Close", f"{ticker}::close"]

    try:
        col_open = _match_col(df.columns.tolist(), open_cands, pos_fallback=0)
        col_high = _match_col(df.columns.tolist(), high_cands, pos_fallback=1)
        col_low = _match_col(df.columns.tolist(), low_cands, pos_fallback=2)
        col_close = _match_col(df.columns.tolist(), close_cands, pos_fallback=3)
    except Exception:
        return None, None

    # 4) Handle Date Bounds (Safety & Auto-reset)
    req_start = pd.to_datetime(start_date_str)
    req_end = pd.to_datetime(end_date_str)
    
    min_avail = df.index[0]
    max_avail = df.index[-1]

    # Check for zero overlap
    if req_start > max_avail or req_end < min_avail:
        return None, None

    # Clamp (Auto-reset) logic
    # Use the later of requested start vs available start
    actual_start = max(req_start, min_avail)
    # Use the earlier of requested end vs available end
    actual_end = min(req_end, max_avail)

    # 5) Slice Data
    # Note: loc includes the endpoint
    subset = df.loc[actual_start:actual_end]
    
    if subset.empty:
        return None, None

    # 6) Build Payload
    results = []
    
    # Iterate through rows. Note: itertuples is generally faster than iterrows
    for row in subset.itertuples(index=True):
        try:
            # getattr is safer for dynamic column names found via _match_col
            # However, since we have column names as strings, we might need to map them 
            # to the namedtuple attributes or just use standard dict access if we didn't use itertuples.
            # Sticking to standard indexing for safety with the variable column names:
            
            ts = row.Index
            
            # Re-access using the dataframe logic to be safe with the specific column names resolved earlier
            # (Fetching by integer location would be faster, but we need to be robust to col position)
            # To optimize, we can use the subset's direct access:
            
            o = float(subset.at[ts, col_open])
            h = float(subset.at[ts, col_high])
            l = float(subset.at[ts, col_low])
            c = float(subset.at[ts, col_close])

            results.append({
                "date": ts.strftime("%Y-%m-%d"),
                "open": o,
                "high": h,
                "low": l,
                "close": c
            })
        except Exception:
            continue

    return results, (actual_start.strftime("%Y-%m-%d"), actual_end.strftime("%Y-%m-%d"))