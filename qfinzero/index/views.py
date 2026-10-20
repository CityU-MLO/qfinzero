"""In-place views: logical stores read straight from the vendors' raw files.

For each store in :data:`IN_PLACE` a scan writes ``_state/index/views/<store>.json``:

* ``files``     ET trade date -> raw file (from the catalogue, scope ``in``);
* ``template``  the converter's own projection for that store (the same SQL
  :mod:`qfinzero.pipeline.sources.massive` writes the store with), with
  ``{src}`` for the files and ``{trade_date}`` for the date expression, so a
  view and a converted partition are the same rows by construction;
* ``date_expr`` the trade date of a row read with ``filename = true``;
* ``replaces``  the converted part a raw file stands in for on its date. Other
  vendors' parts in the partition (Databento fills) are still read.

UPQ uses a view when ``UPQ_IN_PLACE`` names the store; otherwise it reads the
converted partitions as before.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from qfinzero.pipeline.sources import massive

VERSION = 1
PLACEHOLDER = "/__QFZ_SRC__.parquet"
DATE_EXPR = r"CAST(regexp_extract(filename, '(\d{4}-\d{2}-\d{2})\.parquet$', 1) AS DATE)"
# store -> (adapter, asset class, resolution, the converter's projection)
IN_PLACE = {
    "option_minute": ("massive.aggs", "option", "1m", massive.option_minute_sql),
    "option_day": ("massive.aggs", "option", "1d", massive.option_day_sql),
    "stock_daily": ("massive.aggs", "stock", "1d", massive.stock_daily_sql),
}
REPLACES = "part-0000.parquet"


def template(sql_fn) -> str:
    sql = sql_fn(Path(PLACEHOLDER), "1970-01-01")
    out = sql.replace(f"read_parquet('{PLACEHOLDER}')", "{src}").replace("DATE '1970-01-01'", "{trade_date}")
    out = re.sub(r"\n\s*ORDER BY [^\n]*\n?\s*$", "\n", out)
    if "{src}" not in out or "{trade_date}" not in out or "ORDER BY" in out:
        raise ValueError(f"cannot make a view template from {sql_fn.__name__}")
    return out


def views_dir(storage: Path) -> Path:
    return Path(storage) / "_state" / "index" / "views"


def build(storage: Path, rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Write one view file per in-place store from catalogue rows; returns files per store."""
    out_dir = views_dir(storage)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_store: dict[str, dict[str, str]] = {s: {} for s in IN_PLACE}
    for r in rows:
        if r.get("scope") != "in" or not r.get("trade_date_min") or r.get("trade_date_min") != r.get("trade_date_max"):
            continue
        for store, (adapter, asset, res, _) in IN_PLACE.items():
            if (r.get("adapter"), r.get("asset_class"), r.get("resolution")) == (adapter, asset, res):
                # one raw file per date; a duplicate keeps the larger
                d = r["trade_date_min"]
                cur = by_store[store].get(d)
                if cur is None or os.path.getsize(r["path"]) > os.path.getsize(cur):
                    by_store[store][d] = r["path"]
    counts = {}
    for store, files in by_store.items():
        doc = {"version": VERSION, "store": store, "replaces": REPLACES,
               "template": template(IN_PLACE[store][3]), "date_expr": DATE_EXPR,
               "files": dict(sorted(files.items()))}
        tmp = out_dir / f".{store}.json.tmp"
        tmp.write_text(json.dumps(doc, indent=0))
        os.replace(tmp, out_dir / f"{store}.json")
        counts[store] = len(files)
    return counts


def sql(storage: Path, store: str, dates: list[str]) -> str:
    """The view of ``store`` over raw files for ``dates`` (for tests and tools)."""
    doc = json.loads((views_dir(storage) / f"{store}.json").read_text())
    files = [doc["files"][d] for d in dates if d in doc["files"]]
    src = "read_parquet([" + ", ".join("'" + f.replace("'", "''") + "'" for f in files) + "], filename = true)"
    return doc["template"].replace("{src}", src).replace("{trade_date}", doc["date_expr"])
