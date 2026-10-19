"""Data setup utility: file browser, import of local files, massive downloads."""

import gzip
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from qfinzero.admin import datasetup, massive_dl

COLS = ["ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"]


def _rows(d: str):
    ns = int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp() * 1e9)
    return [("AAA", 100, 10.0, 10.5, 10.8, 9.9, ns, 7), ("BBB", 200, 20.0, 19.5, 20.2, 19.1, ns, 9)]


def _parquet(path: Path, d: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    r = _rows(d)
    pq.write_table(pa.table({c: [x[i] for x in r] for i, c in enumerate(COLS)}), path)


def _csv_gz(path: Path, d: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(COLS)] + [",".join(map(str, x)) for x in _rows(d)]
    with gzip.open(path, "wt") as f:
        f.write("\n".join(lines) + "\n")


@pytest.fixture
def env(tmp_path, monkeypatch):
    src, lib_m, lib_d, store = (tmp_path / n for n in ("vendor", "lib_massive", "lib_databento", "upq"))
    for p in (src, lib_m, lib_d, store):
        p.mkdir()
    monkeypatch.setenv("QFZ_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("QFZ_CONFIG_FILE", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("RAW_MASSIVE_DIR", str(lib_m))
    monkeypatch.setenv("RAW_DATABENTO_DIR", str(lib_d))
    monkeypatch.setenv("STORAGE_ROOT", str(store))
    monkeypatch.setenv("QFZ_BROWSE_ROOTS", f"{src}:{lib_m}:{lib_d}")
    for k in ("POLYGON_S3_ACCESS_KEY_ID", "POLYGON_S3_SECRET_ACCESS_KEY", "DATABENTO_API_KEY",
              "MASSIVE_S3_ENDPOINT"):          # other tests export credentials into os.environ
        monkeypatch.delenv(k, raising=False)
    day = src / "us_stocks_sip" / "day_aggs_v1" / "2025" / "03"
    _parquet(day / "2025-03-03.parquet", "2025-03-03")
    _csv_gz(day / "2025-03-04.csv.gz", "2025-03-04")
    (src / "us_stocks_sip" / "day_aggs_v1" / "notes.txt").write_text("x")
    return {"src": src, "lib_m": lib_m, "lib_d": lib_d, "store": store}


def test_browse_is_confined_to_the_roots(env):
    top = datasetup.browse()
    assert str(env["src"].resolve()) in top["roots"]
    listing = datasetup.browse(str(env["src"] / "us_stocks_sip"))
    assert [e["name"] for e in listing["entries"]] == ["day_aggs_v1"]
    assert listing["entries"][0]["hint"] == "massive"
    files = datasetup.browse(str(env["src"] / "us_stocks_sip/day_aggs_v1/2025/03"))["entries"]
    assert {e["hint"] for e in files} == {"dated-parquet", "massive-csv"}
    with pytest.raises(PermissionError):
        datasetup.browse("/etc")
    with pytest.raises(PermissionError):
        datasetup.browse(str(env["src"] / ".." / ".."))
    (env["src"] / "escape").symlink_to("/etc")
    with pytest.raises(PermissionError):
        datasetup.browse(str(env["src"] / "escape"))


def test_inspect_massive(env):
    r = datasetup.inspect("massive", [str(env["src"])])
    assert r["ignored"] == 1
    (g,) = r["groups"]
    assert g == {**g, "index": "us_stocks_sip/day_aggs_v1", "asset": "stock", "resolution": "daily",
                 "files": 2, "csv": 1, "start": "2025-03-03", "end": "2025-03-04"}
    with pytest.raises(ValueError):
        datasetup.inspect("bloomberg", [str(env["src"])])


def test_import_massive_links_transfers_and_converts(env):
    lines: list[str] = []
    r = datasetup.import_local("massive", [str(env["src"] / "us_stocks_sip")], on_line=lines.append)
    assert r["ok"], "\n".join(lines)
    lib = env["lib_m"] / "us_stocks_sip/day_aggs_v1/2025/03"
    assert (lib / "2025-03-03.parquet").is_symlink()
    assert not (lib / "2025-03-04.parquet").is_symlink()          # csv.gz became parquet
    rows = duckdb.sql(f"SELECT trade_date, count(*) FROM read_parquet('{env['store']}/stock_daily/*/*.parquet', "
                      "hive_partitioning=false) GROUP BY 1 ORDER BY 1").fetchall()
    assert [(str(d), n) for d, n in rows] == [("2025-03-03", 2), ("2025-03-04", 2)]
    # a second import links nothing new
    again: list[str] = []
    datasetup.import_local("massive", [str(env["src"] / "us_stocks_sip")], on_line=again.append, convert=False)
    assert any("linked=0" in ln for ln in again)


def test_import_databento_links_selections(env, tmp_path):
    a = env["src"] / "XNAS.ITCH"
    a.mkdir()
    r = datasetup.import_local("databento", [str(a)], convert=False)
    (link,) = (env["lib_d"] / "imports").iterdir()
    assert link.is_symlink() and link.resolve() == a.resolve() and r["plans"] == [{"vendor": "databento"}]
    inside = env["lib_d"] / "XNAS.ITCH"
    inside.mkdir()
    datasetup.import_local("databento", [str(inside)], convert=False)
    assert len(list((env["lib_d"] / "imports").iterdir())) == 1    # already in the library
    f = env["src"] / "2026-08-03.dbn.zst"
    f.write_bytes(b"")
    datasetup.import_local("databento", [str(f)], convert=False)
    names = [p.name for p in (env["lib_d"] / "imports").iterdir()]
    assert any(n.endswith("-2026-08-03.dbn.zst") for n in names)     # suffix kept for the converter


class FakeS3:
    def __init__(self, keys):
        self.keys = keys

    def get_paginator(self, _name):
        keys = self.keys

        class P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k, "Size": 1000} for k in keys if k.startswith(Prefix)]}
        return P()

    def head_object(self, Bucket, Key):      # the subscription covers this product
        return {}

    def download_file(self, bucket, key, dest):
        _csv_gz(Path(dest), key.rsplit("/", 1)[1][:10])


