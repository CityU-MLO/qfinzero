"""Data utility: layouts and init, vendor keys, downloads with progress, budgets, jobs."""

import importlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("QFZ_DATA_ROOT", str(tmp_path / "qfz"))
    monkeypatch.setenv("QFZ_CONFIG_FILE", str(tmp_path / "qfz" / "_state" / "qfz.config.json"))
    for k in ("POLYGON_S3_ACCESS_KEY_ID", "POLYGON_S3_SECRET_ACCESS_KEY", "MASSIVE_REST_API_KEY",
              "POLYGON_API_KEY", "DATABENTO_API_KEY", "RAW_MASSIVE_DIR", "RAW_DATABENTO_DIR",
              "RAW_TUSHARE_DIR", "STORAGE_ROOT"):
        monkeypatch.delenv(k, raising=False)
    from qfinzero.admin import config_store
    importlib.reload(config_store)
    config_store.update({"dirs": {"raw_massive": str(tmp_path / "raw" / "massive"),
                                  "raw_databento": str(tmp_path / "raw" / "databento"),
                                  "raw_tushare": str(tmp_path / "raw" / "tushare"),
                                  "storage_root": str(tmp_path / "qfz" / "upq")}})
    return tmp_path


def test_layout_init_creates_both_layouts_and_markers(env):
    from qfinzero.admin import layout
    before = layout.describe()
    assert not before["qfz"]["exists"] and not before["raw"]["massive"]["exists"]
    r = layout.init()
    assert r["ok"] and r["created"]
    d = r["layout"]
    assert d["raw"]["databento"]["marker"]["kind"] == "raw" and d["raw"]["databento"]["marker"]["vendor"] == "databento"
    assert (Path(d["raw"]["databento"]["path"]) / "imports").is_dir()
    assert d["qfz"]["marker"]["kind"] == "qfz" and all(d["qfz"]["stores"].values())
    assert layout.init()["created"] == []                      # idempotent
    # a RAW library cannot become the store, nor two roles share a directory
    with pytest.raises(ValueError):
        layout.init({"storage_root": d["raw"]["massive"]["path"]})
    with pytest.raises(ValueError):
        layout.init({"raw_tushare": d["raw"]["massive"]["path"]})
    with pytest.raises(ValueError):
        layout.init({"bogus": "/tmp"})
    # someone else's data is not marked unless chosen explicitly
    shared = env / "shared_tushare"
    shared.mkdir()
    (shared / "dump.csv").write_text("x")
    from qfinzero.admin import config_store as cs
    cs.update({"dirs": {"raw_tushare": str(shared)}})
    r = layout.init()
    assert [x["config_key"] for x in r["skipped"]] == ["raw_tushare"] and not (shared / ".qfz-layout.json").exists()
    assert (shared / ".qfz-layout.json").exists() is False
    layout.init({"raw_tushare": str(shared)})
    assert (shared / ".qfz-layout.json").exists()
    # paths are saved
    new = str(env / "elsewhere" / "upq")
    layout.init({"storage_root": new})
    assert layout.describe()["qfz"]["path"] == new and (Path(new) / "stock_minute").is_dir()


def test_vendor_keys_route_by_product_and_stay_masked(env):
    from qfinzero.admin import config_store as cs
    cs.update({"databento": {"api_key": "db-legacy-1111"}})
    assert [k["id"] for k in cs.vendor_keys("databento")] == ["default"]
    k = cs.save_key("databento", {"label": "futures", "products": "GLBX.MDP3", "api_key": "db-fut-2222",
                                  "monthly_budget_usd": 5})
    assert k["api_key"] == "••••2222" and k["products"] == ["GLBX.MDP3"]
    # the default key covers everything, so it wins until it is scoped
    assert cs.databento_key("GLBX.MDP3") == "db-legacy-1111"
    cs.save_key("databento", {"id": "default", "products": ["OPRA.*"], "api_key": "••••1111"})
    assert cs.databento_key("GLBX.MDP3") == "db-fut-2222"
    assert cs.databento_key("OPRA.PILLAR") == "db-legacy-1111"
    assert cs.databento_key("XNAS.ITCH") == ""
    assert "db-fut-2222" not in json.dumps(cs.masked())
    cs.update({"keys": {"databento": []}})                     # the generic update cannot touch keys
    assert len(cs.vendor_keys("databento")) == 2
    m = cs.save_key("massive", {"label": "options", "products": ["us_options_opra/*"],
                                "s3_access_key_id": "AK", "s3_secret_access_key": "SK"})
    assert cs.massive_s3("us_options_opra/quotes_v1")["key_id"] == m["id"]
    assert cs.massive_s3("us_stocks_sip/day_aggs_v1")["access_key_id"] == ""
    assert cs.delete_key("databento", "default") and cs.databento_key("OPRA.PILLAR") == ""
    with pytest.raises(ValueError):
        cs.save_key("databento", {"label": "empty"})


