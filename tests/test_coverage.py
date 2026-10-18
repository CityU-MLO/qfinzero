"""Coverage map over the synthetic sample (no services needed)."""

import os
import time

import pytest

from qfinzero.admin import coverage as C
from qfinzero.sample.universe import DAYS, MINUTE_WINDOW


@pytest.fixture(scope="module")
def root(sample_root):
    return sample_root / "upq"


def test_extent_and_default_range(root):
    ext = C.extent(root)
    assert ext["daily"] == {"start": str(DAYS[0]), "end": str(DAYS[-1]), "days": len(DAYS)}
    # the overnight session before the first minute day sits in the prior ET date
    assert ext["minute"]["start"] == str(DAYS[DAYS.index(MINUTE_WINDOW[0]) - 1])
    assert C.default_range(root, 30)[1] == str(DAYS[-1])


def test_matrix_levels_per_ticker_and_day(root):
    m = C.matrix(["acme", "NOVA", "ZZZZ"], str(DAYS[0]), str(DAYS[-1]), root)
    assert m["tickers"] == ["ACME", "NOVA", "ZZZZ"]
    assert m["cells"]["ZZZZ"] == {}
    early, late = str(DAYS[1]), str(MINUTE_WINDOW[3])
    assert set(m["cells"]["ACME"][early]) == {"daily", "options_eod", "contracts"}
    assert {"daily", "minute", "quotes", "options_eod", "options_minute", "options_quotes"} <= set(m["cells"]["ACME"][late])
    assert "options_eod" not in m["cells"]["NOVA"][late]            # NOVA lists no options
    sessions = m["cells"]["ACME"][late]["sessions"]
    assert sessions["regular"] == 390 and sessions["pre"] == 330 and sessions["post"] == 240
    assert m["days"][0] == str(DAYS[0]) and m["days"][-1] == str(DAYS[-1])


def test_overnight_session_counted(root):
    i = next(k for k in range(1, len(MINUTE_WINDOW)) if (MINUTE_WINDOW[k] - MINUTE_WINDOW[k - 1]).days == 1)
    m = C.matrix(["NOVA", "FERN"], str(MINUTE_WINDOW[i]), str(MINUTE_WINDOW[i]), root)
    d = str(MINUTE_WINDOW[i])
    assert m["cells"]["NOVA"][d]["sessions"].get("overnight", 0) > 0
    assert "overnight" not in m["cells"]["FERN"][d]["sessions"]


def test_summaries_are_cached_and_refreshed(root):
    import json
    d = str(MINUTE_WINDOW[0])
    first = C.day_summary("stock_minute", d, root)
    cache = C._cache_file("stock_minute", d, root)
    fp = json.loads(cache.read_text())["fingerprint"]
    stamp = cache.stat().st_mtime_ns
    assert C.day_summary("stock_minute", d, root) == first and cache.stat().st_mtime_ns == stamp
    part = next((root / "stock_minute" / f"trade_date={d}").glob("*.parquet"))
    future = time.time() + 5
    os.utime(part, (future, future))                                 # partition rewritten
    assert C.day_summary("stock_minute", d, root) == first
    assert json.loads(cache.read_text())["fingerprint"] != fp


def test_cell_detail(root):
    d = str(MINUTE_WINDOW[3])
    c = C.cell("ACME", d, root)
    assert c["levels"]["daily"]["rows"] == 1 and c["daily_bar"]["close"] > 0
    assert c["levels"]["options_eod"]["contracts"] > 50
    assert c["option_expiries"] and c["minute_span"]["first_ns"] < c["minute_span"]["last_ns"]
    assert C.cell("NOVA", "2025-03-03", root)["corporate_actions"] == [{"type": "split", "ratio": 2.0}]
    assert C.cell("ZZZZ", d, root)["levels"]["daily"] is None


def test_suggest_and_limits(root):
    top = C.suggest(limit=3, root=root)
    assert len(top) == 3 and top[0]["dollar_volume"] >= top[1]["dollar_volume"]
    assert top[0]["ticker"] == "QZSP"            # the $520 ETF trades the most dollars
    assert [t["ticker"] for t in C.suggest("QZ", root=root)] == ["QZSP"]
    with pytest.raises(ValueError):
        C.matrix(["ACME"], "2025-03-01", "2025-01-01", root)
    with pytest.raises(ValueError):
        C.matrix(["ACME"], "2020-01-01", "2025-01-01", root)


def test_service_error_messages_are_unwrapped():
    assert C._msg(RuntimeError("{'detail': 'News store unavailable'}")) == "News store unavailable"
    assert C._msg(RuntimeError("plain")) == "plain"
