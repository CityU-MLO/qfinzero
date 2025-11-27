import re
from functools import lru_cache
from typing import Dict, List, Optional

import pandas as pd

from config import OPTIONS_H5_PATH, DATE_FMT


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


def get_option_index() -> pd.DataFrame:
    """Public accessor for the option index."""
    return _opt_idx().copy()


@lru_cache(maxsize=1)
def _opt_keys() -> List[str]:
    """List of all keys present in the options HDF5 file."""
    with pd.HDFStore(OPTIONS_H5_PATH, "r") as st:
        return st.keys()


def get_option_keys() -> List[str]:
    """Public accessor for HDF5 option keys."""
    return list(_opt_keys())


@lru_cache(maxsize=1)
def _underlyings() -> List[str]:
    """Sorted list of all underlying tickers that have listed options."""
    return sorted(_opt_idx()["underlying"].astype(str).unique().tolist())


def get_underlyings() -> List[str]:
    return list(_underlyings())


@lru_cache(maxsize=1)
def _option_tickers() -> List[str]:
    """Sorted list of all option tickers (OPRA format) in the dataset."""
    return sorted(_opt_idx()["ticker"].astype(str).unique().tolist())


def get_option_tickers() -> List[str]:
    return list(_option_tickers())


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


def get_trading_days() -> List[str]:
    return list(_trading_days())


def load_option_day(underlying: str, date_str: str) -> Optional[pd.DataFrame]:
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