class FakeDatabento:
    def __init__(self, cost=1.5, fail=()):
        self.cost, self.fail, self.calls = cost, set(fail), []
        self.metadata = NS(get_cost=lambda **k: self.cost * len(k["symbols"]) / 2,
                           get_billable_size=lambda **k: 1000 * len(k["symbols"]),
                           list_datasets=lambda: ["GLBX.MDP3", "OPRA.PILLAR"])
        self.timeseries = NS(get_range=self._get)

    def _get(self, path, symbols, start, **_k):
        self.calls.append((symbols[0], start))
        if symbols[0] in self.fail:
            raise RuntimeError("no entitlement")
        Path(path).write_bytes(b"x" * 2048)


def test_databento_download_progress_budget_and_spend(env):
    from qfinzero.admin import config_store as cs, databento_dl, vendor_keys
    k = cs.save_key("databento", {"label": "fut", "products": ["GLBX.MDP3"], "api_key": "db-1", "monthly_budget_usd": 1.0})
    params = {"dataset": "GLBX.MDP3", "schema": "mbo", "symbols": "ZN.v.0,CL.v.0", "stype_in": "continuous",
              "start": "2026-09-01", "end": "2026-09-01", "max_cost": 10}
    lib = Path(cs.dirs()["raw_databento"])
    client = FakeDatabento(cost=1.5)
    events: list[dict] = []
    r = databento_dl.download(params, api_key="db-1", root=lib, dry_run=False, client_factory=lambda _k: client,
                              on_progress=lambda **f: events.append(f), key_id=k["id"])
    assert r["ok"] is False and "may still spend" in r["error"]          # $1.50 quote over a $1 budget
    cs.save_key("databento", {"id": k["id"], "monthly_budget_usd": 3})
    r = databento_dl.download(params, api_key="db-1", root=lib, dry_run=False, client_factory=lambda _k: client,
                              on_progress=lambda **f: events.append(f), key_id=k["id"], job_id="download-1")
    assert r["ok"] and r["written"] == 2 and r["spent_usd"] == 1.5
    assert any(e.get("files_total") == 2 for e in events) and events[-1]["stage"] == "done"
    assert any(e.get("files_done") == 2 and e.get("bytes_done") == 4096 for e in events)
    s = vendor_keys.spend()
    assert s["by_key"][k["id"]] == 1.5 and s["recent"][0]["job"] == "download-1"
    assert vendor_keys.budget_left(k["id"]) == 1.5
    # files already present are neither quoted nor fetched again
    again = databento_dl.download(params, api_key="db-1", root=lib, dry_run=True, client_factory=lambda _k: client)
    assert again["to_fetch"] == 0 and again["cost_usd"] == 0
    # stopping between files
    p2 = {**params, "start": "2026-09-02", "end": "2026-09-03"}
    stop = {"n": 0}

    def should_stop():
        stop["n"] += 1
        return stop["n"] > 1
    r = databento_dl.download(p2, api_key="db-1", root=lib, dry_run=False, client_factory=lambda _k: FakeDatabento(0),
                              should_stop=should_stop, key_id=k["id"])
    assert r["ok"] is False and r["written"] == 1 and "stopped" in r["error"]