def test_massive_download_plans_then_fetches(env):
    keys = [f"us_stocks_sip/minute_aggs_v1/2025/03/2025-03-0{d}.csv.gz" for d in (3, 4, 5)]
    s3 = FakeS3(keys + ["us_stocks_sip/minute_aggs_v1/2024/12/2024-12-31.csv.gz"])
    params = {"index": "us_stocks_sip/minute_aggs_v1", "start": "2025-03-04", "end": "2025-03-31"}
    q = massive_dl.download(params, access_key="", secret_key="", endpoint="", root=env["lib_m"], s3=s3)
    assert (q["files"], q["missing"], q["bytes"], q["first"]) == (2, 2, 2000, "2025-03-04")
    r = massive_dl.download(params, access_key="", secret_key="", endpoint="", root=env["lib_m"], s3=s3, dry_run=False)
    assert r["ok"] and r["downloaded"] == 2
    out = env["lib_m"] / "us_stocks_sip/minute_aggs_v1/2025/03/2025-03-05.parquet"
    assert pq.read_table(out).num_rows == 2
    again = massive_dl.download(params, access_key="", secret_key="", endpoint="", root=env["lib_m"], s3=s3)
    assert again["missing"] == 0
    with pytest.raises(ValueError):
        massive_dl.plan(s3, "us_stocks_sip/trades_v1", date(2025, 1, 1), date(2025, 1, 2), env["lib_m"])


def test_download_requires_credentials(env):
    assert datasetup.download("databento", {})["ok"] is False
    r = datasetup.download("massive", {"index": "us_stocks_sip/day_aggs_v1", "start": "2025-01-01", "end": "2025-01-31"})
    assert r["ok"] is False and "key" in r["error"]


