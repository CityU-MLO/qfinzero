"""Updating a source fetches the vendor's new days first (massive), never Databento."""

from __future__ import annotations

import os
import sys
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero.admin import refresh  # noqa: E402


class FakeDownload:
    """Stands in for datasetup.download: massive has days up to ``last``."""

    def __init__(self, last="2026-10-16", error=None, have=("2026-09-01", "2026-09-02", "2026-10-15")):
        self.last, self.error, self.calls, self.have = last, error, [], set(have)

    def __call__(self, vendor, params, dry_run=True, **_kw):
        self.calls.append((vendor, dict(params), dry_run))
        if self.error:
            return {"ok": False, "error": self.error}
        remote = [d for d in ("2026-09-01", "2026-09-02", "2026-10-15", "2026-10-16")
                  if params["start"] <= d <= min(params["end"], self.last)]
        days = [d for d in remote if d not in self.have]
        return {"ok": True, "missing": len(days), "bytes": 40_000_000 * len(days),
                "first": remote[0] if remote else None, "last": remote[-1] if remote else None,
                "missing_dates": days, "key": {"id": "k1", "label": "LUO"}}


ROWS = {
    "us_stock_daily": {"raw_max": "2026-10-15", "store_max": "2026-10-15", "behind_days": 0},
    "us_option_day": {"raw_max": "2026-08-21", "store_max": "2026-08-20", "behind_days": 1},
    "us_databento": {"raw_max": "2026-09-30", "store_max": "2026-09-30", "behind_days": 0},
    "us_stock_minute": {"raw_max": None, "store_max": None, "behind_days": None},
}
TODAY = date(2026, 10, 19)


def test_plan_fetches_new_massive_days_after_the_newest_local_day():
    dl = FakeDownload()
    items = {i["id"]: i for i in refresh.plan(list(ROWS), ROWS, today=TODAY, download=dl)}
    d = items["us_stock_daily"]
    assert d["action"] == "fetch" and d["fetch"]["files"] == 1 and d["fetch"]["first"] == "2026-10-16"
    assert d["fetch"]["index"] == "us_stocks_sip/day_aggs_v1" and d["fetch"]["key"]["label"] == "LUO"
    assert ("massive", {"index": "us_stocks_sip/day_aggs_v1", "start": "2026-06-17", "end": "2026-10-19"}, True) in dl.calls
    assert items["us_option_day"]["action"] == "fetch"          # 08-22 onwards exists remotely
    assert items["us_databento"]["action"] == "manual"          # paid: never fetched here
    assert items["us_stock_minute"]["action"] == "manual"       # no local data: first range is a choice
    assert all(c[0] == "massive" and c[2] for c in dl.calls)    # planning never downloads


def test_gaps_inside_the_lookback_are_fetched():
    dl = FakeDownload(have=("2026-10-15", "2026-10-16"))      # September is missing locally
    it = refresh.plan(["us_stock_daily"], ROWS, today=TODAY, download=dl)[0]
    assert it["action"] == "fetch" and it["fetch"]["files"] == 2 and it["fetch"]["gaps"] == 2
    assert (it["fetch"]["first"], it["fetch"]["last"]) == ("2026-09-01", "2026-09-02")
    dl.calls.clear()
    refresh.run([it], download=dl)
    assert dl.calls[0][1]["start"] == "2026-09-01" and dl.calls[0][1]["end"] == "2026-09-02"   # converts only the gap


def test_up_to_date_and_errors_are_explained():
    items = refresh.plan(["us_stock_daily"], ROWS, today=TODAY, download=FakeDownload(last="2026-10-15"))
    assert items[0]["action"] == "none" and "up to date" in items[0]["message"]
    items = refresh.plan(["us_option_day"], ROWS, today=TODAY, download=FakeDownload(error="no massive key covers it"))
    assert items[0]["action"] == "convert" and items[0]["fetch"]["error"] == "no massive key covers it"


def test_run_downloads_only_fetch_items():
    dl = FakeDownload()
    items = refresh.plan(list(ROWS), ROWS, today=TODAY, download=dl)
    dl.calls.clear()
    res = refresh.run(items, download=dl)
    assert res["ok"] and {r["id"] for r in res["fetched"]} == {"us_stock_daily", "us_option_day"}
    assert all(not c[2] and c[0] == "massive" for c in dl.calls)
