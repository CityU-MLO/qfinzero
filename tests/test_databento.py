"""Databento source: DBN / parquet -> UPQ bar stores.

DBN fixtures are synthesized with ``databento_dbn`` (skipped when the optional
``databento`` extra is absent); the parquet-export path only needs DuckDB.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero.pipeline.paths import resolve  # noqa: E402
from qfinzero.pipeline.sources import databento as dbsrc  # noqa: E402

S = 1_000_000_000
# 2025-01-02 is EST (UTC-5): 09:30 ET == 14:30 UTC
T0930 = 1735828200 * S
DAY_START = 1735776000 * S          # 2025-01-02 00:00 UTC
DAY_END = DAY_START + 86400 * S
PX = 1_000_000_000                  # Databento fixed-point scale (1e-9)


def _has_dbn() -> bool:
    try:
        import databento  # noqa: F401
        import databento_dbn  # noqa: F401
        return True
    except ImportError:
        return False


needs_dbn = pytest.mark.skipif(not _has_dbn(), reason="databento extra not installed")


def _write_dbn(path: Path, dataset: str, schema: str, symbols: dict[str, int], records,
               compress: bool = False, map_days: int = 1) -> Path:
    import databento_dbn as d
    day0 = date(2025, 1, 2)
    md = d.Metadata(
        dataset=dataset, start=DAY_START, end=DAY_END,
        stype_in=d.SType.RAW_SYMBOL, stype_out=d.SType.INSTRUMENT_ID,
        schema=d.Schema.from_str(schema), symbols=list(symbols),
        mappings=[NS(raw_symbol=s, intervals=[NS(start_date=day0, end_date=day0 + timedelta(days=map_days),
                                                  symbol=str(iid))])
                  for s, iid in symbols.items()],
    )
    raw = bytes(md.encode()) + b"".join(bytes(r) for r in records)
    if compress:
        import zstandard
        raw = zstandard.ZstdCompressor().compress(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _trade(iid, ts, price, size, action="T"):
    import databento_dbn as d
    act = {"T": d.Action.TRADE, "F": d.Action.FILL, "A": d.Action.ADD}[action]
    return d.TradeMsg(2, iid, ts, int(round(price * PX)), size, act, d.Side.NONE, 0, ts + 1)


def _mbo(iid, ts, price, size, action):
    import databento_dbn as d
    act = {"T": d.Action.TRADE, "F": d.Action.FILL, "A": d.Action.ADD,
           "C": d.Action.CANCEL}[action]
    return d.MBOMsg(2, iid, ts, 42, int(round(price * PX)), size, act, d.Side.BID, ts + 1)


def _q(con, sql):
    return con.execute(sql).fetchall()


def _paths(tmp_path):
    return resolve(tmp_path / "massive", tmp_path / "tushare", tmp_path / "storage",
                   tmp_path / "databento")


def _convert(paths, **kw):
    from qfinzero.pipeline.convert import Converter
    with Converter(paths) as cv:
        return cv.convert_databento(**kw)


def _store(paths, store, d="2025-01-02"):
    return paths.partition(store, d) / dbsrc.PART_NAME


# ── DBN: trades schema ───────────────────────────────────────────────────

@needs_dbn
def test_dbn_trades_to_minute_and_daily(tmp_path):
    paths = _paths(tmp_path)
    m = 60 * S
    recs = [
        _trade(7, T0930 - m, 99.0, 5),          # 09:29 pre-market
        _trade(7, T0930 + 10 * S, 100.0, 10),   # 09:30
        _trade(7, T0930 + 40 * S, 102.0, 20),   # 09:30
        _trade(7, T0930 + m + 5 * S, 101.0, 30),  # 09:31
        _trade(7, T0930 + 395 * m, 98.0, 7),    # 16:05 after-hours
    ]
    _write_dbn(paths.databento / "XNAS.ITCH" / "trades" / "FOO.dbn.zst", "XNAS.ITCH", "trades",
               {"FOO": 7}, recs, compress=True)
    res = _convert(paths)
    assert res.rows > 0, res.notes

    con = duckdb.connect()
    bars = _q(con, f"""SELECT window_start, open, high, low, close, volume, transactions
                       FROM read_parquet('{_store(paths, 'stock_minute')}') ORDER BY 1""")
    assert [b[0] for b in bars] == [T0930 - m, T0930, T0930 + m, T0930 + 395 * m]
    assert bars[1][1:] == (100.0, 102.0, 100.0, 102.0, 30, 2)
    cols = [r[0] for r in _q(con, f"DESCRIBE SELECT * FROM read_parquet('{_store(paths, 'stock_minute')}')")]
    assert cols == ["ticker", "window_start", "open", "high", "low", "close", "volume",
                    "transactions", "trade_date"]

    day = _q(con, f"SELECT * FROM read_parquet('{_store(paths, 'stock_daily')}')")
    # O/H/L/C from the regular session, volume/transactions from the whole day
    assert day == [("FOO", date(2025, 1, 2), 100.0, 102.0, 100.0, 101.0, 72, 5)]


@needs_dbn
def test_dbn_mbo_counts_only_trade_actions(tmp_path):
    paths = _paths(tmp_path)
    recs = [
        _mbo(9, T0930, 50.0, 100, "A"),
        _mbo(9, T0930 + S, 50.0, 40, "T"),
        _mbo(9, T0930 + S, 50.0, 40, "F"),     # passive side of the same execution
        _mbo(9, T0930 + 2 * S, 50.0, 60, "C"),
    ]
    _write_dbn(paths.databento / "mbo" / "BAR" / "2025-01-02.dbn", "OCEA.MEMOIR", "mbo",
               {"BAR": 9}, recs)
    _convert(paths)
    con = duckdb.connect()
    assert _q(con, f"SELECT ticker, volume, transactions FROM read_parquet('{_store(paths, 'stock_minute')}')") \
        == [("BAR", 40, 1)]


@needs_dbn
def test_mbo_outside_blue_ocean_and_cmbp1_are_out_of_scope(tmp_path):
    """QFZ stops at consolidated BBO: other venues' MBO and cmbp-1 are indexed, not converted."""
    import databento_dbn as d
    paths = _paths(tmp_path)
    _write_dbn(paths.databento / "mbo" / "BAR" / "2025-01-02.dbn", "XNAS.ITCH", "mbo",
               {"BAR": 9}, [_mbo(9, T0930 + S, 50.0, 40, "T")])
    lv = d.ConsolidatedBidAskPair(bid_px=int(2.0 * PX), ask_px=int(2.2 * PX), bid_sz=3, ask_sz=4)
    _write_dbn(paths.databento / "cmbp" / "FOO.dbn", "OPRA.PILLAR", "cmbp-1", {"FOO   250117P00090000": 11},
               [d.CMBP1Msg(int(d.RType.CMBP_1), 30, 11, T0930, int(2.1 * PX), 6, d.Action.TRADE,
                           d.Side.NONE, T0930, levels=lv)])
    res = _convert(paths)
    assert any("out of scope=2" in n for n in res.notes), res.notes
    assert res.rows == 0
    infos = {i.schema: i for i in dbsrc.index(paths.databento)}
    assert infos["mbo"].out_of_scope and infos["cmbp-1"].out_of_scope
    assert not infos["mbo"].convertible and not infos["cmbp-1"].convertible
    from qfinzero.admin import databento_dl
    with pytest.raises(ValueError, match="not used by QFinZero"):
        databento_dl.plan({"dataset": "XNAS.ITCH", "schema": "mbo", "symbols": "AAPL", "start": "2025-01-02"},
                          tmp_path)
    assert databento_dl.plan({"dataset": "OCEA.MEMOIR", "schema": "mbo", "symbols": "AAPL",
                              "start": "2025-01-02"}, tmp_path)


