from functools import lru_cache
from typing import Dict, Tuple

import pandas as pd

from config import RATES_CSV_PATH
from utils import parse_date_like
from greeks_utils import greeks_build_rate_lookup


@lru_cache(maxsize=1)
def _rates_df() -> pd.DataFrame:
    """
    Load the raw Treasury yield curve data.

    The CSV is expected to have at least a date column (exact name does not
    matter; it will be normalized to datetime and used as index). Other
    columns are treated as yield-curve pillars.
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
    expected by greeks_build_rate_lookup, i.e. a regular DataFrame with:
        - a 'date' column (datetime)
        - yield columns such as 'yield_1_year', 'yield_5_year', ...
    """
    base = _rates_df().reset_index()
    if "date" not in base.columns:
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


def get_rates_df() -> pd.DataFrame:
    return _rates_df()


def get_rates_curve_df() -> pd.DataFrame:
    return _rates_curve_df()


def get_rate_lookup():
    return _rate_lookup()


def get_rates_for_date(date_like) -> Tuple[pd.Timestamp, Dict[str, float]]:
    """
    Return (asof_date, rates_dict) for the requested date, falling back to
    the most recent available date on or before it.
    """
    if isinstance(date_like, pd.Timestamp):
        dt = date_like.normalize()
    else:
        dt = parse_date_like(date_like)

    df = _rates_df()
    if dt not in df.index:
        prior = df.index[df.index <= dt]
        if prior.empty:
            raise KeyError("no data on/before date")
        dt = prior.max()
    rec = df.loc[dt].to_dict()
    out = {k: (float(v) if pd.notna(v) else None) for k, v in rec.items()}
    return dt, out
