"""In-place views are the converter's own projection: a view over a raw file
equals the partition the converter writes from it, row for row."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero.index import catalog, views  # noqa: E402
from qfinzero.pipeline.sources import massive  # noqa: E402

S = 1_000_000_000


def _raw(path: Path, tickers):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(tickers)
    pq.write_table(pa.table({
        "ticker": tickers, "volume": pa.array([7] * n, pa.int64()), "open": [1.25] * n, "close": [1.5] * n,
        "high": [2.0] * n, "low": [1.0] * n, "window_start": pa.array([1_736_173_800 * S + i * 60 * S for i in range(n)],
                                                                      pa.int64()),
        "transactions": pa.array([3] * n, pa.int64())}), path)


@pytest.mark.parametrize("store,kind,tickers", [
    ("option_minute", "us_options_opra/minute_aggs_v1", ["O:SPY250117C00600000", "O:SPY1250117P00500000", "BAD"]),
    ("option_day", "us_options_opra/day_aggs_v1", ["O:AAPL250117C00200000"]),
    ("stock_daily", "us_stocks_sip/day_aggs_v1", ["AAPL", "BRK.B"]),
])
def test_view_equals_the_converted_partition(tmp_path, store, kind, tickers):
    raw = tmp_path / "raw" / kind / "2025" / "01" / "2025-01-06.parquet"
    _raw(raw, tickers)
    storage = tmp_path / "storage"
    rep = catalog.scan([tmp_path / "raw"], storage, threads=1)
    assert rep["views"][store] == 1
    doc = json.loads((views.views_dir(storage) / f"{store}.json").read_text())
    assert doc["files"] == {"2025-01-06": str(raw.resolve())} and doc["replaces"] == "part-0000.parquet"
    fn = views.IN_PLACE[store][3]
    con = duckdb.connect()
    converted = con.execute(fn(raw, "2025-01-06")).fetchall()
    in_place = con.execute(views.sql(storage, store, ["2025-01-06"])).fetchall()
    assert sorted(in_place) == sorted(converted) and converted
    if store == "option_minute":
        assert len(converted) == 2          # the converter's OPRA filter applies to the view too


def test_template_keeps_no_order_by_and_both_placeholders():
    for store, (_, _, _, fn) in views.IN_PLACE.items():
        t = views.template(fn)
        assert "{src}" in t and "{trade_date}" in t and "ORDER BY" not in t, store
    assert views.template(massive.stock_daily_sql).count("{trade_date}") == 1