@needs_dbn
def test_session_split_across_utc_files_and_duplicates(tmp_path):
    """Databento cuts files on UTC days: 19:00-20:00 ET lands in the next file.
    Both files are one source and are unioned; a duplicate file adds nothing."""
    paths = _paths(tmp_path)
    late = T0930 + 600 * 60 * S          # 19:30 ET == 00:30 UTC next day
    a = [_trade(7, T0930, 100.0, 10)]
    b = [_trade(7, late, 101.0, 4)]
    _write_dbn(paths.databento / "FOO" / "2025-01-02.dbn", "XNAS.ITCH", "trades", {"FOO": 7}, a)
    _write_dbn(paths.databento / "FOO" / "2025-01-03.dbn", "XNAS.ITCH", "trades", {"FOO": 7}, b,
               map_days=2)
    _write_dbn(paths.databento / "dup" / "FOO.dbn", "XNAS.ITCH", "trades", {"FOO": 7}, a)
    _convert(paths)
    con = duckdb.connect()
    assert _q(con, f"SELECT window_start, volume FROM read_parquet('{_store(paths, 'stock_minute')}') ORDER BY 1") \
        == [(T0930, 10), (late, 4)]
    assert _q(con, f"SELECT close, volume, transactions FROM read_parquet('{_store(paths, 'stock_daily')}')") \
        == [(100.0, 14, 2)]


# ── DBN: OPRA options ────────────────────────────────────────────────────

@needs_dbn
def test_dbn_opra_tcbbo_to_option_stores(tmp_path):
    import databento_dbn as d
    paths = _paths(tmp_path)
    osi = "FOO   250117C00100000"
    recs = [d.CBBOMsg(int(d.RType.TCBBO), 30, 11, T0930 + S, int(1.25 * PX), 3, d.Side.NONE, T0930 + S + 1),
            d.CBBOMsg(int(d.RType.TCBBO), 30, 11, T0930 + 2 * S, int(1.30 * PX), 2, d.Side.NONE, T0930 + 2 * S + 1)]
    _write_dbn(paths.databento / "opra" / "FOO.dbn.zst", "OPRA.PILLAR", "tcbbo", {osi: 11}, recs,
               compress=True)
    _convert(paths)
    con = duckdb.connect()
    row = _q(con, f"""SELECT ticker, contract, underlying, expiry, strike, "right", open, close,
                             volume, transactions
                      FROM read_parquet('{_store(paths, 'option_minute')}')""")
    assert row == [("O:FOO250117C00100000", "O:FOO250117C00100000", "FOO", date(2025, 1, 17),
                    100.0, "C", 1.25, 1.30, 5, 2)]
    ws = _q(con, f"SELECT window_start FROM read_parquet('{_store(paths, 'option_day')}')")[0][0]
    assert ws == (1735794000 * S)   # 2025-01-02 00:00 ET, the massive day-agg convention
    # same column order/types as the massive option stores (UPQ reads both in one glob)
    from qfinzero.pipeline import schema
    cols = _q(con, f"DESCRIBE SELECT * FROM read_parquet('{_store(paths, 'option_day')}')")
    assert [c[0] for c in cols] == list(schema.OPTION_DAY)


# ── DBN: OHLCV ───────────────────────────────────────────────────────────

