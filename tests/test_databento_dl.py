"""Databento downloads into the library layout v2:
<asset>/<dataset>/<schema>/<SYMBOL>/<YYYY-MM-DD>.dbn.zst, one day per file."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero.admin import databento_dl as dl  # noqa: E402

S = 1_000_000_000
ET = ZoneInfo("America/New_York")
PX = 10**9


# ── the layout table ───────────────────────────────────────────────────────

def test_asset_and_symbol_directories():
    assert dl.asset_dir("OPRA.PILLAR") == "options"
    assert dl.asset_dir("GLBX.MDP3") == "futures" and dl.asset_dir("XEUR.EOBI") == "futures"
    for ds in ("XNAS.ITCH", "EQUS.MINI", "DBEQ.BASIC", "OCEA.MEMOIR", "IEXG.TOPS", "XCIS.TRADESBBO"):
        assert dl.asset_dir(ds) == "equity", ds
    with pytest.raises(ValueError, match="asset table"):
        dl.asset_dir("XTSE.FOO")
    assert dl.symbol_dir("equity", "BRK B") == "BRK.B"
    assert dl.symbol_dir("equity", "AAPL") == "AAPL"
    assert dl.symbol_dir("options", "SPY.OPT") == "SPY"
    assert dl.symbol_dir("options", "SPY   250117C00500000") == "SPY"
    assert dl.symbol_dir("options", "NVDA") == "NVDA"
    assert dl.symbol_dir("futures", "ZN.v.0") == "ZN"
    assert dl.symbol_dir("futures", "ZNZ6") == "ZN" and dl.symbol_dir("futures", "ESZ26") == "ES"
    assert dl.symbol_dir("futures", "ZN.FUT") == "ZN" and dl.symbol_dir("futures", "CL") == "CL"
    assert dl.symbol_dir("futures", "ZNZ6-ZNH7") == "ZN"


def test_plan_paths_groups_and_windows(tmp_path):
    jobs = dl.plan({"dataset": "OPRA.PILLAR", "schema": "cbbo-1m", "symbols": "SPY.OPT,QQQ.OPT",
                    "start": "2026-10-16", "end": "2026-10-19"}, tmp_path)
    assert len(jobs) == 8                       # every calendar day; empty ones are learnt, not guessed
    assert jobs[0]["path"] == str(tmp_path / "options/OPRA.PILLAR/cbbo-1m/QQQ/2026-10-16.dbn.zst") \
        or jobs[0]["path"] == str(tmp_path / "options/OPRA.PILLAR/cbbo-1m/SPY/2026-10-16.dbn.zst")
    # two continuous futures of one product share a directory and a request
    jobs = dl.plan({"dataset": "GLBX.MDP3", "schema": "ohlcv-1m", "symbols": "ZN.v.0,ZN.v.1",
                    "start": "2026-09-01", "end": "2026-09-03"}, tmp_path)
    assert {j["dir"] for j in jobs} == {"ZN"} and all(j["symbols"] == ["ZN.v.0", "ZN.v.1"] for j in jobs)
    rs = dl.runs(jobs, "GLBX.MDP3", "ohlcv-1m")
    assert len(rs) == 1 and rs[0]["start"].startswith("2026-09-01T00:00:00") and rs[0]["end"].startswith("2026-09-04T00:00:00")
    # tick schemas: a week per request
    ticks = dl.plan({"dataset": "XNAS.ITCH", "schema": "trades", "symbols": "AAPL", "start": "2026-09-01",
                     "end": "2026-09-20"}, tmp_path)
    assert [len(r["jobs"]) for r in dl.runs(ticks, "XNAS.ITCH", "trades")] == [7, 7, 6]
    # Blue Ocean: a file is the 20:00-04:00 ET session opening on its date
    ocea = dl.plan({"dataset": "OCEA.MEMOIR", "schema": "bbo-1m", "symbols": "AAPL", "start": "2026-10-18",
                    "end": "2026-10-19"}, tmp_path)
    r = dl.runs(ocea, "OCEA.MEMOIR", "bbo-1m")[0]
    assert r["start"] == "2026-10-19T00:00:00+00:00" and r["end"] == "2026-10-20T08:00:00+00:00"   # EDT
    assert ocea[0]["path"].endswith("equity/OCEA.MEMOIR/bbo-1m/AAPL/2026-10-18.dbn.zst")


# ── a fake Databento that writes real DBN ───────────────────────────────────

def _dbn(path: Path, dataset: str, schema: str, symbols: list[str], start: int, end: int, records: list) -> None:
    import databento_dbn as d
    import zstandard
    d0 = datetime.fromtimestamp(start / S, tz=timezone.utc).date()
    d1 = datetime.fromtimestamp((end - 1) / S, tz=timezone.utc).date() + timedelta(days=1)
    md = d.Metadata(dataset=dataset, start=start, end=end, stype_in=d.SType.RAW_SYMBOL,
                    stype_out=d.SType.INSTRUMENT_ID, schema=d.Schema.from_str(schema), symbols=symbols,
                    mappings=[NS(raw_symbol=s, intervals=[NS(start_date=d0, end_date=d1, symbol=str(100 + i))])
                              for i, s in enumerate(symbols)])
    path.write_bytes(zstandard.ZstdCompressor().compress(bytes(md.encode()) + b"".join(bytes(r) for r in records)))


class FakeDatabento:
    """One record per symbol at each of ``times`` (UTC ns) inside the requested window."""

    def __init__(self, times: list[int], cost: float = 0.0, check_env: bool = False):
        self.times, self.cost, self.calls, self.check_env = times, cost, [], check_env
        self.metadata = NS(get_cost=lambda **k: self.cost, get_billable_size=lambda **k: 1000)
        self.timeseries = NS(get_range=self._get)

    def _get(self, dataset, schema, symbols, start, end, path, **_k):
        import databento_dbn as d
        if self.check_env:
            assert not any(k in os.environ for k in dl._PROXY_VARS), "a proxy variable is set"
        lo = int(datetime.fromisoformat(start).timestamp()) * S
        hi = int(datetime.fromisoformat(end).timestamp()) * S
        self.calls.append((tuple(symbols), start, end))
        recs = []
        for t in sorted(t for t in self.times if lo <= t < hi):
            for i, _ in enumerate(symbols):
                if schema.startswith("ohlcv"):
                    recs.append(d.OHLCVMsg(int(d.RType.OHLCV_1M), 1, 100 + i, t, PX, 2 * PX, PX, PX, 5))
                else:
                    recs.append(d.TradeMsg(1, 100 + i, t, PX, 1, d.Action.TRADE, d.Side.NONE, 0, t))
        _dbn(Path(path), dataset, schema, list(symbols), lo, hi, recs)


def _utc(day: str, hm: str = "15:00") -> int:
    return int(datetime.fromisoformat(f"{day}T{hm}:00+00:00").timestamp()) * S


def test_a_range_is_split_into_day_files_and_empty_days_are_remembered(tmp_path):
    pytest.importorskip("databento_dbn")
    from qfinzero.admin import dbn_split
    times = [_utc("2026-09-04"), _utc("2026-09-04", "16:00"), _utc("2026-09-07")]   # Fri, Mon; weekend empty
    c = FakeDatabento(times)
    params = {"dataset": "GLBX.MDP3", "schema": "ohlcv-1m", "symbols": "ZN.v.0", "stype_in": "continuous",
              "start": "2026-09-04", "end": "2026-09-07"}
    r = dl.download(params, api_key="k", root=tmp_path, dry_run=False, client_factory=lambda _k: c)
    assert r["ok"], r
    assert (r["written"], r["empty"], r["requests"], len(c.calls)) == (2, 2, 1, 1)
    d = tmp_path / "futures/GLBX.MDP3/ohlcv-1m/ZN"
    assert sorted(p.name for p in d.iterdir()) == ["2026-09-04.dbn.zst", "2026-09-07.dbn.zst"]
    _, body = dbn_split.read(d / "2026-09-04.dbn.zst")
    assert len(body) == 2 * 56
    assert dbn_split.header_symbols(d / "2026-09-07.dbn.zst") == ["ZN.v.0"]
    import databento as db
    st = db.DBNStore.from_file(d / "2026-09-04.dbn.zst")
    assert st.metadata.start == _utc("2026-09-04", "00:00") and st.to_df(map_symbols=True)["symbol"].tolist() == ["ZN.v.0"] * 2
    ledger = [json.loads(x) for x in (tmp_path / "_meta/qfz_downloads.jsonl").read_text().splitlines()]
    assert sorted((x["day"], x["status"]) for x in ledger) == [("2026-09-04", "written"), ("2026-09-05", "empty"),
                                                                ("2026-09-06", "empty"), ("2026-09-07", "written")]
    assert not list((tmp_path / "_meta/tmp").iterdir())
    # a re-run asks for nothing: files present, empty days remembered
    again = dl.download(params, api_key="k", root=tmp_path, dry_run=True, client_factory=lambda _k: c)
    assert again["to_fetch"] == 0 and again["requests"] == 0 and again["files"] == 4


def test_a_day_file_without_a_symbol_is_replaced_by_the_union(tmp_path):
    pytest.importorskip("databento_dbn")
    from qfinzero.admin import dbn_split
    c = FakeDatabento([_utc("2026-09-01")])
    base = {"dataset": "GLBX.MDP3", "schema": "trades", "stype_in": "continuous", "start": "2026-09-01"}
    assert dl.download({**base, "symbols": "ZN.v.0"}, api_key="k", root=tmp_path, dry_run=False,
                       client_factory=lambda _k: c)["written"] == 1
    jobs = dl.plan({**base, "symbols": "ZN.v.1"}, tmp_path)
    assert jobs[0]["replace"] and jobs[0]["symbols"] == ["ZN.v.0", "ZN.v.1"]
    r = dl.download({**base, "symbols": "ZN.v.1"}, api_key="k", root=tmp_path, dry_run=False,
                    client_factory=lambda _k: c)
    assert r["ok"] and c.calls[-1][0] == ("ZN.v.0", "ZN.v.1")
    f = tmp_path / "futures/GLBX.MDP3/trades/ZN/2026-09-01.dbn.zst"
    assert dbn_split.header_symbols(f) == ["ZN.v.0", "ZN.v.1"]


def test_blue_ocean_sessions_split_by_the_et_date_they_open(tmp_path):
    pytest.importorskip("databento_dbn")

    def et(day, hm):
        return int(datetime.fromisoformat(f"{day} {hm}").replace(tzinfo=ET).timestamp()) * S
    c = FakeDatabento([et("2026-10-18", "21:00"), et("2026-10-19", "01:00"), et("2026-10-19", "22:00")])
    r = dl.download({"dataset": "OCEA.MEMOIR", "schema": "ohlcv-1m", "symbols": "AAPL", "start": "2026-10-18",
                     "end": "2026-10-19"}, api_key="k", root=tmp_path, dry_run=False, client_factory=lambda _k: c)
    assert r["ok"] and r["written"] == 2
    from qfinzero.admin import dbn_split
    d = tmp_path / "equity/OCEA.MEMOIR/ohlcv-1m/AAPL"
    assert len(dbn_split.read(d / "2026-10-18.dbn.zst")[1]) == 2 * len(dbn_split.read(d / "2026-10-19.dbn.zst")[1])


def test_downloads_bypass_the_proxy(tmp_path, monkeypatch):
    pytest.importorskip("databento_dbn")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:17890")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:17890")
    c = FakeDatabento([_utc("2026-09-01")], check_env=True)
    r = dl.download({"dataset": "XNAS.ITCH", "schema": "trades", "symbols": "AAPL", "start": "2026-09-01"},
                    api_key="k", root=tmp_path, dry_run=False, client_factory=lambda _k: c)
    assert r["ok"], r
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:17890"      # restored afterwards


def test_the_converter_finds_the_new_layout(tmp_path):
    pytest.importorskip("databento_dbn")
    pytest.importorskip("duckdb")
    from qfinzero.pipeline.sources import databento as dbsrc
    c = FakeDatabento([_utc("2026-09-01"), _utc("2026-09-02")])
    dl.download({"dataset": "XNAS.ITCH", "schema": "trades", "symbols": "BRK B", "start": "2026-09-01",
                 "end": "2026-09-02"}, api_key="k", root=tmp_path, dry_run=False, client_factory=lambda _k: c)
    (tmp_path / "equity/XNAS.ITCH/trades/BRK.B/2026-09-03.dbn.zst.part").write_bytes(b"partial")
    infos = dbsrc.index(tmp_path)
    assert sorted(Path(i.path).relative_to(tmp_path).as_posix() for i in infos) == [
        "equity/XNAS.ITCH/trades/BRK.B/2026-09-01.dbn.zst", "equity/XNAS.ITCH/trades/BRK.B/2026-09-02.dbn.zst"]
    assert {(i.dataset, i.schema, i.asset) for i in infos} == {("XNAS.ITCH", "trades", "stock")}
    assert all(i.convertible for i in infos)
