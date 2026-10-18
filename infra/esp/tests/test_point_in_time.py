"""Point-in-time behaviour of ESP over the synthetic sample."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from qfinzero.sample.universe import EARNINGS, MACRO

ET = ZoneInfo("America/New_York")
ACME = next(e for e in EARNINGS if e.ticker == "ACME")      # AMC, 16:05 ET
BOLT = next(e for e in EARNINGS if e.ticker == "BOLT")      # BMO, 07:00 ET
CPI = next(m for m in MACRO if m.event == "CPI YoY")


def et(d, hh, mm=0):
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET).astimezone(timezone.utc).isoformat()


def earnings_on(client, e, now):
    r = client.post("/esp/calendar/earnings", json={
        "start_date": e.day.isoformat(), "end_date": e.day.isoformat(),
        "tickers": [e.ticker], "now_utc": now})
    assert r.status_code == 200, r.text
    (ev,) = r.json()["events"]
    return ev


def test_earnings_hidden_until_release(client):
    before = earnings_on(client, ACME, et(ACME.day, 15, 59))
    assert before["status"] == "scheduled"
    assert before["payload"]["actual_eps"] is None
    assert before["payload"]["estimated_eps"] == ACME.eps_estimate
    after = earnings_on(client, ACME, et(ACME.day, 16, 5))
    assert after["status"] == "occurred"
    assert after["payload"]["actual_eps"] == ACME.eps_actual


def test_bmo_earnings_release_time(client):
    assert earnings_on(client, BOLT, et(BOLT.day, 6, 59))["payload"]["actual_eps"] is None
    assert earnings_on(client, BOLT, et(BOLT.day, 7, 0))["payload"]["actual_eps"] == BOLT.eps_actual


def test_event_by_id_respects_now(client):
    ev = earnings_on(client, ACME, et(ACME.day, 17))
    eid = ev["event_id"]
    early = client.get(f"/esp/events/{eid}", params={"now_utc": et(ACME.day, 12)}).json()
    assert early["status"] == "scheduled" and early["payload"]["actual_eps"] is None
    late = client.get(f"/esp/events/{eid}", params={"now_utc": et(ACME.day, 17)}).json()
    assert late["payload"]["actual_eps"] == ACME.eps_actual


def test_window_query_blanks_future_results(client):
    r = client.post("/esp/events/query", json={
        "mode": "window", "start_utc": et(ACME.day, 0), "end_utc": et(ACME.day, 23, 59),
        "event_types": ["earnings"], "tickers": ["ACME"], "now_utc": et(ACME.day, 9, 30), "view": "full"})
    (ev,) = r.json()["events"]
    assert ev["status"] == "scheduled" and ev["payload"]["actual_eps"] is None


def test_macro_actual_hidden_until_release(client):
    def cpi(now):
        r = client.post("/esp/calendar/econ", json={
            "start_date": CPI.day.isoformat(), "end_date": CPI.day.isoformat(), "now_utc": now})
        return next(e for e in r.json()["events"] if e["title"] == "CPI YoY")

    assert cpi(et(CPI.day, 8, 29))["payload"]["actual"] is None
    assert cpi(et(CPI.day, 8, 29))["payload"]["consensus"] == "2.9%"
    assert cpi(et(CPI.day, 8, 30))["payload"]["actual"] == "2.9%"


def search(client, now, **kw):
    body = {"tickers": ["ACME"], "start_utc": et(ACME.day, 0),
            "end_utc": et(ACME.day, 23, 59), "now_utc": now, **kw}
    r = client.post("/esp/news/search", json=body)
    assert r.status_code == 200, r.text
    return r.json()["events"]


def test_news_not_visible_before_publication(client):
    titles = [e["title"] for e in search(client, et(ACME.day, 16, 5))]
    assert not any("Q4 EPS" in t for t in titles)
    titles = [e["title"] for e in search(client, et(ACME.day, 16, 6))]
    assert any("Q4 EPS $1.61 beats" in t for t in titles)


def test_news_body_respects_now(client):
    (ev,) = [e for e in search(client, et(ACME.day, 23)) if "Q4 EPS" in e["title"]]
    nid = ev["event_id"].removeprefix("news_")
    assert client.get(f"/esp/news/{nid}/body", params={"now_utc": et(ACME.day, 16)}).status_code == 404
    body = client.get(f"/esp/news/{nid}/body", params={"now_utc": et(ACME.day, 17)}).json()
    assert body["title"] == ev["title"] and body["tickers"] == ["ACME"]


def test_news_keyword_and_pagination(client):
    first = search(client, et(ACME.day, 23), limit=1)
    assert len(first) == 1
    hits = search(client, et(ACME.day, 23), keyword="EPS")
    assert hits and all("EPS" in e["title"] for e in hits)


def test_health_and_stats_on_sqlite_news(client, esp_dir):
    fresh = client.get("/esp/health/freshness").json()["sources"]
    assert fresh["news"]["record_count"] > 100
    assert fresh["news"]["unique_keys"] == 20
    assert fresh["earnings"]["record_count"] == len(EARNINGS)
    assert fresh["econ_events"]["record_count"] == len(MACRO)
    # stats is relative to the wall clock, so it covers no sample news
    st = client.get("/esp/news/stats", params={"days": 90}).json()
    assert set(st) >= {"total_count", "daily_counts", "top_tickers", "duplicate_stats"}


def test_news_export(client):
    r = client.get("/esp/news/export", params={
        "format": "jsonl", "tickers": "ACME", "start": "2025-01-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"})
    assert r.status_code == 200
    rows = [json.loads(line) for line in r.text.splitlines() if line]
    assert rows and all("ACME" in row["tickers"] for row in rows)
    assert rows == sorted(rows, key=lambda x: x["published_utc"])


def test_missing_databases_are_unavailable(tmp_path):
    from fastapi.testclient import TestClient

    from tests.conftest import make_app
    with TestClient(make_app(tmp_path, news_backend="sqlite")) as c:
        assert c.get("/esp/health").status_code == 200
        r = c.post("/esp/calendar/earnings", json={"start_date": "2025-01-01", "end_date": "2025-12-31"})
        assert r.status_code == 200 and r.json()["events"] == []
        assert c.get("/esp/news/stats").status_code == 503


def test_auto_backend_falls_back_to_mongo(tmp_path):
    from services.data_sources import DataSourceManager, MongoNewsSource, SQLiteNewsSource
    kw = dict(mongo_uri="mongodb://127.0.0.1:1", mongo_db="x", mongo_collection="x",
              earnings_db="e", econ_events_db="c")
    assert isinstance(DataSourceManager(**kw, news_db=str(tmp_path / "none")).news, MongoNewsSource)
    (tmp_path / "news.sqlite3").write_bytes(b"")
    assert isinstance(DataSourceManager(**kw, news_db=str(tmp_path / "news.sqlite3")).news, SQLiteNewsSource)
    with pytest.raises(ValueError):
        DataSourceManager(**kw, news_backend="sqlite")


@pytest.mark.parametrize("actual", ["&nbsp;", " ", "", None])
def test_blank_econ_actual_is_scheduled(actual):
    from services.data_sources import SQLiteEconEventsSource
    ev = SQLiteEconEventsSource("x")._to_event(
        {"event_id": "a", "date": "2025-01-15", "gmt_time": "13:30", "event_name": "CPI YoY",
         "actual": actual, "consensus": "2.9%"},
        datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert ev.status.value == "scheduled" and ev.payload["actual"] is None


def test_undated_earnings_known_after_day_end():
    from services.data_sources import SQLiteEarningsSource
    row = {"benzinga_id": "b", "ticker": "X", "date": "2025-01-15", "time": None,
           "date_status": "confirmed", "actual_eps": 1.0}
    src = SQLiteEarningsSource("x")
    noon = datetime(2025, 1, 15, 17, tzinfo=timezone.utc)
    assert src._to_event(row, noon).payload["actual_eps"] is None
    assert src._to_event(row, noon + timedelta(days=1)).payload["actual_eps"] == 1.0
