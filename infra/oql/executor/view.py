# executor/view.py
"""
Utilities to produce a compact, human-friendly view of strategy results.

Given a raw combo DataFrame (with columns like strike_L1, price_S, net_cost, ...),
`summarize_strategy_df` keeps only key leg features and strategy-level metrics.

`summarize_strategy_with_preview` additionally returns a JSON-friendly dict
for the first raw row, which is useful for logging or LLM consumption.
"""

from __future__ import annotations

from typing import List, Optional, Tuple, Dict, Any
import json

import numpy as np
import pandas as pd


# Leg fields we care about for each role
LEG_BASE_FIELDS: List[str] = [
    "contract_ticker",
    "type",
    "strike",
    "dte",
    "moneyness_ratio",
    "price",
    "volume",
    "delta",
    "theta",
    "vega",
]

# Role suffixes that can appear in column names across all strategies
ROLE_SUFFIXES: List[str] = [
    "_L1", "_S", "_L2",         # ButterflyCall
    "_L", "_S",                 # Vertical spreads
    "_SC", "_LC", "_SP", "_LP", # Iron Condor
    "_C", "_P",                 # Straddle / Strangle
    "_B", "_F",                 # Calendar spreads
    "_O",                       # SingleOption
]

# Strategy-level metrics we want to expose if present
METRIC_FIELDS: List[str] = [
    "spread_width",
    "call_width",
    "put_width",
    "time_gap",
    "net_cost",
    "net_debit",
    "net_credit",
    "max_profit",
    "max_loss",
    "rr_ratio",
    "net_delta",
    "net_gamma",
    "net_theta",
    "net_vega",
    "net_rho",
]


def _pick_symbol_column(df: pd.DataFrame) -> Optional[str]:
    """
    Pick a single symbol column from many duplicated ones, e.g.:
      symbol_L1, symbol_S, symbol_L2, ...
    We just return the first matching column for readability.
    """
    candidates = [c for c in df.columns if c.lower().startswith("symbol")]
    return candidates[0] if candidates else None


def summarize_strategy_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a compact view of a raw combo DataFrame.

    It keeps:
      - one symbol column (if any)
      - expiry_date
      - for each role suffix: contract_ticker, type, strike, dte,
        moneyness_ratio, price, volume, delta, theta, vega (if present)
      - strategy-level metrics defined in METRIC_FIELDS (if present)

    Parameters
    ----------
    df : pd.DataFrame
        Raw strategy output DataFrame from OQLEngine.

    Returns
    -------
    pd.DataFrame
        A reduced DataFrame with only key columns.
    """
    if df is None or df.empty:
        return df

    cols: List[str] = []

    # 1. Underlying / symbol (only one)
    symbol_col = _pick_symbol_column(df)
    if symbol_col is not None:
        cols.append(symbol_col)

    # 2. Expiry date (common for all strategies)
    if "expiry_date" in df.columns:
        cols.append("expiry_date")

    # 3. Leg-level fields per role suffix
    for suffix in ROLE_SUFFIXES:
        for base in LEG_BASE_FIELDS:
            col_name = f"{base}{suffix}"
            if col_name in df.columns:
                cols.append(col_name)

    # 4. Strategy-level metrics
    for m in METRIC_FIELDS:
        if m in df.columns:
            cols.append(m)

    # Remove duplicates while preserving order
    seen = set()
    final_cols: List[str] = []
    for c in cols:
        if c not in seen:
            seen.add(c)
            final_cols.append(c)

    if not final_cols:
        # If nothing matched, just return original df
        return df

    return df[final_cols]


# ---------------------------------------------------------------------------
# Helpers for JSON preview of the first raw combo
# ---------------------------------------------------------------------------

def _to_python_scalar(v: Any) -> Any:
    """
    Convert numpy / pandas scalar types into plain Python types that are
    JSON-serializable (or easily dumped by json.dumps).
    """
    # numpy scalar -> Python scalar
    if isinstance(v, np.generic):
        return v.item()

    # pandas Timestamp -> ISO string
    if isinstance(v, pd.Timestamp):
        return v.isoformat()

    # anything else is kept as-is (str, int, float, None, etc.)
    return v


def first_raw_row_dict(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Return the first raw row as a dict of Python scalars.

    This is meant to be JSON-friendly: numpy / pandas scalars are
    converted to plain Python types.

    If df is empty, returns {}.
    """
    if df is None or df.empty:
        return {}

    row = df.iloc[0]
    return {k: _to_python_scalar(v) for k, v in row.items()}


def first_raw_row_json(df: pd.DataFrame, **json_kwargs: Any) -> str:
    """
    Return the first raw row as a JSON string.

    Parameters
    ----------
    df : pd.DataFrame
        Raw combo DataFrame.
    json_kwargs : dict
        Extra keyword arguments passed to json.dumps, e.g. indent=2.

    Returns
    -------
    str
        JSON string representing the first row (or "{}" if empty).
    """
    d = first_raw_row_dict(df)
    return json.dumps(d, **json_kwargs)


def summarize_strategy_with_preview(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Convenience helper that returns both:
      - summarized combo DataFrame
      - JSON-friendly dict of the first raw row

    This is useful when you want to:
      - show a compact table to the user
      - but also keep a full raw preview for logs / LLM context.

    Returns
    -------
    summary_df : pd.DataFrame
        Reduced DataFrame from summarize_strategy_df(df).
    raw_preview : dict
        First-row preview from first_raw_row_dict(df).
    """
    if df is None or df.empty:
        return df, {}

    summary = summarize_strategy_df(df)
    preview = first_raw_row_dict(df)
    return summary, preview
