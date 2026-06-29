"""Raw-source + converted-storage registry.

Scans the in-place raw vendor dirs and the UPQ storage root and reports what
data exists (markets, assets, resolutions, date ranges, counts) plus what has
been converted. Backs ``qfz-data status``.
"""

from __future__ import annotations

from pathlib import Path

from .engine import _lit, connect
from .paths import PipelinePaths, resolve
from .sources import massive


def _dated_range(root: Path) -> dict:
    files = massive.list_dated_files(root, None, None)
    if not files:
        return {"present": False, "files": 0}
    return {
        "present": True,
        "files": len(files),
        "start": files[0].trade_date,
        "end": files[-1].trade_date,
    }


def _count_files(d: Path, pattern: str = "*") -> int:
    return sum(1 for _ in d.glob(pattern)) if d.is_dir() else 0


def scan_raw(p: PipelinePaths, con=None) -> dict:
    out: dict = {"massive": {}, "tushare": {}}

    out["massive"]["root"] = str(p.massive)
    out["massive"]["stock_daily"] = _dated_range(p.massive_stock_day)
    out["massive"]["stock_minute"] = _dated_range(p.massive_stock_minute)
    out["massive"]["option_day"] = _dated_range(p.massive_option_day)
    out["massive"]["option_minute"] = _dated_range(p.massive_option_minute)
    out["massive"]["rates"] = {"present": p.massive_treasury.exists()}
    out["massive"]["splits_files"] = _count_files(p.massive_splits, "*.jsonl")
    out["massive"]["dividends_files"] = _count_files(p.massive_dividends, "*.jsonl")

    out["tushare"]["root"] = str(p.tushare)
    n_cn = _count_files(p.tushare_cn_daily, "*.parquet")
    cn = {"present": n_cn > 0, "symbols": n_cn}
    if n_cn:
        own = con is None
        con = con or connect()
        try:
            glob = _lit(p.tushare_cn_daily / "*.parquet")
            row = con.execute(
                f"SELECT MIN(trade_date), MAX(trade_date) FROM read_parquet('{glob}', union_by_name=true)"
            ).fetchone()
            if row and row[0]:
                cn["start"] = f"{row[0][:4]}-{row[0][4:6]}-{row[0][6:]}"
                cn["end"] = f"{row[1][:4]}-{row[1][4:6]}-{row[1][6:]}"
        except Exception as e:  # noqa: BLE001
            cn["error"] = str(e)
        finally:
            if own:
                con.close()
    out["tushare"]["cn_daily"] = cn
    out["tushare"]["cn_dividend_files"] = _count_files(p.tushare_cn_dividend, "*.parquet")
    return out


def scan_storage(p: PipelinePaths) -> dict:
    out: dict = {"root": str(p.storage)}
    for store in ("stock_daily", "stock_minute", "option_day", "option_minute"):
        d = p.store(store)
        parts = sorted(
            x.name[len("trade_date="):]
            for x in d.glob("trade_date=*") if x.is_dir()
        ) if d.is_dir() else []
        out[store] = {
            "partitions": len(parts),
            **({"start": parts[0], "end": parts[-1]} if parts else {}),
        }
    for single in ("rates/rates.parquet", "corporate_actions/corporate_actions.parquet",
                   "dividends/dividends.parquet"):
        out[single] = (p.storage / single).exists()
    return out


def scan(paths: PipelinePaths | None = None) -> dict:
    p = paths or resolve()
    con = connect()
    try:
        return {"raw": scan_raw(p, con), "storage": scan_storage(p)}
    finally:
        con.close()
