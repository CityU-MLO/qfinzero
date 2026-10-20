"""Crypto and FX: massive global flat files (gzip CSV, or the parquet converted from it) -> pair stores, coverage."""

from __future__ import annotations

import gzip
import os
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DAY0 = 1771891200000000000          # 2026-02-24 00:00 UTC
MIN = 60_000_000_000


def _csv(path: Path, header: str, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        f.write(header + "\n" + "\n".join(rows) + "\n")


def _raw(massive: Path) -> None:
    agg = "ticker,volume,open,close,high,low,window_start,transactions"
    for d, ws in (("2026-02-23", DAY0 - 86_400 * 10**9), ("2026-02-24", DAY0)):
        y, m = d[:4], d[5:7]
        _csv(massive / f"global_crypto/day_aggs_v1/{y}/{m}/{d}.csv.gz", agg,
             [f"X:BTC-USD,20134.07,64624.1,64061.9,65094,62500,{ws},930852",
              f"X:ETH-USD,1.5,1800,1810,1820,1790,{ws},12"])
        _csv(massive / f"global_crypto/minute_aggs_v1/{y}/{m}/{d}.csv.gz", agg,
             [f"X:BTC-USD,0.25,64624.1,64630,64640,64600,{ws},40", f"X:BTC-USD,0.5,64630,64620,64633,64610,{ws + MIN},41"])
        _csv(massive / f"global_forex/day_aggs_v1/{y}/{m}/{d}.csv.gz", agg,
             [f"C:EUR-USD,900,1.183,1.181,1.185,1.18,{ws},900"])
        _csv(massive / f"global_forex/minute_aggs_v1/{y}/{m}/{d}.csv.gz", agg,
             [f"C:EUR-USD,3,1.183,1.1831,1.1832,1.1829,{ws},3"])
        # two quotes in the first minute (the later wins), one 23:59:59 the day
        # before (belongs to the previous UTC day: dropped from this partition)
        _csv(massive / f"global_forex/quotes_v1/{y}/{m}/{d}.csv.gz",
             "ticker,ask_exchange,ask_price,bid_exchange,bid_price,participant_timestamp",
             [f"C:EUR-USD,48,1.1832,48,1.1830,{ws + 1_000_000_000}",
              f"C:EUR-USD,48,1.1833,48,1.1831,{ws + 50_000_000_000}",
              f"C:EUR-USD,48,1.1800,48,1.1799,{ws - 1_000_000_000}"])


@pytest.fixture(params=["csv", "parquet"])
def stores(tmp_path, request):
    from qfinzero.pipeline.convert import Converter
    from qfinzero.pipeline.paths import resolve
    massive = tmp_path / "massive"
    _raw(massive)
    if request.param == "parquet":
        from qfinzero.admin import massive_dl
        rep = massive_dl.convert_library(massive, delete_csv=True)
        assert rep["ok"] and rep["converted"] == rep["deleted"] == 10 and not list(massive.rglob("*.csv.gz"))
    (tmp_path / "tushare").mkdir()
    paths = resolve(massive, tmp_path / "tushare", tmp_path / "upq")
    with Converter(paths) as cv:
        res = {r.store: r for r in (cv.convert_crypto_daily(), cv.convert_crypto_minute(), cv.convert_fx_daily(),
                                    cv.convert_fx_minute(), cv.convert_fx_quotes())}
        again = cv.convert_crypto_daily()
    return tmp_path / "upq", res, again


def q(root: Path, store: str, sql: str):
    con = duckdb.connect()
    try:
        return con.execute(sql.replace("$S", f"read_parquet('{root / store}/*/*.parquet')")).fetchall()
    finally:
        con.close()


def test_pairs_are_normalised_and_volume_is_fractional(stores):
    root, res, again = stores
    assert res["crypto_daily"].partitions == 2 and res["crypto_daily"].rows == 4
    assert again.skipped == 2 and again.partitions == 0            # unchanged inputs are not reconverted
    rows = q(root, "crypto_daily", "SELECT ticker, base, quote, volume, trade_date::VARCHAR FROM $S "
                                   "WHERE trade_date = DATE '2026-02-24' ORDER BY ticker")
    assert rows == [("BTC-USD", "BTC", "USD", 20134.07, "2026-02-24"), ("ETH-USD", "ETH", "USD", 1.5, "2026-02-24")]
    assert q(root, "crypto_minute", "SELECT sum(volume) FROM $S")[0][0] == pytest.approx(1.5)
    assert q(root, "fx_minute", "SELECT DISTINCT ticker, base, quote FROM $S") == [("EUR-USD", "EUR", "USD")]


def test_fx_quotes_keep_the_last_quote_of_each_utc_minute(stores):
    root, res, _ = stores
    rows = q(root, "fx_quote_minute", "SELECT trade_date::VARCHAR, window_start, bid_price, ask_price FROM $S "
                                      "ORDER BY window_start")
    assert ("2026-02-24", DAY0, 1.1831, 1.1833) in rows             # later quote of the minute wins
    assert all(not (d == "2026-02-24" and ws < DAY0) for d, ws, _, _ in rows)   # 23:59:59 stays in 02-23


def test_recent_window_for_large_stores(tmp_path):
    from qfinzero.pipeline.convert import Converter
    from qfinzero.pipeline.paths import resolve
    massive = tmp_path / "massive"
    _raw(massive)
    (tmp_path / "tushare").mkdir()
    with Converter(resolve(massive, tmp_path / "tushare", tmp_path / "upq")) as cv:
        cv.RECENT_DAYS = {**cv.RECENT_DAYS, "fx_minute": 0}         # only the newest day
        assert cv.convert_fx_minute().partitions == 1
        assert cv.convert_fx_minute(start="2026-01-01").partitions == 1   # an explicit start reaches back


def test_registry_and_coverage_see_the_pairs(stores):
    from qfinzero.admin import coverage as C
    from qfinzero.pipeline import registry
    from qfinzero.pipeline.paths import resolve
    root, _, _ = stores
    scan = registry.scan_storage(resolve(root.parent / "massive", root.parent / "tushare", root))
    assert scan["fx_quote_minute"]["end"] == "2026-02-24" and scan["crypto_daily"]["partitions"] == 2
    assert C.kind_of("x:btc-usd") == ("BTC-USD", "crypto") and C.kind_of("C:EUR-USD") == ("EUR-USD", "fx")
    assert C.kind_of("/CL") == ("CL", "future") and C.kind_of("SPY") == ("SPY", "stock")
    m = C.matrix(["X:BTC-USD", "C:EUR-USD", "SPY"], "2026-02-23", "2026-02-24", root)
    assert m["kinds"] == {"X:BTC-USD": "crypto", "C:EUR-USD": "fx", "SPY": "stock"}
    assert set(m["cells"]["X:BTC-USD"]["2026-02-24"]) == {"crypto_daily", "crypto_minute"}
    assert set(m["cells"]["C:EUR-USD"]["2026-02-24"]) == {"fx_daily", "fx_minute", "fx_quotes"}
    assert C.suggest("X:", root=root)[0]["ticker"] == "X:BTC-USD"
    a = C.asset("X:BTC-USD", "2026-02-01", "2026-02-28", root)
    assert a["kind"] == "crypto" and a["series"][-1]["close"] == 64061.9
    c = C.cell("C:EUR-USD", "2026-02-24", root)
    assert c["kind"] == "fx" and c["quote_span"]["first_ns"] == DAY0 and c["option_expiries"] == []


def test_massive_downloads_convert_global_files_to_parquet(tmp_path):
    from datetime import date
    from qfinzero.admin import massive_dl

    class S3:
        def get_paginator(self, _n):
            class P:
                def paginate(self, Bucket, Prefix):
                    yield {"Contents": [{"Key": "global_forex/day_aggs_v1/2026/02/2026-02-24.csv.gz", "Size": 10}]}
            return P()
    (tmp_path / "global_forex/day_aggs_v1/2026/02").mkdir(parents=True)
    files = massive_dl.plan(S3(), "global_forex/day_aggs_v1", date(2026, 2, 1), date(2026, 2, 28), tmp_path)
    assert files[0]["path"].endswith("2026-02-24.parquet") and not files[0]["exists"]
    # a day still kept as massive shipped it counts as present (convert_library converts it)
    (tmp_path / "global_forex/day_aggs_v1/2026/02/2026-02-24.csv.gz").write_bytes(b"x")
    assert massive_dl.plan(S3(), "global_forex/day_aggs_v1", date(2026, 2, 1), date(2026, 2, 28), tmp_path)[0]["exists"]


def test_csv_to_parquet_sorts_types_and_indexes(tmp_path, monkeypatch):
    import pyarrow.parquet as pq
    from qfinzero.admin import massive_dl
    from qfinzero.index import adapters
    monkeypatch.setattr(massive_dl, "ROW_GROUP", 3)
    src = tmp_path / "global_crypto/trades_v1/2026/02/2026-02-24.csv.gz"
    rows = [f"X:{t}-USD,{c},1,{i},{DAY0 + n},0.5,{s}" for i, (t, n, c, s) in enumerate(
        [("BTC", 1, 2, 0.25), ("BTC", 1, 1, 3), ("BTC", 5, "", 1.5), ("ETH", 2, 2, 7), ("SOL", 0, 1, 2), ("ZEC", 9, 1, 1)])]
    _csv(src, "ticker,conditions,exchange,id,participant_timestamp,price,size", rows)
    dst = src.with_name("2026-02-24.parquet")
    assert massive_dl.csv_to_parquet(src, dst) == {"rows": 6, "sorted": True}
    pf = pq.ParquetFile(dst)
    assert [pf.metadata.row_group(i).num_rows for i in range(pf.metadata.num_row_groups)] == [3, 3]
    assert pf.metadata.row_group(0).column(0).has_offset_index
    sch = pf.schema_arrow
    assert (str(sch.field("size").type), str(sch.field("id").type), str(sch.field("conditions").type)) == \
        ("double", "string", "string")
    assert massive_dl.verify_parquet(src, dst)["rows"] == 6
    d = adapters.massive_trades(dst)
    assert (d.kind, d.market, d.asset_class, d.level, d.ts_min, d.ts_max) == \
        ("trade", "global", "crypto", "L2", DAY0, DAY0 + 9)

    # out of order: sorted by ticker then time, ties keep their file order
    _csv(src, "ticker,conditions,exchange,id,participant_timestamp,price,size",
         [rows[3], rows[1], rows[0], rows[5], rows[4], rows[2]])
    dst.unlink()
    assert massive_dl.csv_to_parquet(src, dst) == {"rows": 6, "sorted": True}
    got = pq.read_table(dst).to_pydict()
    assert got["id"] == ["1", "0", "2", "3", "4", "5"] and got["ticker"][-1] == "X:ZEC-USD"
    massive_dl.verify_parquet(src, dst)
    # a larger file than may be sorted in memory is written as it comes
    dst.unlink()
    assert massive_dl.csv_to_parquet(src, dst, sort_limit=0) == {"rows": 6, "sorted": False}
    assert adapters.massive_trades(dst).level == "L1"

    # a quiet day: a header without a line break, no rows
    empty = src.with_name("2026-02-25.csv.gz")
    with gzip.open(empty, "wt") as f:
        f.write("ticker,conditions,exchange,id,participant_timestamp,price,size")
    assert massive_dl.csv_to_parquet(empty, empty.with_name("2026-02-25.parquet")) == {"rows": 0, "sorted": True}
    assert pq.read_table(empty.with_name("2026-02-25.parquet")).schema == sch
    assert massive_dl.verify_parquet(empty, empty.with_name("2026-02-25.parquet"))["rows"] == 0

    # a parquet that lost a row fails verification
    import pyarrow as pa
    pq.write_table(pa.Table.from_pydict({k: v[:-1] for k, v in got.items()}), dst)
    with pytest.raises(ValueError, match="differs"):
        massive_dl.verify_parquet(src, dst)


def test_converted_fx_quotes_are_indexed_as_global(tmp_path):
    from qfinzero.admin import massive_dl
    from qfinzero.index import adapters
    _raw(tmp_path)
    src = tmp_path / "global_forex/quotes_v1/2026/02/2026-02-24.csv.gz"
    dst = src.with_name("2026-02-24.parquet")
    massive_dl.csv_to_parquet(src, dst)
    d = adapters.massive_quotes(dst)
    assert (d.market, d.asset_class, d.dataset, d.level, d.ts_min) == \
        ("global", "fx", "global_forex", "L2", DAY0 - 1_000_000_000)
    a = adapters.massive_aggs(dst.parent.parent.parent.parent.parent / "minute_aggs_v1/2026/02/2026-02-24.csv.gz")
    assert a is None                                    # gzip CSV stays with massive.global until converted


def test_local_import_recognises_global_files(tmp_path):
    from qfinzero.admin import datasetup
    q = Path("/x/global_forex/quotes_v1/2021/02/2021-02-01.csv.gz")
    assert datasetup._massive_index(q) == "global_forex/quotes_v1"
    assert datasetup._massive_index(Path("/x/global_crypto/minute_aggs_v1/2026/02/2026-02-24.csv.gz")) == \
        "global_crypto/minute_aggs_v1"
    assert datasetup._massive_index(Path("/x/global_crypto/trades_v1/2026/02/2026-02-24.csv.gz")) is None
    src = tmp_path / "dl" / "global_forex" / "quotes_v1" / "2021" / "02" / "2021-02-01.csv.gz"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    groups, ignored = datasetup._massive_files([tmp_path / "dl"])
    assert groups == {"global_forex/quotes_v1": [("2021-02-01", src)]} and ignored == 0