@needs_dbn
def test_dbn_ohlcv_minute_and_daily_only(tmp_path):
    import databento_dbn as d
    paths = _paths(tmp_path)
    one_m = [d.OHLCVMsg(int(d.RType.OHLCV_1M), 2, 5, T0930 + i * 60 * S,
                        int((10 + i) * PX), int((11 + i) * PX), int((9 + i) * PX), int((10.5 + i) * PX), 100)
             for i in range(3)]
    _write_dbn(paths.databento / "a" / "BAZ.dbn", "XNAS.ITCH", "ohlcv-1m", {"BAZ": 5}, one_m)
    one_d = [d.OHLCVMsg(int(d.RType.OHLCV_1D), 2, 6, DAY_START, 20 * PX, 21 * PX, 19 * PX, 20 * PX, 900)]
    _write_dbn(paths.databento / "b" / "QUX.dbn", "XNAS.ITCH", "ohlcv-1d", {"QUX": 6}, one_d)
    _convert(paths)
    con = duckdb.connect()
    minute = _q(con, f"SELECT ticker, count(*), max(transactions) FROM read_parquet('{_store(paths, 'stock_minute')}') GROUP BY 1")
    assert minute == [("BAZ", 3, None)]          # QUX has daily bars only
    daily = _q(con, f"SELECT ticker, open, close, volume FROM read_parquet('{_store(paths, 'stock_daily')}') ORDER BY 1")
    assert daily == [("BAZ", 10.0, 12.5, 300), ("QUX", 20.0, 20.0, 900)]


# ── fill precedence + incremental re-runs ───────────────────────────────

@needs_dbn
def test_fill_precedence_and_refilter(tmp_path):
    paths = _paths(tmp_path)
    recs = [_trade(7, T0930, 100.0, 1), _trade(8, T0930, 200.0, 1)]
    _write_dbn(paths.databento / "t.dbn", "XNAS.ITCH", "trades", {"FOO": 7, "BAR": 8}, recs)
    # another vendor already wrote FOO for this date
    part = paths.partition("stock_minute", "2025-01-02")
    part.mkdir(parents=True)
    con = duckdb.connect()
    con.execute(f"""COPY (SELECT 'FOO' AS ticker, {T0930}::BIGINT AS window_start, 1.0 AS open,
                    1.0 AS high, 1.0 AS low, 1.0 AS close, 1::BIGINT AS volume,
                    1::BIGINT AS transactions, DATE '2025-01-02' AS trade_date)
                    TO '{part / 'part-0000.parquet'}' (FORMAT PARQUET)""")
    _convert(paths)
    tick = lambda: [r[0] for r in _q(con, f"SELECT ticker FROM read_parquet('{_store(paths, 'stock_minute')}')")]  # noqa: E731
    assert tick() == ["BAR"]

    # second run: nothing re-extracted, every partition skipped
    res = _convert(paths)
    assert res.partitions == 0 and res.skipped > 0
    assert any("0 extracted" in n for n in res.notes)

    # the other vendor later adds BAR: our part loses it (file removed when empty)
    con.execute(f"""COPY (SELECT * FROM read_parquet('{part / 'part-0000.parquet'}')
                    UNION ALL SELECT 'BAR', {T0930}::BIGINT, 2.0, 2.0, 2.0, 2.0, 1::BIGINT,
                    1::BIGINT, DATE '2025-01-02')
                    TO '{part / 'part-new.parquet'}' (FORMAT PARQUET)""")
    os.replace(part / "part-new.parquet", part / "part-0000.parquet")
    assert dbsrc.refilter_part(con, part) == 0
    assert not _store(paths, "stock_minute").exists()


# ── parquet exports (no databento package needed) ────────────────────────

def test_parquet_export_mbo(tmp_path):
    paths = _paths(tmp_path)
    src = paths.databento / "OCEA.MEMOIR" / "mbo" / "SPY" / "2025-01-02.parquet"
    src.parent.mkdir(parents=True)
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    con.execute(f"""COPY (
        SELECT * FROM (VALUES
          (to_timestamp(1735828200), 160, 'A', 590.0, 100, 'SPY'),
          (to_timestamp(1735828201), 160, 'T', 590.5, 10, 'SPY'),
          (to_timestamp(1735828201), 160, 'F', 590.5, 10, 'SPY'),
          (to_timestamp(1735828259), 160, 'T', 589.5, 5, 'SPY'))
        AS t(ts_event, rtype, action, price, size, symbol))
        TO '{src}' (FORMAT PARQUET)""")
    info = dbsrc.describe(src)
    assert (info.schema, info.asset, info.start) == ("mbo", "stock", "2025-01-02")
    _convert(paths)
    assert _q(con, f"SELECT ticker, open, close, volume, transactions FROM read_parquet('{_store(paths, 'stock_minute')}')") \
        == [("SPY", 590.5, 589.5, 15, 2)]


def test_reference_and_foreign_files_are_skipped(tmp_path):
    paths = _paths(tmp_path)
    con = duckdb.connect()
    ref = paths.databento / "definition.parquet"
    ref.parent.mkdir(parents=True)
    con.execute(f"""COPY (SELECT 1735828200000000000::BIGINT AS ts_event, 19 AS rtype,
                    'FOO   250117C00100000' AS symbol)
                    TO '{ref}' (FORMAT PARQUET)""")
    con.execute(f"COPY (SELECT 1 AS x) TO '{paths.databento / 'other.parquet'}' (FORMAT PARQUET)")
    (paths.databento / "_tmp").mkdir()
    con.execute(f"COPY (SELECT 1 AS x) TO '{paths.databento / '_tmp' / 'ignored.parquet'}' (FORMAT PARQUET)")
    from qfinzero.pipeline import registry
    raw = registry.scan(paths)["raw"]["databento"]
    assert raw["files"] == 2 and raw["convertible_files"] == 0
    res = _convert(paths)
    assert res.rows == 0 and any("other=1" in n for n in res.notes)