def test_key_test_and_massive_progress(env):
    from qfinzero.admin import config_store as cs, massive_dl, vendor_keys
    db = cs.save_key("databento", {"label": "all", "api_key": "db-x"})
    assert vendor_keys.test_key("databento", db["id"], databento_client=FakeDatabento())["datasets"] == 2

    class Denied(Exception):
        response = {"Error": {"Code": "403"}}

    class S3:
        """Like massive: every product lists, only stocks download."""
        def list_objects_v2(self, Bucket, Prefix, MaxKeys=1000):
            return {"Contents": [{"Key": f"{Prefix}2026-01-0{d}.csv.gz"} for d in (2, 5)]}

        def head_object(self, Bucket, Key):
            if not Key.startswith("us_stocks_sip/"):
                raise Denied()
            return {}
    mk = cs.save_key("massive", {"label": "stocks", "s3_access_key_id": "a", "s3_secret_access_key": "b"})
    t = vendor_keys.test_key("massive", mk["id"], s3=S3())
    assert t["ok"] and t["access"]["us_stocks_sip/day_aggs_v1"] and not t["access"]["us_options_opra/day_aggs_v1"]
    assert "403" in t["errors"]["us_options_opra/day_aggs_v1"]

    import gzip

    class FakeS3:
        keys = [f"us_stocks_sip/day_aggs_v1/2025/03/2025-03-0{d}.csv.gz" for d in (3, 4)]

        def get_paginator(self, _n):
            keys = self.keys

            class P:
                def paginate(self, Bucket, Prefix):
                    yield {"Contents": [{"Key": k, "Size": 100} for k in keys if k.startswith(Prefix)]}
            return P()

        def head_object(self, Bucket, Key):
            if not Key.startswith("us_stocks_sip/"):
                raise Denied()
            return {}

        def download_file(self, bucket, key, dest, Callback=None):
            with gzip.open(dest, "wt") as f:
                f.write("ticker,volume,open,close,high,low,window_start,transactions\nA,1,1,1,1,1,1,1\n")
            if Callback:
                Callback(60)
                Callback(40)
    events: list[dict] = []
    params = {"index": "us_stocks_sip/day_aggs_v1", "start": "2025-03-01", "end": "2025-03-31"}
    r = massive_dl.download(params, access_key="", secret_key="", endpoint="", root=Path(cs.dirs()["raw_massive"]),
                            s3=FakeS3(), dry_run=False, on_progress=lambda **f: events.append(f))
    assert r["ok"] and r["downloaded"] == 2
    assert events[0]["bytes_total"] == 200 and any(e.get("bytes_done") == 200 for e in events)
    assert any(e.get("stage") == "converting" for e in events)
    # a product the key can list but not download is refused at planning time
    FakeS3.keys = [f"us_options_opra/day_aggs_v1/2025/03/2025-03-0{d}.csv.gz" for d in (3, 4)]
    r = massive_dl.download({**params, "index": "us_options_opra/day_aggs_v1"}, access_key="", secret_key="",
                            endpoint="", root=Path(cs.dirs()["raw_massive"]), s3=FakeS3(), dry_run=True)
    assert r["ok"] is False and "not in the subscription" in r["error"]


def test_jobs_progress_cancel_and_persistence(env, tmp_path):
    sys.path.insert(0, str(ROOT / "infra" / "data-admin"))
    import jobs as J
    reg = J.JobRegistry(tmp_path / "jobs")

    def slow(job):
        job.update(files_total=10)
        for i in range(10):
            if job.cancelled():
                return {"ok": False, "error": "stopped"}
            job.update(files_done=i + 1, bytes_done=(i + 1) * 100)
            time.sleep(0.05)
        return {"ok": True}
    job = reg.submit("download", "slow", slow, meta={"vendor": "databento"})
    time.sleep(0.12)
    assert job.cancel()
    for _ in range(100):
        if job.status in J.TERMINAL:
            break
        time.sleep(0.02)
    snap = job.snapshot()
    assert snap["status"] == "cancelled" and 0 < snap["progress"]["files_done"] < 10
    assert snap["progress"]["files_total"] == 10 and "eta_s" in snap["progress"] and snap["meta"]["vendor"] == "databento"
    # a running job left behind by a restart comes back as interrupted
    (tmp_path / "jobs" / "download-9.json").write_text(json.dumps(
        {"id": "download-9", "kind": "download", "label": "x", "status": "running", "created_at": "2099-01-01T00:00:00"}))
    reg2 = J.JobRegistry(tmp_path / "jobs")
    assert reg2.get("download-1").status == "cancelled"
    assert reg2.get("download-9").status == "interrupted"
    assert reg2.submit("download", "next", lambda j: {"ok": True}).id == "download-10"


def test_compact_rewrites_old_partitions_once(env):
    import duckdb
    from qfinzero.pipeline.compact import compact
    from qfinzero.pipeline.engine import copy_to_parquet, parquet_options
    store = Path(env) / "qfz" / "upq"
    con = duckdb.connect()
    for d in ("2020-01-02", "2099-01-02"):
        copy_to_parquet(con, "SELECT 'X' AS ticker, range AS window_start, random() AS close FROM range(50000)",
                        store / "stock_minute" / f"trade_date={d}" / "part-0000.parquet")
    assert "COMPRESSION_LEVEL 3" in parquet_options() and "COMPRESSION_LEVEL 9" in parquet_options("archive")
    plan = compact(store, older_than_days=30, dry_run=True)
    assert plan["files"] == 1                                    # the 2099 partition is too new
    r = compact(store, older_than_days=30)
    assert r["ok"] and r["files"] == 1 and r["after"] <= r["before"]
    assert compact(store, older_than_days=30, dry_run=True)["files"] == 0      # remembered
    n = con.execute(f"SELECT count(*) FROM read_parquet('{store}/stock_minute/trade_date=2020-01-02/*.parquet')").fetchone()[0]
    assert n == 50000
