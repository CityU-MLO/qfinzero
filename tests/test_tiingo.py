"""Tiingo BOATS: download into the raw library, convert behind Databento."""

from __future__ import annotations

import gzip
import io
import json
import os
import sys
import urllib.error
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

duckdb = pytest.importorskip("duckdb")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero.admin import tiingo_dl  # noqa: E402
from qfinzero.pipeline.paths import resolve  # noqa: E402
from qfinzero.pipeline.sources import databento as dbsrc, tiingo  # noqa: E402

ET = ZoneInfo("America/New_York")
S = 1_000_000_000


def et(day: str, hm: str) -> datetime:
    return datetime.fromisoformat(f"{day} {hm}").replace(tzinfo=ET)


def iso(day: str, hm: str) -> str:
    return et(day, hm).astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ns(day: str, hm: str) -> int:
    return int(et(day, hm).timestamp()) * S


# ── client and downloads ───────────────────────────────────────────────────

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_client_sends_the_token_and_treats_404_as_empty(monkeypatch):
    seen = []

    def opener(req, timeout):
        seen.append(req)
        if "missing" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b""))
        return _Resp(b'[{"ticker": "aapl"}]')

    c = tiingo_dl.Client("k-1", opener=opener)
    assert c.get("/boats/aapl") == [{"ticker": "aapl"}]
    assert c.get("/boats/missing/prices") == []
    assert seen[0].headers["Authorization"] == "Token k-1"
    with pytest.raises(ValueError):
        tiingo_dl.Client("")


class FakeClient:
    def __init__(self, bars=None, snap=None):
        self.bars, self.snap, self.calls = bars or {}, snap or [], []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path == "/boats":
            return self.snap
        t = path.split("/")[2].upper()
        return self.bars.get(t, [])


def test_download_prices_writes_months_and_skips_finished_ones(tmp_path, monkeypatch):
    rows = [{"date": iso("2026-07-07", "21:00"), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 5}]
    c = FakeClient(bars={"AAA": rows}, snap=[{"ticker": "aaa"}, {"ticker": "bbb"}])
    r = tiingo_dl.download_prices(root=tmp_path, start="2026-07-01", end="2026-08-31", client=c)
    assert r["requests"] == 4 and r["files"] == 2 and r["empty"] == 2      # 2 tickers x 2 months
    f = tmp_path / "boats" / "prices" / "2026-07" / "AAA.json.gz"
    assert json.loads(gzip.decompress(f.read_bytes())) == rows
    # the session of a month's last day ends the next morning: one day further
    assert c.calls[1][1]["endDate"] == "2026-08-01" and c.calls[1][1]["resampleFreq"] == "1min"
    again = tiingo_dl.download_prices(root=tmp_path, start="2026-07-01", end="2026-08-31", client=c)
    assert again["requests"] == 2          # July AAA is done; empty answers are asked again
    assert not any(p.suffix == ".tmp" for p in tmp_path.rglob("*"))


def test_session_window():
    assert tiingo_dl.in_session(et("2026-10-18", "21:00"))       # Sunday night
    assert tiingo_dl.in_session(et("2026-10-19", "03:59"))       # Monday morning
    assert not tiingo_dl.in_session(et("2026-10-19", "04:00"))
    assert not tiingo_dl.in_session(et("2026-10-23", "21:00"))   # Friday night: closed
    assert not tiingo_dl.in_session(et("2026-10-24", "01:00"))   # Saturday morning


def test_record_quotes_returns_outside_the_session_and_when_already_running(tmp_path):
    import fcntl
    c = FakeClient(snap=[])
    r = tiingo_dl.record_quotes(root=tmp_path, client=c, now=lambda: et("2026-10-19", "12:00"))
    assert r["snapshots"] == 0 and "outside" in r["note"] and c.calls == []
    lockdir = tmp_path / "boats" / "quotes"
    lockdir.mkdir(parents=True)
    with open(lockdir / ".recording.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        r = tiingo_dl.record_quotes(root=tmp_path, client=c, now=lambda: et("2026-10-19", "21:00"))
    assert r["note"] == "already recording" and c.calls == []


def test_record_quotes_takes_one_snapshot_a_minute(tmp_path):
    clock = iter([et("2026-10-19", "21:00:05"), et("2026-10-19", "21:00:06"),
                  et("2026-10-19", "21:01:04"), et("2026-10-19", "21:01:05")])
    slept = []
    c = FakeClient(snap=[{"ticker": "aaa", "bidPrice": 1.0, "askPrice": 1.1}])
    r = tiingo_dl.record_quotes(root=tmp_path, minutes=2, client=c, now=lambda: next(clock), sleep=slept.append)
    assert r["snapshots"] == 2
    assert sorted(p.name for p in (tmp_path / "boats" / "quotes" / "2026-10-19").iterdir()) == ["2100.json.gz",
                                                                                               "2101.json.gz"]
    assert round(slept[0]) == 57          # to the next minute boundary + 3 s


# ── conversion ─────────────────────────────────────────────────────────────

def _gz(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(obj).encode()))


