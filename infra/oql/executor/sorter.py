"""
Sorting helpers for ORDER BY with multiple keys.
- Column names are matched case-insensitively.
- Unknown columns are ignored.
"""

from typing import List
import pandas as pd
from parsing.ast import OrderSpec


def sort_df(df: pd.DataFrame, order: List[OrderSpec]) -> pd.DataFrame:
    if df.empty or not order:
        return df

    name_map = {c.lower(): c for c in df.columns}
    by_cols, ascending = [], []

    for spec in order:
        key = spec.col.strip()
        real = name_map.get(key.lower())
        if not real:
            continue
        by_cols.append(real)
        ascending.append(spec.direction.upper() == "ASC")

    if not by_cols:
        return df
    return df.sort_values(by=by_cols, ascending=ascending, kind="mergesort")