def test_parquet_cbbo_export_becomes_quotes(tmp_path):
    paths = _paths(tmp_path)
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    q = paths.databento / "cbbo" / "2025-01-02.parquet"
    q.parent.mkdir(parents=True)
    # Databento exports: float (pretty) prices, ts_recv stamped at interval end
    con.execute(f"""COPY (SELECT * FROM (VALUES
          (to_timestamp(1735828260), to_timestamp(1735828260), 193, 1.2, 1.3, 5, 7, 'FOO   250117C00100000'),
          (to_timestamp(1735828320), to_timestamp(1735828320), 193, 1.25, 'NaN'::DOUBLE, 5, 0, 'FOO   250117C00100000'))
        AS t(ts_recv, ts_event, rtype, bid_px_00, ask_px_00, bid_sz_00, ask_sz_00, symbol))
        TO '{q}' (FORMAT PARQUET)""")
    res = _convert(paths)
    out = paths.partition("option_quote_minute", "2025-01-02") / dbsrc.PART_NAME
    assert _q(con, f"SELECT window_start, bid_price, ask_price FROM read_parquet('{out}') ORDER BY 1") \
        == [(T0930, 1.2, 1.3), (T0930 + 60 * S, 1.25, None)], res.notes


def test_osi_ticker_normalisation():
    con = duckdb.connect()
    sql = dbsrc._ticker_sql("s", "a")
    got = _q(con, f"""SELECT {sql} FROM (VALUES ('SPXW  250117P05000000', 'option'),
                      ('BRK B', 'stock'), ('bad', 'option')) t(s, a)""")
    assert [g[0] for g in got] == ["O:SPXW250117P05000000", "BRK.B", None]


# ── admin: scan / acquire / update registry ─────────────────────────────

def test_scan_databento_states():
    from qfinzero.admin import scan
    assert scan.scan_databento(api_key="")["ok"] is False
    ok = scan.scan_databento(api_key="db-x", lister=lambda k: ["OPRA.PILLAR", "GLBX.MDP3", "XEUR.EOBI"])
    assert ok["ok"] and {d["name"]: d["converted"] for d in ok["datasets"]} == {
        "GLBX.MDP3": True, "OPRA.PILLAR": True, "XEUR.EOBI": False}
    bad = scan.scan_databento(api_key="db-x", lister=lambda k: (_ for _ in ()).throw(RuntimeError("401")))
    assert bad["ok"] is False and "401" in bad["error"]


class _FakeClient:
    def __init__(self, cost):
        self.calls = []
        meta = NS(get_cost=lambda **kw: cost, get_billable_size=lambda **kw: 1000)
        self.metadata = meta
        self.timeseries = NS(get_range=self._get_range)

    def _get_range(self, path, **kw):
        self.calls.append(kw)
        Path(path).write_bytes(b"DBN")


def test_databento_download_is_cost_gated(tmp_path):
    from qfinzero.admin import databento_dl
    params = {"dataset": "XNAS.ITCH", "schema": "trades", "symbols": "SPY,QQQ",
              "start": "2025-01-02", "end": "2025-01-06"}
    jobs = databento_dl.plan(params, tmp_path)
    assert len(jobs) == 6   # 3 weekdays x 2 symbols (Jan 4/5 are a weekend)
    assert jobs[0]["path"].endswith("XNAS.ITCH/trades/SPY/2025-01-02.dbn.zst")

    paid = _FakeClient(cost=1.5)
    dry = databento_dl.download(params, api_key="k", root=tmp_path, client_factory=lambda k: paid)
    assert dry["ok"] and dry["to_fetch"] == 6 and not paid.calls
    refused = databento_dl.download(params, api_key="k", root=tmp_path, dry_run=False,
                                    client_factory=lambda k: paid)
    assert refused["ok"] is False and "max_cost" in refused["error"] and not paid.calls

    free = _FakeClient(cost=0.0)
    done = databento_dl.download(params, api_key="k", root=tmp_path, dry_run=False,
                                 client_factory=lambda k: free)
    assert done["ok"] and done["written"] == 6
    again = databento_dl.download(params, api_key="k", root=tmp_path, dry_run=False,
                                  client_factory=lambda k: free)
    assert again["to_fetch"] == 0 and len(free.calls) == 6   # existing files never re-bought

    ohlcv = databento_dl.plan({**params, "schema": "ohlcv-1m"}, tmp_path)
    assert len(ohlcv) == 2 and ohlcv[0]["end"] == "2025-01-07"


def test_update_registry_has_databento_source():
    from qfinzero.update.sources import BY_ID, select
    src = BY_ID["us_databento"]
    assert src in select("prices", "us") and src not in select("prices", "cn")
    scan = {"raw": {"databento": {"end": "2025-01-03"}}, "storage": {"databento": {"end": "2025-01-02"}}}
    from qfinzero.update.freshness import compute_freshness
    assert compute_freshness(src, scan, date(2025, 1, 3)).state == "behind"


# ── storage contract: the engine reads our parts and the other vendors' parts
# with one ``read_parquet`` glob, so names, order and types must match ───────

_DUCK = {"VARCHAR": "VARCHAR", "DATE": "DATE", "DOUBLE": "DOUBLE", "BIGINT": "BIGINT"}


