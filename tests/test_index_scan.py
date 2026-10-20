"""Raw-data index: recognise vendor files in place, catalogue them incrementally."""

from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero.index import adapters, catalog  # noqa: E402

S = 1_000_000_000
T0 = 1_785_765_000 * S          # 2026-08-03 13:50 UTC


def _aggs(path: Path, tickers: list[str], volume_type=pa.int64(), rows_per=1, row_group_size=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    tk = [t for t in tickers for _ in range(rows_per)]
    n = len(tk)
    t = pa.table({
        "ticker": pa.array(tk), "volume": pa.array([10] * n, volume_type),
        "open": [1.0] * n, "close": [1.0] * n, "high": [1.0] * n, "low": [1.0] * n,
        "window_start": pa.array([T0 + i * 60 * S for i in range(n)], pa.int64()),
        "transactions": pa.array([1] * n, pa.int64()),
    })
    pq.write_table(t, path, row_group_size=row_group_size or n)


def _library(tmp: Path) -> Path:
    root = tmp / "lib"
    opt = root / "massive" / "us_options_opra" / "minute_aggs_v1" / "2026" / "08" / "2026-08-03.parquet"
    _aggs(opt, ["O:SPY260821C00500000", "O:SPY260821P00500000"], rows_per=3)
    big = root / "massive" / "us_stocks_sip" / "minute_aggs_v1" / "2026" / "08" / "2026-08-04.parquet"
    _aggs(big, [f"T{i:05d}" for i in range(140)], volume_type=pa.float64(), rows_per=1000)
    tiingo = root / "tiingo" / "boats" / "prices" / "2026-08" / "AAPL.json.gz"
    tiingo.parent.mkdir(parents=True)
    tiingo.write_bytes(gzip.compress(json.dumps([{"date": "2026-08-04T00:00:00.000Z", "close": 1}]).encode()))
    custom = root / "my_cn"
    (custom / "2026-08-03").mkdir(parents=True)
    (custom / "qfz.dataset.yaml").write_text(
        "qfz_dataset: 1\nname: my_cn_minute\nvendor: acme\nkind: bar\nresolution: 1m\nasset_class: stock\n"
        "market: cn\ntime: {column: dt, unit: ns}\ncolumns: {code: ticker}\n")
    pq.write_table(pa.table({"code": ["SH600519", "SZ000001"], "dt": pa.array([T0, T0], pa.int64()),
                             "open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "close": [1.0, 2.0]}),
                   custom / "2026-08-03" / "bars.parquet")
    pq.write_table(pa.table({"code": ["SH600519"], "dt": pa.array([T0], pa.int64()), "close": [1.0]}),
                   custom / "2026-08-03" / "broken.parquet")
    (root / "README.txt").write_text("notes")
    pq.write_table(pa.table({"a": [1]}), root / "other.parquet")
    return root


def _rows(storage: Path, name: str) -> list[dict]:
    return pq.read_table(catalog.index_dir(storage) / name).to_pylist()


def test_scan_recognises_each_source(tmp_path):
    root, storage = _library(tmp_path), tmp_path / "storage"
    rep = catalog.scan([root], storage, threads=2)
    assert rep["ok"] and rep["files"] == 8 and rep["read"] == 8
    by = {Path(r["path"]).name: r for r in _rows(storage, "catalog.parquet")}

    opt = by["2026-08-03.parquet"]
    assert (opt["adapter"], opt["kind"], opt["asset_class"], opt["resolution"], opt["trade_date_min"]) \
        == ("massive.aggs", "bar", "option", "1m", "2026-08-03")
    assert opt["level"] == "L2" and opt["rows"] == 6      # sorted, small row group
    assert opt["symbols"] is None                          # whole-market day files are not listed
    stk = by["2026-08-04.parquet"]
    assert stk["level"] == "L1" and "row groups up to 140,000 rows" in stk["note"]
    assert "fractional volume" in stk["note"]

    assert (by["AAPL.json.gz"]["adapter"], by["AAPL.json.gz"]["trade_date_max"]) == ("tiingo.boats", "2026-08-31")

    bars = by["bars.parquet"]
    assert (bars["adapter"], bars["vendor"], bars["dataset"], bars["market"], bars["scope"], bars["level"]) \
        == ("qfz.standard", "acme", "my_cn_minute", "cn", "in", "L2")
    broken = by["broken.parquet"]
    assert broken["scope"] == "error" and "missing open, high, low" in broken["note"]

    assert by["README.txt"]["scope"] == "unknown" and by["other.parquet"]["scope"] == "unknown"
    assert rep["unknown"]["files"] == 2
    assert by["qfz.dataset.yaml"]["kind"] == "manifest" and by["qfz.dataset.yaml"]["scope"] == "in"

    syms = {(r["symbol"], Path(r["path"]).name): r["rows"] for r in _rows(storage, "symbols.parquet")}
    assert syms == {("SH600519", "bars.parquet"): 1, ("SZ000001", "bars.parquet"): 1, ("AAPL", "AAPL.json.gz"): 0}
    assert by["bars.parquet"]["symbols"] == 2
    rgs = [r for r in _rows(storage, "row_groups.parquet") if r["path"].endswith("2026-08-03.parquet")]
    assert rgs == [{"path": str(opt["path"]), "rg": 0, "rows": 6, "symbol_min": "O:SPY260821C00500000",
                    "symbol_max": "O:SPY260821P00500000"}]


def test_rescan_reads_only_changed_files(tmp_path):
    root, storage = _library(tmp_path), tmp_path / "storage"
    catalog.scan([root], storage, threads=2)
    again = catalog.scan([root], storage, threads=2)
    assert again["read"] == 0 and again["reused"] == 8
    f = root / "massive" / "us_options_opra" / "minute_aggs_v1" / "2026" / "08" / "2026-08-03.parquet"
    _aggs(f, ["O:QQQ260821C00400000"], rows_per=2)
    third = catalog.scan([root], storage, threads=2)
    assert third["read"] == 1
    rgs = [r for r in _rows(storage, "row_groups.parquet") if r["path"] == str(f.resolve())]
    assert [r["symbol_min"] for r in rgs] == ["O:QQQ260821C00400000"]
    # files that disappeared leave the catalogue
    (root / "README.txt").unlink()
    assert catalog.scan([root], storage, threads=2)["files"] == 7
    assert catalog.last_report(storage)["files"] == 7


def test_massive_trades_and_reference_files(tmp_path):
    import gzip as _gz
    t = tmp_path / "us_options_opra" / "trades_v1" / "2026" / "08" / "2026-08-21.parquet"
    t.parent.mkdir(parents=True)
    pq.write_table(pa.table({"ticker": ["O:A", "O:B"], "conditions": [0, 0], "price": [1.0, 2.0],
                             "sip_timestamp": pa.array([T0, T0 + S], pa.int64()), "size": [1, 2]}), t)
    d = adapters.describe(t)
    assert (d.adapter, d.kind, d.asset_class, d.resolution, d.ts_min) == ("massive.trades", "trade", "option", "tick", T0)
    c = tmp_path / "global_crypto" / "trades_v1" / "2014" / "01" / "2014-01-01.csv.gz"
    c.parent.mkdir(parents=True)
    c.write_bytes(_gz.compress(b"ticker,conditions,exchange,id,participant_timestamp,price,size\n"))
    d = adapters.describe(c)
    assert (d.kind, d.schema, d.resolution) == ("trade", "trades_v1", "tick")
    n = tmp_path / "benzinga" / "news" / "2026" / "2026-08.jsonl"
    n.parent.mkdir(parents=True)
    n.write_text("{}")
    d = adapters.describe(n)
    assert (d.adapter, d.kind, d.dataset, d.schema) == ("massive.reference", "event", "benzinga", "news")


def test_scanning_one_directory_keeps_the_others(tmp_path):
    root, storage = _library(tmp_path), tmp_path / "storage"
    catalog.scan([root / "massive", root / "tiingo"], storage, threads=2)
    rep = catalog.scan([root / "tiingo"], storage, threads=2)
    assert rep["files"] == 3 and rep["read"] == 0 and rep["scanned"] == [str((root / "tiingo").resolve())]
    assert {Path(r).name for r in rep["roots"]} == {"massive", "tiingo"}


def test_unsorted_row_groups_are_level_one(tmp_path):
    f = tmp_path / "us_options_opra" / "minute_aggs_v1" / "2021" / "06" / "2021-06-21.parquet"
    _aggs(f, ["O:B", "O:C", "O:A", "O:D"], rows_per=1, row_group_size=2)       # groups [B..C], [A..D]
    d = adapters.describe(f)
    assert d.level == "L1" and "not in symbol order" in d.note


def test_manifest_needs_a_time_zone_for_naive_iso_times(tmp_path):
    m = tmp_path / "qfz.dataset.yaml"
    m.write_text("qfz_dataset: 1\nkind: bar\ntime: {column: dt, unit: iso}\n")
    with pytest.raises(ValueError, match="timezone"):
        adapters.load_manifest(m)
    m.write_text("qfz_dataset: 1\nkind: bar\ntime: {column: dt, unit: iso, timezone: Asia/Shanghai}\n")
    assert adapters.load_manifest(m)["kind"] == "bar"


def test_databento_files_are_catalogued_with_scope(tmp_path):
    pytest.importorskip("databento_dbn")
    from types import SimpleNamespace as NS
    from datetime import date, timedelta
    import databento_dbn as d
    day0 = date(2025, 1, 2)
    start = 1735776000 * S

    def dbn(path, dataset, schema):
        md = d.Metadata(dataset=dataset, start=start, end=start + 86400 * S, stype_in=d.SType.RAW_SYMBOL,
                        stype_out=d.SType.INSTRUMENT_ID, schema=d.Schema.from_str(schema), symbols=["FOO"],
                        mappings=[NS(raw_symbol="FOO", intervals=[NS(start_date=day0, end_date=day0 + timedelta(days=1),
                                                                     symbol="7")])])
        rec = d.TradeMsg(2, 7, start + 3600 * S, 100 * 10**9, 1, d.Action.TRADE, d.Side.NONE, 0, start + 3600 * S)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(md.encode()) + bytes(rec))

    dbn(tmp_path / "db" / "trades" / "FOO.dbn", "XNAS.ITCH", "trades")
    dbn(tmp_path / "db" / "mbo" / "FOO.dbn", "XNAS.ITCH", "mbo")
    rep = catalog.scan([tmp_path / "db"], tmp_path / "storage")
    rows = {r["schema"]: r for r in _rows(tmp_path / "storage", "catalog.parquet")}
    assert (rows["trades"]["adapter"], rows["trades"]["kind"], rows["trades"]["scope"]) == ("databento", "trade", "in")
    assert rows["mbo"]["scope"] == "out" and "out of scope" in rows["mbo"]["note"]
    assert {g["scope"] for g in rep["groups"]} == {"in", "out"}
