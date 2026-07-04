"""Unit tests for qfinzero.update — the convert-only orchestration core.

All dependencies (raw/store scan, the converter) are injected as fakes, so these
run without DuckDB, polars, or any real market data.
"""

from datetime import date
from pathlib import Path

import pytest

from qfinzero.update import (
    Orchestrator,
    SOURCES,
    compute_freshness,
    select,
)
from qfinzero.update.freshness import _business_days_between, colour
from qfinzero.update.sources import BY_ID
from qfinzero.update.lock import domain_lock, LockBusy


# ── fakes ───────────────────────────────────────────────────────────────


class FakePaths:
    def __init__(self, storage):
        self.storage = Path(storage)


class FakeConvertResult:
    def __init__(self, store, partitions=1, rows=100, skipped=0, notes=None):
        self.store = store
        self.partitions = partitions
        self.rows = rows
        self.skipped = skipped
        self.notes = notes or []

    def log(self):
        return f"{self.store} partitions={self.partitions}"


class FakeConverter:
    """Records every convert_* call and the (start, force) it was given."""

    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _rec(self, store, start, force):
        self.calls.append((store, start, force))
        return FakeConvertResult(store)

    def convert_us_stock_daily(self, start=None, force=False):
        return self._rec("us_stock_daily", start, force)

    def convert_us_stock_minute(self, start=None, force=False):
        return self._rec("us_stock_minute", start, force)

    def convert_us_option_day(self, start=None, force=False):
        return self._rec("us_option_day", start, force)

    def convert_us_option_minute(self, start=None, force=False):
        return self._rec("us_option_minute", start, force)

    def convert_cn_stock_daily(self, start=None, force=False):
        return self._rec("cn_stock_daily", start, force)

    def convert_rates(self, force=False):
        return self._rec("rates", None, force)

    def convert_corporate_actions(self, include_massive=True, include_tushare=True):
        return self._rec("corp_actions", None, False)


FRESH = "2026-06-27"


def make_scan(**override) -> dict:
    """A baseline scan where everything present and fully caught up."""
    scan = {
        "raw": {
            "massive": {
                "stock_daily": {"present": True, "end": FRESH},
                "stock_minute": {"present": True, "end": FRESH},
                "option_day": {"present": True, "end": FRESH},
                "option_minute": {"present": True, "end": FRESH},
                "rates": {"present": True},
                "splits_files": 5,
                "dividends_files": 5,
            },
            "tushare": {
                "cn_daily": {"present": True, "end": FRESH},
                "cn_dividend_files": 3,
            },
        },
        "storage": {
            "stock_daily": {"partitions": 10, "end": FRESH},
            "stock_minute": {"partitions": 10, "end": FRESH},
            "option_day": {"partitions": 10, "end": FRESH},
            "option_minute": {"partitions": 10, "end": FRESH},
            "rates/rates.parquet": True,
            "corporate_actions/corporate_actions.parquet": True,
        },
    }
    # dotted-path overrides, e.g. make_scan(**{"storage.option_day.end": "2026-06-20"})
    for dotted, value in override.items():
        cur = scan
        parts = dotted.split(".")
        for p in parts[:-1]:
            cur = cur[p]
        cur[parts[-1]] = value
    return scan


def orch(tmp_path, scan):
    fake_cv = FakeConverter()
    o = Orchestrator(
        paths=FakePaths(tmp_path),
        scan_fn=lambda: scan,
        converter_factory=lambda: fake_cv,
        today=date(2026, 6, 29),
    )
    return o, fake_cv


# ── freshness ────────────────────────────────────────────────────────────


def test_business_days_between():
    assert _business_days_between(date(2024, 1, 2), date(2024, 1, 8)) == 4  # skips weekend
    assert _business_days_between(date(2024, 1, 2), date(2024, 1, 2)) == 0
    assert _business_days_between(date(2024, 1, 8), date(2024, 1, 2)) == 0  # b<=a


def test_freshness_behind():
    scan = make_scan(**{"storage.option_day.end": "2026-06-20"})
    fr = compute_freshness(BY_ID["us_option_day"], scan, today=date(2026, 6, 29))
    assert fr.state == "behind"
    assert fr.stale is True
    assert fr.behind_days == 7
    assert colour(fr) in ("amber", "red")


def test_freshness_fresh():
    fr = compute_freshness(BY_ID["us_stock_daily"], make_scan(), today=date(2026, 6, 29))
    assert fr.state == "fresh"
    assert fr.stale is False


def test_freshness_missing_store():
    scan = make_scan(**{"storage.stock_minute": {"partitions": 0}})  # no 'end'
    fr = compute_freshness(BY_ID["us_stock_minute"], scan, today=date(2026, 6, 29))
    assert fr.state == "missing"
    assert fr.stale is True


def test_freshness_no_raw():
    scan = make_scan(**{"raw.massive.option_minute": {"present": False}})  # no 'end'
    fr = compute_freshness(BY_ID["us_option_minute"], scan, today=date(2026, 6, 29))
    assert fr.state == "no_raw"
    assert fr.stale is False


