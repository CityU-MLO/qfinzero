"""Load interest-rate files into the rates store (Settings → Rates).

Option Greeks discount with the Treasury curve of the day (``rates`` store,
yields in percent). massive's ``treasury_yields.jsonl`` only carries the 1-,
5- and 10-year points and can lag the prices; this module reads rate files a
user uploads and keeps them in ``$STORAGE_ROOT/_state/rates_loaded.parquet``.
Every conversion of the ``rates`` store lays them over the massive base, so a
later update never drops them.

Accepted files (CSV, detected from the header):

* U.S. Treasury "Daily Treasury Par Yield Curve Rates": ``Date`` (MM/DD/YYYY)
  and ``1 Mo``, ``3 Mo``, ``1 Yr``, ``2 Yr``, ``5 Yr``, ``10 Yr``, ``30 Yr``…
* FRED series: ``DATE`` / ``observation_date`` and one of ``DGS1MO``,
  ``DGS3MO``, ``DGS1``, ``DGS2``, ``DGS5``, ``DGS10``, ``DGS30`` (``.`` = missing);
* generic: a date column and ``1M``/``3M``/``1Y``/``2Y``/``5Y``/``10Y``/``30Y`` or
  the store's own ``yield_1_month`` … ``yield_30_year`` names.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

TENORS = ["yield_1_month", "yield_3_month", "yield_1_year", "yield_2_year", "yield_5_year",
          "yield_10_year", "yield_30_year"]
_ALIASES = {
    "yield_1_month": {"1 mo", "1m", "1mo", "dgs1mo", "yield_1_month", "1 month"},
    "yield_3_month": {"3 mo", "3m", "3mo", "dgs3mo", "yield_3_month", "3 month"},
    "yield_1_year": {"1 yr", "1y", "1yr", "dgs1", "yield_1_year", "1 year"},
    "yield_2_year": {"2 yr", "2y", "2yr", "dgs2", "yield_2_year", "2 year"},
    "yield_5_year": {"5 yr", "5y", "5yr", "dgs5", "yield_5_year", "5 year"},
    "yield_10_year": {"10 yr", "10y", "10yr", "dgs10", "yield_10_year", "10 year"},
    "yield_30_year": {"30 yr", "30y", "30yr", "dgs30", "yield_30_year", "30 year"},
}
_DATE_COLS = {"date", "observation_date", "time", "day"}


def _tenor(col: str) -> Optional[str]:
    c = col.strip().lower()
    return next((t for t, names in _ALIASES.items() if c in names), None)


def _date(v: str) -> Optional[str]:
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(v[:10] if fmt == "%Y-%m-%d" else v, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _num(v: str) -> Optional[float]:
    v = (v or "").strip().replace("%", "")
    if v in ("", ".", "N/A", "NA", "null", "nan"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse(text: str, filename: str = "") -> dict[str, Any]:
    """Rows ``{date: {tenor: percent}}`` from one CSV, with what was recognised."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("the file is empty") from None
    cols = [h.strip() for h in header]
    date_i = next((i for i, c in enumerate(cols) if c.lower() in _DATE_COLS), None)
    if date_i is None:
        raise ValueError(f"no date column in {cols[:6]}")
    tenor_i = {i: _tenor(c) for i, c in enumerate(cols) if i != date_i}
    known = {i: t for i, t in tenor_i.items() if t}
    if not known:
        raise ValueError("no recognised tenor columns (expected e.g. '3 Mo', 'DGS3MO', '1Y' or yield_1_year)")
    rows: dict[str, dict[str, float]] = {}
    bad = 0
    for rec in reader:
        if len(rec) <= date_i or not rec[date_i].strip():
            continue
        d = _date(rec[date_i])
        if d is None:
            bad += 1
            continue
        vals = {t: x for i, t in known.items() if i < len(rec) and (x := _num(rec[i])) is not None}
        if vals:
            rows.setdefault(d, {}).update(vals)
    if not rows:
        raise ValueError("no rows with a date and a rate")
    out_of_range = [d for d, v in rows.items() if any(not (-5 <= x <= 30) for x in v.values())]
    if out_of_range:
        raise ValueError(f"rates must be in percent (e.g. 4.25); {out_of_range[0]} has {rows[out_of_range[0]]}")
    ds = sorted(rows)
    return {"file": filename, "rows": rows, "dates": len(ds), "start": ds[0], "end": ds[-1],
            "tenors": sorted(set(known.values()), key=TENORS.index),
            "ignored_columns": [cols[i] for i, t in tenor_i.items() if not t], "bad_dates": bad}