def _bar(day, hm, px, vol):
    return {"date": iso(day, hm), "open": px, "high": px + 0.5, "low": px - 0.5, "close": px, "volume": vol}


def test_convert_fills_behind_databento(tmp_path):
    from qfinzero.pipeline.convert import Converter
    paths = resolve(tmp_path / "massive", tmp_path / "tushare", tmp_path / "storage", tmp_path / "databento",
                    tmp_path / "tiingo")
    sun, mon = "2025-01-05", "2025-01-06"
    prices = tmp_path / "tiingo" / "boats" / "prices" / "2025-01"
    for t in ("AAA", "BBB"):
        _gz(prices / f"{t}.json.gz", [_bar(sun, "21:00", 10.0, 100), _bar(sun, "21:01", 10.5, 0),   # zero volume
                                      _bar(mon, "01:00", 11.0, 50), _bar(mon, "09:30", 99.0, 7)])  # daytime
    q = tmp_path / "tiingo" / "boats" / "quotes" / sun
    snap = lambda bid: [{"ticker": t, "quoteTimestamp": iso(sun, "21:00:30"), "bidPrice": bid,  # noqa: E731
                         "askPrice": bid + 0.1, "bidSize": 100, "askSize": 200} for t in ("aaa", "bbb")]
    _gz(q / "2100.json.gz", snap(10.0))
    _gz(q / "2101.json.gz", snap(10.0))                        # unchanged book: same row
    # Databento's Blue Ocean book already has AAA that night
    con = duckdb.connect()
    for store, d, cols in (("stock_minute", sun, f"{ns(sun, '21:00')}::BIGINT AS window_start, 1.0 AS open, "
                            "1.0 AS high, 1.0 AS low, 1.0 AS close, 1::BIGINT AS volume, 1::BIGINT AS transactions"),
                           ("stock_overnight_daily", mon, "1.0 AS close, 1::BIGINT AS volume")):
        part = paths.partition(store, d) / dbsrc.PART_NAME
        part.parent.mkdir(parents=True)
        con.execute(f"COPY (SELECT 'AAA' AS ticker, {cols}, DATE '{d}' AS trade_date) TO '{part}' (FORMAT PARQUET)")

    with Converter(paths) as cv:
        res = cv.convert_tiingo()
    assert res.rows > 0, res.notes
    tp = lambda store, d: paths.partition(store, d) / tiingo.PART_NAME  # noqa: E731
    rows = con.execute(f"SELECT ticker, window_start, close, volume FROM read_parquet('{tp('stock_minute', sun)}')").fetchall()
    assert rows == [("BBB", ns(sun, "21:00"), 10.0, 100)]      # AAA left to Databento; zero volume dropped
    assert con.execute(f"SELECT ticker, close FROM read_parquet('{tp('stock_minute', mon)}')").fetchall() \
        == [("AAA", 11.0), ("BBB", 11.0)]                        # no Databento AAA in Monday's partition
    day = con.execute(f"SELECT ticker, trade_date, open, high, low, close, volume, first_window_start, last_window_start "
                      f"FROM read_parquet('{tp('stock_overnight_daily', mon)}')").fetchall()
    assert day == [("BBB", date(2025, 1, 6), 10.0, 11.5, 9.5, 11.0, 150, ns(sun, "21:00"), ns(mon, "01:00"))]
    qrows = con.execute(f"SELECT ticker, window_start, bid_price, ask_price, bid_size, ask_size "
                        f"FROM read_parquet('{tp('stock_quote_minute', sun)}')").fetchall()
    assert qrows == [("AAA", ns(sun, "21:00"), 10.0, 10.1, 100, 200), ("BBB", ns(sun, "21:00"), 10.0, 10.1, 100, 200)]
    # Databento never treats a Tiingo part as a vendor to fill behind
    assert dbsrc.sibling_parts(paths.partition("stock_minute", sun)) == []
    # unchanged inputs: nothing rebuilt
    with Converter(paths) as cv:
        again = cv.convert_tiingo()
    assert again.partitions == 0 and again.skipped > 0