def test_freshness_unavailable_news():
    fr = compute_freshness(BY_ID["news"], make_scan(), today=date(2026, 6, 29))
    assert fr.state == "unavailable"
    assert fr.stale is False


# ── selection ──────────────────────────────────────────────────────────────


def test_select_all_and_prices():
    assert len(select("all")) == len(SOURCES)
    prices = select("prices")
    assert {s.id for s in prices} == {
        "us_stock_daily", "us_stock_minute", "us_option_day",
        "us_option_minute", "cn_stock_daily", "rates", "corp_actions",
    }


def test_select_market_filter():
    cn = {s.id for s in select("prices", market="cn")}
    assert "cn_stock_daily" in cn
    assert "us_stock_daily" not in cn
    # global (market=None) sources still included
    assert "rates" in cn and "corp_actions" in cn


def test_select_unknown_raises():
    with pytest.raises(ValueError):
        select("nonsense_source")


# ── planning ───────────────────────────────────────────────────────────────


def test_plan_marks_behind_source(tmp_path):
    scan = make_scan(**{"storage.option_day.end": "2026-06-20"})
    o, _ = orch(tmp_path, scan)
    plan = {it.source.id: it for it in o.plan("prices")}
    assert plan["us_option_day"].will_run is True
    assert plan["us_option_day"].reason == "stale"
    assert plan["us_stock_daily"].will_run is False  # fresh


def test_plan_corp_actions_dependency(tmp_path):
    # a dated price source is behind → corp_actions should run as a dependency
    scan = make_scan(**{"storage.option_day.end": "2026-06-20"})
    o, _ = orch(tmp_path, scan)
    plan = {it.source.id: it for it in o.plan("prices")}
    assert plan["corp_actions"].will_run is True
    assert plan["corp_actions"].reason == "dependency"


def test_plan_all_fresh_nothing_runs(tmp_path):
    o, _ = orch(tmp_path, make_scan())
    assert all(not it.will_run for it in o.plan("prices"))


# ── execution ────────────────────────────────────────────────────────────────


def test_run_converts_only_stale(tmp_path):
    scan = make_scan(**{"storage.option_day.end": "2026-06-20"})
    o, cv = orch(tmp_path, scan)
    result = o.run("prices")
    ran = {c[0] for c in cv.calls}
    assert "us_option_day" in ran
    assert "corp_actions" in ran           # dependency
    assert "us_stock_daily" not in ran     # fresh, skipped
    # start passed to the stale converter is its prior store_max
    od_call = [c for c in cv.calls if c[0] == "us_option_day"][0]
    assert od_call[1] == "2026-06-20"
    # manifest persisted
    mf = tmp_path / "_state" / "update_manifest.json"
    assert mf.exists()
    statuses = {r["id"]: r["status"] for r in result["results"]}
    assert statuses["us_option_day"] == "ok"
    assert statuses["us_stock_daily"] == "skipped"


def test_dry_run_writes_nothing(tmp_path):
    scan = make_scan(**{"storage.option_day.end": "2026-06-20"})
    o, cv = orch(tmp_path, scan)
    result = o.run("prices", dry_run=True)
    assert result["dry_run"] is True
    assert cv.calls == []                                  # converter never called
    assert not (tmp_path / "_state" / "update_manifest.json").exists()
    assert any(it["will_run"] for it in result["plan"])


def test_force_runs_all_available(tmp_path):
    o, cv = orch(tmp_path, make_scan())  # everything fresh
    o.run("prices", force=True)
    ran = {c[0] for c in cv.calls}
    assert ran == {
        "us_stock_daily", "us_stock_minute", "us_option_day",
        "us_option_minute", "cn_stock_daily", "rates", "corp_actions",
    }


def test_run_records_error_per_source(tmp_path):
    scan = make_scan(**{"storage.option_day.end": "2026-06-20"})
    o, cv = orch(tmp_path, scan)

    def boom(start=None, force=False):
        raise RuntimeError("disk full")
    cv.convert_us_option_day = boom

    result = o.run("prices")
    statuses = {r["id"]: r for r in result["results"]}
    assert statuses["us_option_day"]["status"] == "error"
    assert "disk full" in statuses["us_option_day"]["error"]
    # other sources unaffected
    assert statuses["corp_actions"]["status"] == "ok"


def test_status_includes_last_run(tmp_path):
    scan = make_scan(**{"storage.option_day.end": "2026-06-20"})
    o, _ = orch(tmp_path, scan)
    o.run("prices")
    status = o.status("prices")
    by_id = {s["id"]: s for s in status["sources"]}
    assert by_id["us_option_day"]["last_run"]["status"] == "ok"
    assert by_id["us_option_day"]["colour"] in ("green", "amber", "red", "grey")


# ── lock ────────────────────────────────────────────────────────────────────


def test_domain_lock_is_exclusive(tmp_path):
    with domain_lock(tmp_path, "price"):
        with pytest.raises(LockBusy):
            with domain_lock(tmp_path, "price"):
                pass
    # released → reacquirable
    with domain_lock(tmp_path, "price"):
        pass