def _loaded_path(storage: Path) -> Path:
    return storage / "_state" / "rates_loaded.parquet"


def _read(con, path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, float]] = {}
    lit = str(path).replace("'", "''")
    for r in con.execute(f"SELECT CAST(date AS VARCHAR), {', '.join(TENORS)} FROM read_parquet('{lit}')").fetchall():
        out[r[0]] = {t: v for t, v in zip(TENORS, r[1:]) if v is not None}
    return out


def _write(con, rows: dict[str, dict[str, float]], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    con.execute("CREATE OR REPLACE TEMP TABLE _r (date DATE, " + ", ".join(f"{t} DOUBLE" for t in TENORS) + ")")
    con.executemany("INSERT INTO _r VALUES (?, " + ", ".join("?" for _ in TENORS) + ")",
                    [(date.fromisoformat(d), *[v.get(t) for t in TENORS]) for d, v in sorted(rows.items())])
    lit = str(tmp).replace("'", "''")
    con.execute(f"COPY (SELECT * FROM _r ORDER BY date) TO '{lit}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    tmp.replace(path)
    return len(rows)


def status(storage: Path) -> dict[str, Any]:
    """What the rates store and the loaded overlay hold."""
    from qfinzero.pipeline.engine import connect
    con = connect()
    try:
        out: dict[str, Any] = {"store": None, "loaded": None}
        store = storage / "rates" / "rates.parquet"
        for key, p in (("store", store), ("loaded", _loaded_path(storage))):
            if not p.exists():
                continue
            lit = str(p).replace("'", "''")
            q = ", ".join(f"count({t})" for t in TENORS)
            r = con.execute(f"SELECT CAST(min(date) AS VARCHAR), CAST(max(date) AS VARCHAR), count(*), {q} "
                            f"FROM read_parquet('{lit}')").fetchone()
            out[key] = {"start": r[0], "end": r[1], "dates": r[2], "tenors": {t: n for t, n in zip(TENORS, r[3:])}}
        return out
    finally:
        con.close()


def apply(storage: Path, parsed: list[dict[str, Any]], *, replace: bool = False) -> dict[str, Any]:
    """Merge parsed files into the overlay (later files win per date and tenor),
    then rebuild ``rates/rates.parquet`` as the massive base with the overlay on top."""
    from qfinzero.pipeline.engine import connect
    con = connect()
    try:
        path = _loaded_path(storage)
        rows = {} if replace else _read(con, path)
        before = len(rows)
        for p in parsed:
            for d, vals in p["rows"].items():
                rows.setdefault(d, {}).update(vals)
        n = _write(con, rows, path)
    finally:
        con.close()
    store = overlay(storage)
    return {"ok": True, "loaded_dates": n, "new_dates": n - before, "store": store}


def overlay(storage: Path) -> dict[str, Any]:
    """Lay the loaded rates over ``rates/rates.parquet`` (creating it if absent)."""
    from qfinzero.pipeline.engine import connect
    con = connect()
    try:
        loaded = _read(con, _loaded_path(storage))
        store_path = storage / "rates" / "rates.parquet"
        base = _read(con, store_path)
        for d, vals in loaded.items():
            base.setdefault(d, {}).update(vals)
        n = _write(con, base, store_path) if base else 0
        return {"dates": n, "overlaid": len(loaded)}
    finally:
        con.close()

