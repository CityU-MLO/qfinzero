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


def parquet_options(profile: str = "write") -> str:
    """``COPY … (FORMAT PARQUET, …)`` options for the QFZ store.

    ``write`` (fresh partitions) uses the configured format (``format`` in the
    data configuration: zstd level 3, 122,880-row groups by default);
    ``archive`` (``qfz-data compact``) raises the zstd level to 9 and keeps the
    row-group size. Measured on real partitions, level 9 is 3-6% smaller at
    the same read speed but writes 2-3x slower; larger row groups shrink files
    a little more but make single-ticker lookups 2-4x slower, so they are not
    used.
    """
    try:
        from qfinzero.admin.layout import storage_format
        f = storage_format()
    except Exception:  # noqa: BLE001 - config unavailable: the defaults
        f = {"compression": "zstd", "level": 3, "row_group_rows": 122_880}
    codec = str(f.get("compression") or "zstd").upper()
    level = 9 if profile == "archive" else int(f.get("level") or 3)
    opts = [f"COMPRESSION {codec}"]
    if codec == "ZSTD":
        opts.append(f"COMPRESSION_LEVEL {level}")
    opts.append(f"ROW_GROUP_SIZE {int(f.get('row_group_rows') or 122_880)}")
    return "FORMAT PARQUET, " + ", ".join(opts)


def copy_to_parquet(con, select_sql: str, out_file: Path, profile: str = "write") -> int:
    """Write ``select_sql`` to a single parquet file; return row count.

    Mirrors the UPQ ingester: one file per partition, trade_date carried as an
    in-file column, zstd compression (see :func:`parquet_options`).
    """
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_suffix(".parquet.tmp")
    con.execute(
        f"COPY ({select_sql}) TO '{_lit(tmp)}' ({parquet_options(profile)})"
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