@needs_dbn
def test_parts_match_upq_storage_schema_exactly(tmp_path):
    import databento_dbn as d
    from qfinzero.pipeline import schema
    paths = _paths(tmp_path)
    _write_dbn(paths.databento / "s.dbn", "XNAS.ITCH", "trades", {"FOO": 7},
               [_trade(7, T0930, 100.0, 1)])
    _write_dbn(paths.databento / "o.dbn", "OPRA.PILLAR", "tcbbo", {"FOO   250117C00100000": 11},
               [d.CBBOMsg(int(d.RType.TCBBO), 30, 11, T0930, int(1.25 * PX), 3, d.Side.NONE, T0930 + 1)])
    _convert(paths)
    con = duckdb.connect()
    for store, want in (("stock_daily", schema.STOCK_DAILY), ("stock_minute", schema.STOCK_MINUTE),
                        ("option_day", schema.OPTION_DAY), ("option_minute", schema.OPTION_MINUTE)):
        got = [(r[0], r[1]) for r in _q(con, f"DESCRIBE SELECT * FROM read_parquet('{_store(paths, store)}')")]
        assert got == [(c, _DUCK[t]) for c, t in want.items()], store


@needs_dbn
def test_removed_raw_file_drops_its_parts(tmp_path):
    paths = _paths(tmp_path)
    raw = _write_dbn(paths.databento / "t.dbn", "XNAS.ITCH", "trades", {"FOO": 7},
                     [_trade(7, T0930, 100.0, 1)])
    keep = _write_dbn(paths.databento / "keep" / "t.dbn", "XNAS.ITCH", "trades", {"BAR": 8},
                      [_trade(8, T0930 + 86400 * S, 50.0, 1)])   # next day
    _convert(paths)
    assert _store(paths, "stock_minute").exists()
    raw.unlink()
    res = _convert(paths)
    assert not _store(paths, "stock_minute").exists()
    assert not _store(paths, "stock_daily").parent.exists()   # empty partition dir removed too
    assert _store(paths, "stock_minute", "2025-01-03").exists()   # the other file's day stays
    assert any("stale" in n for n in res.notes)
    staged = list(paths.databento_staging.glob("*.parquet"))
    assert len(staged) == 1 and keep.exists()


@needs_dbn
def test_cleanup_skipped_when_a_file_is_unreadable(tmp_path):
    paths = _paths(tmp_path)
    raw = _write_dbn(paths.databento / "t.dbn", "XNAS.ITCH", "trades", {"FOO": 7},
                     [_trade(7, T0930, 100.0, 1)])
    _write_dbn(paths.databento / "b.dbn", "XNAS.ITCH", "trades", {"BAR": 8},
               [_trade(8, T0930, 50.0, 1)])
    _convert(paths)
    raw.write_bytes(b"not a dbn file")          # corrupt instead of deleted
    res = _convert(paths)
    con = duckdb.connect()
    tickers = {r[0] for r in _q(con, f"SELECT ticker FROM read_parquet('{_store(paths, 'stock_minute')}')")}
    assert tickers == {"FOO", "BAR"}             # FOO kept from its last good extraction
    assert any("cleanup skipped" in n for n in res.notes)
    assert any("last good" in n for n in res.notes)


# ── overnight session (Blue Ocean, 20:00-04:00 ET) ──────────────────────

@needs_dbn
def test_overnight_venue_fills_night_without_displacing_day(tmp_path):
    paths = _paths(tmp_path)
    night = T0930 + int(11.5 * 3600) * S        # 21:00 ET on 2025-01-02
    _write_dbn(paths.databento / "ocea" / "FOO.dbn", "OCEA.MEMOIR", "mbo", {"FOO": 7},
               [_mbo(7, night, 99.0, 25, "T")], map_days=2)
    _write_dbn(paths.databento / "xnas" / "FOO.dbn", "XNAS.ITCH", "trades", {"FOO": 7},
               [_trade(7, T0930, 100.0, 10)])
    # massive already has FOO's regular session on this date
    part = paths.partition("stock_minute", "2025-01-02")
    part.mkdir(parents=True)
    con = duckdb.connect()
    con.execute(f"""COPY (SELECT 'FOO' AS ticker, {T0930}::BIGINT AS window_start, 1.0 AS open,
                    1.0 AS high, 1.0 AS low, 1.0 AS close, 500::BIGINT AS volume,
                    5::BIGINT AS transactions, DATE '2025-01-02' AS trade_date)
                    TO '{part / 'part-0000.parquet'}' (FORMAT PARQUET)""")
    _convert(paths)
    rows = _q(con, f"SELECT window_start, volume FROM read_parquet('{_store(paths, 'stock_minute')}')")
    assert rows == [(night, 25)]                 # night bar added, XNAS day bar not duplicated
    # the night trade never enters a daily bar (stock_daily comes from XNAS day trades only)
    assert _q(con, f"SELECT volume FROM read_parquet('{_store(paths, 'stock_daily')}')") == [(10,)]

    # massive re-converting the partition keeps our night bar
    assert dbsrc.refilter_part(con, part) == 1
    # Thursday 21:00 ET is Friday's overnight session
    night_part = paths.partition(dbsrc.OVERNIGHT_STORE, "2025-01-03") / dbsrc.PART_NAME
    assert _q(con, f"SELECT ticker, trade_date, close, volume FROM read_parquet('{night_part}')") \
        == [("FOO", date(2025, 1, 3), 99.0, 25)]


