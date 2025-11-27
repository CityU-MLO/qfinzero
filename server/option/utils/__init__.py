import math
from typing import List, Optional

import pandas as pd
from flask import jsonify

from config import DATE_FMT


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


def _match_col(
    cols: List[str],
    candidates: List[str],
    pos_fallback: Optional[int] = None,
) -> str:
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