def _quote_rows(d: str, contract: str):
    base = int(datetime.fromisoformat(f"{d}T14:30:00").replace(tzinfo=timezone.utc).timestamp() * 1e9)
    minute = 60_000_000_000
    # three quotes in the first minute (last one wins), then one per minute for 30 minutes
    rows = [(contract, base + 1_000, 1.00, 1.10, 5, 6), (contract, base + 2_000, 1.01, 1.11, 5, 6),
            (contract, base + 59_000_000_000, 1.02, 1.12, 7, 8)]
    rows += [(contract, base + k * minute + 1, 1.0 + k / 100, 1.1 + k / 100, 1, 1) for k in range(1, 31)]
    return rows


def test_import_massive_quotes_flat_rest_and_snapshot_at_15_minutes(env):
    import json as _json
    q = env["src"] / "us_options_opra"
    c1, c2 = "O:SPY260618C00747000", "O:AAPL260618C00300000"
    cols = ["ticker", "sip_timestamp", "bid_price", "ask_price", "bid_size", "ask_size"]
    flat = q / "quotes_v1" / "2026" / "06" / "2026-06-18.parquet"
    flat.parent.mkdir(parents=True)
    r = _quote_rows("2026-06-18", c1)
    pq.write_table(pa.table({c: [x[i] for x in r] for i, c in enumerate(cols)}), flat)
    rest = q / "quotes_sample" / "O_AAPL260618C00300000__2026-06-17.jsonl.gz"
    rest.parent.mkdir(parents=True)
    with gzip.open(rest, "wt") as f:
        for _, ts, b, a, bs, as_ in _quote_rows("2026-06-17", c2):
            f.write(_json.dumps({"sip_timestamp": ts, "bid_price": b, "ask_price": a, "bid_size": bs, "ask_size": as_,
                                 "bid_exchange": 1, "ask_exchange": 1, "sequence_number": 1}) + "\n")
    snap = q / "quotes_30min_snapshot" / "sample_2026-06-16.parquet"
    snap.parent.mkdir(parents=True)
    mark = int(datetime.fromisoformat("2026-06-16T15:00:00").replace(tzinfo=timezone.utc).timestamp() * 1e9)
    pq.write_table(pa.table({"ticker": [c1, c1], "mark_ns": [mark, mark + 1_800_000_000_000],
                             "bid_price": [2.0, 2.5], "ask_price": [2.1, 2.6], "bid_size": [1, 2], "ask_size": [3, 4]}), snap)

    info = datasetup.inspect("massive", [str(q)])
    (g,) = info["groups"]
    assert g["index"] == "us_options_opra/quotes_v1" and g["kinds"] == {"flat": 1, "rest": 1, "snapshot": 1}
    lines: list[str] = []
    res = datasetup.import_local("massive", [str(q)], on_line=lines.append, quote_intervals={"option": 15})
    assert res["ok"], "\n".join(lines)
    store = env["store"] / "option_quote_minute"
    rows = duckdb.sql(f"SELECT contract, trade_date, window_start, bid_price FROM read_parquet('{store}/*/*.parquet', "
                      "hive_partitioning=false) ORDER BY 2, 1, 3").fetchall()
    by_day: dict = {}
    for contract, d, ws, bid in rows:
        by_day.setdefault((str(d), contract), []).append((ws, bid))
    # 31 minutes of quotes at 15-minute sampling -> buckets 14:30, 14:45, 15:00
    assert len(by_day[("2026-06-18", c1)]) == 3
    assert by_day[("2026-06-18", c1)][0][1] == pytest.approx(1.14)      # last minute of the first bucket
    assert len(by_day[("2026-06-17", c2)]) == 3
    # snapshots: the 15:00 mark is the book of the 14:59 minute
    snaps = by_day[("2026-06-16", c1)]
    assert [b for _, b in snaps] == [2.0, 2.5]
    assert datetime.fromtimestamp(snaps[0][0] / 1e9, tz=timezone.utc).strftime("%H:%M") == "14:59"
    assert datasetup.status()["quote_intervals"]["option"] == 15            # persisted for later updates


def test_quote_interval_is_validated(env):
    with pytest.raises(ValueError):
        datasetup.set_quote_intervals({"option": 7})