def _et_ns(day: str, hm: str) -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return int(datetime.fromisoformat(f"{day} {hm}").replace(tzinfo=ZoneInfo("America/New_York")).timestamp()) * S


def _book(iid, ts, oid, price, size, action, side="B"):
    import databento_dbn as d
    act = {"T": d.Action.TRADE, "F": d.Action.FILL, "A": d.Action.ADD, "C": d.Action.CANCEL,
           "M": d.Action.MODIFY, "R": d.Action.CLEAR}[action]
    sd = {"B": d.Side.BID, "A": d.Side.ASK, "N": d.Side.NONE}[side]
    px = dbsrc.UNDEF_PRICE if price is None else int(round(price * PX))
    return d.MBOMsg(2, iid, ts, oid, px, size, act, sd, ts)


@needs_dbn
def test_asset_filter_skips_other_asset_files(tmp_path):
    paths = _paths(tmp_path)
    _write_dbn(paths.databento / "xnas" / "FOO.dbn", "XNAS.ITCH", "trades", {"FOO": 7},
               [_trade(7, T0930, 100.0, 10)])
    _write_dbn(paths.databento / "glbx" / "ZN.dbn", "GLBX.MDP3", "trades", {"ZN.v.0": 42},
               [_trade(42, T0930, 110.5, 3)])
    res = _convert(paths, assets=("stock",))
    assert any("1 extracted" in n for n in res.notes), res.notes
    assert _store(paths, "stock_minute").exists() and not _store(paths, "future_minute").exists()


def test_overnight_sessions_follow_the_trading_calendar():
    # Sunday night and Monday morning are Monday's session; Friday night has none
    assert dbsrc.overnight_sessions(["2025-01-05"])["2025-01-06"] == ("2025-01-03", "2025-01-06")
    # 2025-01-09 was a market closure: Wednesday night and Thursday morning go to Friday
    s = dbsrc.overnight_sessions(["2025-01-08", "2025-01-09"])
    assert s["2025-01-10"] == ("2025-01-08", "2025-01-10")
    assert "2025-01-09" not in s


def test_replay_mbo_book_keeps_the_last_book_per_minute():
    import numpy as np
    m = dbsrc.NS_PER_MIN
    t0 = 1_735_869_600 * S                 # 21:00 ET 2025-01-02
    dt = np.dtype([("ts_recv", "u8"), ("instrument_id", "u4"), ("order_id", "u8"), ("price", "i8"),
                   ("size", "u4"), ("action", "S1"), ("side", "S1")])
    P = PX
    recs = np.array([
        (t0, 7, 1, 99 * P, 100, b"A", b"B"),
        (t0 + 10 * S, 7, 2, int(99.5 * P), 50, b"A", b"A"),
        (t0 + 20 * S, 7, 3, int(99.1 * P), 30, b"A", b"B"),
        (t0 + m + 5 * S, 7, 3, int(99.1 * P), 10, b"F", b"B"),     # passive fill: 20 left
        (t0 + m + 30 * S, 7, 3, int(99.1 * P), 20, b"C", b"B"),    # cancel the rest
        (t0 + m + 40 * S, 7, 0, int(99.2 * P), 5, b"T", b"N"),     # trades leave the book alone
        (t0 + 2 * m, 7, 2, int(99.4 * P), 60, b"M", b"A"),         # ask moves
        (t0 + 3 * m, 7, 0, dbsrc.UNDEF_PRICE, 0, b"R", b"N"),      # clear
    ], dtype=dt)
    out = dbsrc.replay_mbo_book([recs[:4], recs[4:]])
    rows = list(zip(out["ws"], out["bid"], out["ask"], out["bsz"], out["asz"]))
    assert rows == [(t0, int(99.1 * P), int(99.5 * P), 30, 50),
                    (t0 + m, 99 * P, int(99.5 * P), 100, 50),
                    (t0 + 2 * m, 99 * P, int(99.4 * P), 100, 60),
                    (t0 + 3 * m, None, None, 0, 0)]


@needs_dbn
def test_blue_ocean_book_becomes_overnight_quotes_and_sessions(tmp_path):
    paths = _paths(tmp_path)
    sun, mon = "2025-01-05", "2025-01-06"
    a = _et_ns(sun, "21:00:00")
    recs = [
        _book(7, a, 1, 99.00, 100, "A", "B"),
        _book(7, a + 10 * S, 2, 99.50, 50, "A", "A"),
        _book(7, a + 20 * S, 0, 99.20, 10, "T", "N"),
        _book(7, _et_ns(mon, "01:00:00"), 0, 99.40, 15, "T", "N"),
        _book(7, _et_ns(mon, "01:00:30"), 2, 99.30, 50, "M", "A"),
        _book(7, _et_ns(mon, "21:30:00"), 0, 98.00, 5, "T", "N"),     # Tuesday's session
    ]
    _write_dbn(paths.databento / "ocea" / "FOO" / f"{sun}.dbn", "OCEA.MEMOIR", "mbo", {"FOO": 7}, recs,
               map_days=10)
    res = _convert(paths)
    assert res.rows > 0, res.notes
    con = duckdb.connect()
    q = paths.partition("stock_quote_minute", sun) / dbsrc.PART_NAME
    assert _q(con, f"SELECT ticker, window_start, bid_price, ask_price, bid_size, ask_size FROM read_parquet('{q}')") \
        == [("FOO", a, 99.0, 99.5, 100, 50)]
    q2 = paths.partition("stock_quote_minute", mon) / dbsrc.PART_NAME
    assert _q(con, f"SELECT window_start, ask_price FROM read_parquet('{q2}')") \
        == [(_et_ns(mon, "01:00:00"), 99.3)]
    night = lambda d: paths.partition(dbsrc.OVERNIGHT_STORE, d) / dbsrc.PART_NAME  # noqa: E731
    # Sunday 21:00 and Monday 01:00 are one session, dated Monday
    assert _q(con, f"SELECT trade_date, open, high, low, close, volume, transactions, first_window_start, "
                   f"last_window_start FROM read_parquet('{night(mon)}')") \
        == [(date(2025, 1, 6), 99.2, 99.4, 99.2, 99.4, 25, 2, a, _et_ns(mon, "01:00:00"))]
    assert _q(con, f"SELECT trade_date, close FROM read_parquet('{night('2025-01-07')}')") \
        == [(date(2025, 1, 7), 98.0)]
    # overnight bars stay out of the regular daily store
    assert not (paths.partition("stock_daily", sun) / dbsrc.PART_NAME).exists()


