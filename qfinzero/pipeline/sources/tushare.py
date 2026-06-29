"""tushare source reader (CN A-shares).

Raw layout (read in place):
  cn/daily/<ts_code>.parquet      ts_code, trade_date(YYYYMMDD str), open, high,
                                  low, close, pre_close, vol(手 = 100-share lots), amount
  cn/dividend/<ts_code>.parquet   div_proc, stk_div, cash_div, cash_div_tax, ex_date, ...

CN is daily-only (tushare has no minute bars here). ``vol`` is in 手 (lots) and is
multiplied by 100 to get shares; ``transactions`` is not provided (NULL).
ticker keeps the tushare ``ts_code`` form (e.g. ``000001.SZ``), disjoint from the
US ticker namespace so CN and US can coexist in one store.
"""

from __future__ import annotations

from pathlib import Path

from ..engine import _lit


def daily_glob(cn_daily_dir: Path) -> str:
    return _lit(cn_daily_dir / "*.parquet")


def dividend_glob(cn_dividend_dir: Path) -> str:
    return _lit(cn_dividend_dir / "*.parquet")


def all_daily_sql(glob: str, start: str | None, end: str | None) -> str:
    """Project every CN daily row in range into the UPQ stock_daily schema.

    Read once (the per-symbol glob is scanned a single time); the converter then
    partitions the resulting temp table by date in memory.
    """
    where = []
    if start:
        where.append(f"trade_date >= '{start.replace('-', '')}'")
    if end:
        where.append(f"trade_date <= '{end.replace('-', '')}'")
    clause = (" AND " + " AND ".join(where)) if where else ""
    return f"""
        SELECT
            CAST(ts_code AS VARCHAR) AS ticker,
            strptime(trade_date, '%Y%m%d')::DATE AS trade_date,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(close AS DOUBLE) AS close,
            CAST(round(CAST(vol AS DOUBLE) * 100) AS BIGINT) AS volume,
            CAST(NULL AS BIGINT) AS transactions
        FROM read_parquet('{glob}', union_by_name=true)
        WHERE trade_date IS NOT NULL AND trade_date <> ''{clause}
    """
