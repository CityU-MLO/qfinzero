"""DuckDB engine helpers for the converter.

DuckDB is the same engine the UPQ Rust ingester uses, so the parquet we emit is
byte-compatible: ``COPY (...) TO '.../trade_date=X/part-0000.parquet'
(FORMAT PARQUET, COMPRESSION ZSTD)`` with ``trade_date`` as an in-file column.
"""

from __future__ import annotations

import os
from pathlib import Path


def connect(threads: int | None = None):
    import duckdb

    con = duckdb.connect()
    if threads:
        con.execute(f"PRAGMA threads={int(threads)}")
    return con


def copy_to_parquet(con, select_sql: str, out_file: Path) -> int:
    """Write ``select_sql`` to a single ZSTD parquet file; return row count.

    Mirrors the UPQ ingester: one file per partition, trade_date carried as an
    in-file column, ZSTD compression.
    """
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_suffix(".parquet.tmp")
    con.execute(
        f"COPY ({select_sql}) TO '{_lit(tmp)}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    n = con.execute(f"SELECT COUNT(*) FROM read_parquet('{_lit(tmp)}')").fetchone()[0]
    if n == 0:
        # don't leave empty partitions around
        tmp.unlink(missing_ok=True)
        return 0
    os.replace(tmp, out_file)
    return int(n)


def _lit(path: Path | str) -> str:
    """Escape a path for a single-quoted DuckDB string literal."""
    return str(path).replace("'", "''")