# ── quote stores ─────────────────────────────────────────────────────────

def _cbbo(rtype, iid, ts_recv, bid, ask, bsz=5, asz=7, price=None, size=0):
    import databento_dbn as d
    lv = d.ConsolidatedBidAskPair(bid_px=int(round(bid * PX)), ask_px=int(round(ask * PX)),
                                  bid_sz=bsz, ask_sz=asz)
    p = int(round(price * PX)) if price is not None else dbsrc.UNDEF_PRICE
    return d.CBBOMsg(rtype, 30, iid, ts_recv, p, size, d.Side.NONE, ts_recv, levels=lv)


@needs_dbn
def test_cbbo_1m_becomes_option_quote_minute(tmp_path):
    import databento_dbn as d
    paths = _paths(tmp_path)
    osi = "FOO   250117C00100000"
    r = int(d.RType.CBBO_1M)
    # sampled schemas stamp ts_recv at the END of the interval: 09:31:00 -> minute 09:30
    recs = [_cbbo(r, 11, T0930 + 60 * S, 1.20, 1.30), _cbbo(r, 11, T0930 + 120 * S, 1.25, 1.35)]
    _write_dbn(paths.databento / "cbbo" / "FOO.dbn.zst", "OPRA.PILLAR", "cbbo-1m", {osi: 11}, recs,
               compress=True)
    res = _convert(paths)
    assert res.rows == 2, res.notes
    con = duckdb.connect()
    q = paths.partition("option_quote_minute", "2025-01-02") / dbsrc.PART_NAME
    got = _q(con, f"SELECT contract, underlying, strike, \"right\", window_start, bid_price, ask_price, "
                  f"bid_size, ask_size FROM read_parquet('{q}') ORDER BY window_start")
    assert got == [("O:FOO250117C00100000", "FOO", 100.0, "C", T0930, 1.20, 1.30, 5, 7),
                   ("O:FOO250117C00100000", "FOO", 100.0, "C", T0930 + 60 * S, 1.25, 1.35, 5, 7)]
    from qfinzero.pipeline import schema
    cols = [(c[0], c[1]) for c in _q(con, f"DESCRIBE SELECT * FROM read_parquet('{q}')")]
    assert cols == [(c, _DUCK[t]) for c, t in schema.OPTION_QUOTE_MINUTE.items()]
    # quote-only files produce no bars
    assert not (paths.partition("option_minute", "2025-01-02") / dbsrc.PART_NAME).exists()


def test_quote_sampling_keeps_the_last_book_per_bucket():
    import duckdb as _duckdb

    from qfinzero.pipeline.sources import databento as _db
    m = _db.NS_PER_MIN
    base = 1_781_791_200_000_000_000          # 14:00 UTC, a 15-minute boundary
    _duckdb.sql("CREATE OR REPLACE TEMP TABLE qq AS SELECT 'X' AS ticker, "
                f"{base} + i * {m} AS window_start, i AS bid FROM range(40) t(i)")
    got = _duckdb.sql(_db.sample_sql("qq", 15) + " ORDER BY window_start").fetchall()
    assert [r[2] for r in got] == [14, 29, 39]
    assert len(_duckdb.sql(_db.sample_sql("qq", 1)).fetchall()) == 40
    with pytest.raises(ValueError):
        _db.check_interval(7)


