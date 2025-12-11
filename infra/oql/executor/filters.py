"""
Common filter utilities for WHERE and HAVING clauses.
- Role-aware WHERE: only applies conditions for the given leg role (L/S/F/B/C/P/SC/LC/SP/LP/L1/L2).
- Moneyness shortcuts (ITM/ATM/OTM) are handled here.
- Approx operator `~`: ±5 days for dte, ±10% for other numeric fields.
- Supports operators: >, <, =, >=, <=, !=, ~, and BETWEEN in HAVING.
"""

from typing import List, Optional
import pandas as pd
import numpy as np

from parsing.ast import Condition
from executor import config


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _as_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _moneyness_mask(df: pd.DataFrame, token: str) -> pd.Series:
    token = (token or "").upper()
    ratio = _as_numeric(df["moneyness_ratio"])

    # If this subset is pure CALL, use call rules; otherwise use put rules.
    is_call_subset = df["type"].nunique() == 1 and df["type"].iloc[0] == "C"

    if token == "ATM":
        return ratio.between(config.ATM_LO, config.ATM_HI)
    if token == "ITM":
        if is_call_subset:
            return ratio > (1.0 + config.ITM_TOL)
        else:
            return ratio < (1.0 - config.ITM_TOL)
    if token == "OTM":
        if is_call_subset:
            return ratio < (1.0 - config.OTM_TOL)
        else:
            return ratio > (1.0 + config.OTM_TOL)
    # Unknown token -> no-op
    return pd.Series(True, index=df.index)


def _approx_mask(series: pd.Series, target: float, field: str) -> pd.Series:
    s = _as_numeric(series)
    if field.lower() == "dte":
        lo, hi = target - config.DTE_TOL_DAYS, target + config.DTE_TOL_DAYS
        return s.between(lo, hi)
    lo, hi = target * (1 - config.NUMERIC_TOL_RATIO), target * (
        1 + config.NUMERIC_TOL_RATIO
    )
    return s.between(lo, hi)


def _compare(series: pd.Series, op: str, value) -> pd.Series:
    if op in ("=", "=="):
        # equality handles both numeric and string
        return series == value
    if op == "!=":
        return series != value
    # For numeric comparisons, coerce to numeric
    s = _as_numeric(series)
    if op == ">":
        return s > float(value)
    if op == "<":
        return s < float(value)
    if op == ">=":
        return s >= float(value)
    if op == "<=":
        return s <= float(value)
    if op == "~":
        return _approx_mask(series, float(value), series.name or "")
    # Fallback: no-op
    return pd.Series(True, index=series.index)


def apply_where(
    df: pd.DataFrame, role: str, conditions: List[Condition]
) -> pd.DataFrame:
    """Apply role-specific WHERE filters to a subset dataframe.

    Column names are matched case-insensitively so that fields like
    'Dte', 'Strike', 'Delta' in OQL map correctly to 'dte', 'strike',
    'delta' in the underlying DataFrame.
    """
    if df is None or df.empty:
        return df

    # case-insensitive column name map
    name_map = {c.lower(): c for c in df.columns}

    mask = pd.Series(True, index=df.index)

    for c in conditions:
        if c.role != role:
            continue

        col = c.field  # e.g. "Dte", "Strike"
        op = c.op
        val = c.val
        col_key = col.lower()

        # Special handling for logical "Moneyness" (ITM/ATM/OTM)
        if col_key == "moneyness":
            mask &= _moneyness_mask(df, val)
            continue

        # Map to real DataFrame column name (case-insensitive)
        real_col = name_map.get(col_key)
        if real_col is None:
            # Unknown column -> ignore this condition
            continue

        series = df[real_col]
        num = _to_float(val)

        # If value is numeric and op is not "~", compare numerically
        if num is not None and op != "~":
            mask &= _compare(series, op, num)
        elif op == "~" and num is not None:
            # Approx operator uses numeric tolerance
            mask &= _compare(series, op, num)
        else:
            # Non-numeric equality/inequality (e.g. type = 'C')
            if op in ("=", "==", "!="):
                mask &= _compare(series.astype(str), op, str(val))

    return df[mask]



def apply_having(df: pd.DataFrame, conditions: List[Condition]) -> pd.DataFrame:
    """Apply post-aggregation (combo-level) filters like net_* columns.

    Supports numeric comparisons and BETWEEN:
      - max_loss <= 300
      - rr_ratio >= 2
      - net_delta BETWEEN -0.1 AND 0.1
    """
    if df is None or df.empty or not conditions:
        return df

    out = df
    name_map = {c.lower(): c for c in out.columns}

    for c in conditions:
        col_key = c.field.lower()
        real_col = name_map.get(col_key)
        if real_col is None:
            continue

        num = _to_float(c.val)
        series = out[real_col]

        if num is not None:
            # numeric compare
            out = out[_compare(series, c.op, num)]
        else:
            # string compare for = / !=
            if c.op in ("=", "==", "!="):
                out = out[_compare(series.astype(str), c.op, c.val)]

    return out
