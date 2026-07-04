"""Data explorer — coverage summaries over the UPQ stores and ESP databases.

Read-only introspection for the Console's Data Explorer: what stores exist, their
date span and size, the symbols inside a store, and how many events ESP holds.
Heavy per-symbol scans are on-demand (the explorer calls :func:`store_symbols`
when the operator opens a store), and everything degrades gracefully when a store
or optional dependency is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from qfinzero.pipeline.paths import resolve
from . import config_store

# Partitioned price stores that carry a ``ticker`` + ``trade_date`` column.
_SYMBOL_STORES = {"stock_daily", "stock_minute", "option_day", "option_minute"}


def _paths():
    d = config_store.dirs()
    return resolve(d.get("raw_massive"), d.get("raw_tushare"), d.get("storage_root"))


def overview() -> dict[str, Any]:
    """Raw + UPQ storage snapshot (from the registry) plus ESP event counts."""
    from qfinzero.pipeline import registry
    paths = _paths()
    scan = registry.scan(paths)
    return {
        "storage_root": str(paths.storage),
        "raw": scan.get("raw", {}),
        "storage": scan.get("storage", {}),
        "esp": _esp_counts(),
    }


def store_symbols(
    store: str, limit: int = 200, start: str | None = None, end: str | None = None,
) -> dict[str, Any]:
    """Per-symbol coverage in a price store: ``[{ticker, start, end, rows}]``.

    Grouped scan via DuckDB over the store's parquet partitions; ``limit`` caps
    the rows returned (ranked by row count) so the explorer stays responsive.
    """
    if store not in _SYMBOL_STORES:
        return {"ok": False, "error": f"unknown store {store!r}", "stores": sorted(_SYMBOL_STORES)}
    paths = _paths()
    root = paths.store(store)
    if not root.is_dir():
        return {"ok": True, "store": store, "symbols": [], "note": "store not built"}
    try:
        import duckdb  # noqa: F401
        from qfinzero.pipeline.engine import _lit, connect
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"duckdb unavailable: {e}"}

    glob = _lit(root / "trade_date=*" / "*.parquet")
    where = []
    if start:
        where.append(f"trade_date >= DATE '{start}'")
    if end:
        where.append(f"trade_date <= DATE '{end}'")
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        f"SELECT ticker, MIN(trade_date) s, MAX(trade_date) e, COUNT(*) n "
        f"FROM read_parquet('{glob}'){wsql} GROUP BY ticker ORDER BY n DESC LIMIT {int(limit)}"
    )
    con = connect()
    try:
        rows = con.execute(sql).fetchall()
        total = con.execute(
            f"SELECT COUNT(DISTINCT ticker) FROM read_parquet('{glob}'){wsql}"
        ).fetchone()[0]
    except Exception as e:  # noqa: BLE001 — empty/unbuilt store
        return {"ok": True, "store": store, "symbols": [], "note": f"scan failed: {e}"}
    finally:
        con.close()
    syms = [{"ticker": t, "start": str(s), "end": str(e), "rows": int(n)} for t, s, e, n in rows]
    return {"ok": True, "store": store, "total_symbols": int(total),
            "returned": len(syms), "symbols": syms}


def _esp_counts() -> dict[str, Any]:
    """Best-effort row counts for the ESP SQLite DBs + Mongo news collection."""
    import os
    root = config_store.dirs().get("qfz_data_root") or os.environ.get("QFZ_DATA_ROOT", "/data/qfinzero")
    esp_dir = Path(root) / "esp"
    out: dict[str, Any] = {
        "earnings": _sqlite_count(esp_dir / "benzinga_earnings.sqlite3", "earnings", "date"),
        "econ": _sqlite_count(esp_dir / "nasdaq_econ_events.sqlite3", "econ_events", "date"),
        "news": _mongo_count(),
    }
    return out


def _sqlite_count(db: Path, table: str, date_col: str) -> dict[str, Any]:
    if not db.exists():
        return {"present": False}
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            mx = con.execute(f"SELECT MAX({date_col}) FROM {table}").fetchone()[0]
        finally:
            con.close()
        return {"present": True, "rows": int(n), "max_date": mx}
    except Exception as e:  # noqa: BLE001
        return {"present": True, "error": f"{type(e).__name__}: {e}"}


def _mongo_count() -> dict[str, Any]:
    m = config_store.mongo()
    uri = m.get("uri")
    if not uri:
        return {"present": False}
    try:
        from pymongo import MongoClient
        client = MongoClient(uri, serverSelectionTimeoutMS=1500)
        try:
            n = client[m.get("db") or "market_news"][m.get("collection") or "ticker_news"].estimated_document_count()
        finally:
            client.close()
        return {"present": True, "docs": int(n)}
    except Exception as e:  # noqa: BLE001 — pymongo missing / server down
        return {"present": False, "error": f"{type(e).__name__}: {e}"}