@needs_dbn
def test_glbx_trades_become_future_stores_by_cme_session(tmp_path):
    from qfinzero.pipeline import schema
    paths = _paths(tmp_path)
    m = 60 * S
    eve = DAY_START + (23 * 60 + 30) * m             # 23:30 UTC = 18:30 ET: next session
    recs = [
        _trade(42, T0930, 110.5, 3),
        _trade(42, T0930 + 20 * S, 110.75, 2),
        _trade(42, DAY_START + 21 * 3600 * S + 30 * m, 110.25, 4),   # 16:30 ET, same session
        _trade(42, eve, 111.0, 1),
        _trade(43, T0930, 110.0, 5),
        _trade(44, T0930, 0.25, 9),                                    # calendar spread
    ]
    _write_dbn(paths.databento / "GLBX.MDP3" / "trades" / "2025-01-02.dbn.zst", "GLBX.MDP3", "trades",
               {"ZN.v.0": 42, "ZNH5": 43, "ZNH5-ZNM5": 44}, recs, compress=True)
    res = _convert(paths)
    assert res.rows > 0, res.notes
    con = duckdb.connect()
    bars = _q(con, f"SELECT ticker, root, window_start, open, close, volume "
                   f"FROM read_parquet('{_store(paths, 'future_minute')}') ORDER BY 1, 3")
    assert bars == [("ZN", "ZN", T0930, 110.5, 110.75, 5),
                    ("ZN", "ZN", DAY_START + 21 * 3600 * S + 30 * m, 110.25, 110.25, 4),
                    ("ZNH5", "ZN", T0930, 110.0, 110.0, 5)]
    nxt = _q(con, f"SELECT ticker, volume FROM read_parquet('{_store(paths, 'future_minute', '2025-01-03')}')")
    assert nxt == [("ZN", 1)]
    # only the evening of the 2025-01-03 session is in the file: no daily bar for it
    assert not _store(paths, "future_daily", "2025-01-03").exists()
    day = _q(con, f"SELECT ticker, root, open, high, low, close, settle, volume "
                  f"FROM read_parquet('{_store(paths, 'future_daily')}') ORDER BY 1")
    assert day == [("ZN", "ZN", 110.5, 110.75, 110.25, 110.25, 110.25, 9),
                   ("ZNH5", "ZN", 110.0, 110.0, 110.0, 110.0, 110.0, 5)]
    for store, want in (("future_daily", schema.FUTURE_DAILY), ("future_minute", schema.FUTURE_MINUTE)):
        got = [(r[0], r[1]) for r in _q(con, f"DESCRIBE SELECT * FROM read_parquet('{_store(paths, store)}')")]
        assert got == [(c, _DUCK[t]) for c, t in want.items()], store
    assert not _store(paths, "stock_minute").exists()


def test_future_root_and_asset_mapping():
    con = duckdb.connect()
    roots = _q(con, f"SELECT ticker, {dbsrc.FUTURE_ROOT_SQL} FROM (VALUES ('ZN'), ('ZNZ6'), ('ESZ26'), "
                    "('MNQ'), ('6EH7'), ('M2KU6'), ('CL.v.1')) t(ticker) ORDER BY 1")
    assert dict(roots) == {"ZN": "ZN", "ZNZ6": "ZN", "ESZ26": "ES", "MNQ": "MNQ", "6EH7": "6E",
                           "M2KU6": "M2K", "CL.v.1": "CL"}
    assert dbsrc.asset_for_dataset("GLBX.MDP3") == "future"
    assert dbsrc.asset_for_dataset("XNAS.ITCH") == "stock"


@needs_dbn
def test_glbx_mbp1_becomes_future_quotes(tmp_path):
    import databento_dbn as d
    paths = _paths(tmp_path)

    def rec(ts, bid, ask, action=d.Action.ADD, price=None, size=0):
        lv = d.BidAskPair(bid_px=int(bid * PX), ask_px=int(ask * PX), bid_sz=12, ask_sz=9)
        p = int(price * PX) if price is not None else dbsrc.UNDEF_PRICE
        return d.MBP1Msg(1, 42, ts, p, size, action, d.Side.NONE, 0, ts, levels=lv)

    recs = [rec(T0930 + 5 * S, 110.5, 110.515625),
            rec(T0930 + 30 * S, 110.515625, 110.53125, d.Action.TRADE, price=110.53125, size=4),
            rec(T0930 + 61 * S, 110.53125, 110.546875)]
    _write_dbn(paths.databento / "GLBX.MDP3" / "mbp-1" / "ZN.dbn", "GLBX.MDP3", "mbp-1", {"ZN.v.0": 42}, recs)
    _convert(paths, quote_interval={"future": 1})
    con = duckdb.connect()
    quotes = _store(paths, "future_quote_minute")
    assert _q(con, f"SELECT ticker, root, window_start, bid_price, ask_price, bid_size FROM read_parquet('{quotes}') "
                   "ORDER BY window_start") == [("ZN", "ZN", T0930, 110.515625, 110.53125, 12),
                                                ("ZN", "ZN", T0930 + 60 * S, 110.53125, 110.546875, 12)]
    assert _q(con, f"SELECT close, volume FROM read_parquet('{_store(paths, 'future_minute')}')") == [(110.53125, 4)]


@needs_dbn
def test_glbx_statistics_settle_and_instrument_ids(tmp_path):
    import databento_dbn as d
    paths = _paths(tmp_path)
    _write_dbn(paths.databento / "GLBX.MDP3" / "trades" / "2025-01-02.dbn", "GLBX.MDP3", "trades",
               {"ZN.v.0": 42}, [_trade(42, T0930, 110.5, 3), _trade(42, T0930 + 3600 * S * 3, 110.25, 2)])

    def stat(price, recv, flags):
        return d.StatMsg(1, 42, recv, recv, DAY_START, int(round(price * PX)), 0, d.StatType.SETTLEMENT_PRICE,
                         stat_flags=flags)
    _write_dbn(paths.databento / "GLBX.MDP3" / "statistics" / "2025-01-02.dbn", "GLBX.MDP3", "statistics",
               {"ZN.v.0": 42}, [stat(110.3, T0930 + 7 * 3600 * S, 0), stat(110.375, T0930 + 8 * 3600 * S, 1),
                                stat(110.9, T0930 + 9 * 3600 * S, 0)])   # a later preliminary loses to the final
    res = _convert(paths)
    assert res.rows > 0, res.notes
    con = duckdb.connect()
    day = _q(con, f"SELECT ticker, instrument_id, close, settle, settle_source "
                  f"FROM read_parquet('{_store(paths, 'future_daily')}')")
    assert day == [("ZN", 42, 110.25, 110.375, "exchange")]
    ids = _q(con, f"SELECT DISTINCT instrument_id FROM read_parquet('{_store(paths, 'future_minute')}')")
    assert ids == [(42,)]
