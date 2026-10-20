"""Time lock: session clock -> as_of, and MCP data tools honouring it."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from types import SimpleNamespace as NS
from urllib.parse import parse_qs, urlparse

import pytest
import responses

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero import timelock  # noqa: E402
from tests.conftest import MOCK_ESP_URL, MOCK_PMB_URL, MOCK_UPQ_URL  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_qfz_mcp_server_tl", os.path.join(PROJECT_ROOT, "mcp", "server.py"))
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)


@pytest.fixture(autouse=True)
def _urls(monkeypatch):
    monkeypatch.setattr(srv, "UPQ_URL", MOCK_UPQ_URL)
    monkeypatch.setattr(srv, "ESP_URL", MOCK_ESP_URL)
    monkeypatch.setattr(srv, "PMB_URL", MOCK_PMB_URL)
    monkeypatch.delenv("QFZ_TIME_LOCK_SESSION", raising=False)
    monkeypatch.delenv("QFZ_REQUIRE_SESSION", raising=False)
    monkeypatch.delenv("QFZ_TIME_LOCK_AS_OF", raising=False)


# ── pure helpers ─────────────────────────────────────────────────────────

def test_as_of_for_minute_and_daily_clocks():
    minute = {"frequency": "1m", "current_ts": "2025-01-02T14:30:00+00:00"}
    assert timelock.as_of_for_clock(minute) == "2025-01-02T14:31:00Z"      # bar close
    daily = {"frequency": "1d", "current_ts": "2025-01-02T00:00:00+00:00",
             "trading_date": "2025-01-02"}
    assert timelock.as_of_for_clock(daily) == "2025-01-02T21:00:00Z"       # 16:00 EST
    summer = {"frequency": "1d", "current_ts": "2025-06-02T00:00:00+00:00"}
    assert timelock.as_of_for_clock(summer) == "2025-06-02T20:00:00Z"      # 16:00 EDT
    assert timelock.as_of_for_clock({}) is None


def test_binding_priority_and_strict_mode(monkeypatch):
    assert timelock.bound_session("hdr", "arg") == "hdr"
    monkeypatch.setenv("QFZ_TIME_LOCK_SESSION", "env")
    assert timelock.bound_session(None, "arg") == "env"
    monkeypatch.delenv("QFZ_TIME_LOCK_SESSION")
    assert timelock.bound_session(None, "arg") == "arg"
    assert timelock.resolve(None, lambda s: {}) is None
    monkeypatch.setenv("QFZ_REQUIRE_SESSION", "1")
    with pytest.raises(timelock.TimeLockError):
        timelock.resolve(None, lambda s: {})
    with pytest.raises(timelock.TimeLockError):
        timelock.resolve("bad", lambda s: (_ for _ in ()).throw(KeyError(s)))


def test_clamps():
    a = "2025-01-02T14:31:00Z"
    assert timelock.clamp_end("2025-01-03T00:00:00Z", a) == a
    assert timelock.clamp_end("2025-01-02T10:00:00+00:00", a) == "2025-01-02T10:00:00+00:00"
    assert timelock.clamp_end(None, a) == a
    assert timelock.clamp_end("x", None) == "x"
    assert timelock.clamp_date("2025-01-09", a) == "2025-01-02"
    assert timelock.utc_iso("2025-01-02T09:30:00-05:00") == "2025-01-02T14:30:00"


# ── MCP tools ────────────────────────────────────────────────────────────

def _clock(minute_ts="2025-01-02T14:30:00+00:00"):
    responses.get(f"{MOCK_PMB_URL}/v1/sessions/sess_1/state",
                  json={"clock": {"frequency": "1m", "current_ts": minute_ts}})


def _qs(call):
    return {k: v[0] for k, v in parse_qs(urlparse(call.request.url).query).items()}


@responses.activate
def test_upq_tool_passes_as_of_for_bound_session():
    _clock()
    responses.get(f"{MOCK_UPQ_URL}/stock", json=[])
    srv.upq_stock_minute(["AAPL"], "2025-01-02T14:00:00", "2025-01-02T21:00:00", session_id="sess_1")
    q = _qs(responses.calls[-1])
    assert q["as_of"] == "2025-01-02T14:31:00Z"


@responses.activate
def test_header_binding_beats_the_agent_argument():
    _clock()
    responses.get(f"{MOCK_UPQ_URL}/stock/daily", json=[])
    ctx = NS(request_context=NS(request=NS(headers={"x-qfz-session": "sess_1"})))
    srv.upq_stock_daily(["AAPL"], "2025-01-01", "2025-12-31", session_id="other", ctx=ctx)
    assert "sess_1" in responses.calls[0].request.url
    assert _qs(responses.calls[-1])["as_of"] == "2025-01-02T14:31:00Z"


@responses.activate
def test_unbound_calls_unchanged_and_strict_mode_refuses(monkeypatch):
    responses.get(f"{MOCK_UPQ_URL}/stock", json=[])
    srv.upq_stock_minute(["AAPL"], "2025-01-02T14:00:00", "2025-01-02T21:00:00")
    assert "as_of" not in _qs(responses.calls[-1])
    monkeypatch.setenv("QFZ_REQUIRE_SESSION", "1")
    with pytest.raises(timelock.TimeLockError):
        srv.upq_stock_minute(["AAPL"], "2025-01-02T14:00:00", "2025-01-02T21:00:00")


@responses.activate
def test_esp_tools_run_as_of_the_session():
    _clock()
    responses.post(f"{MOCK_ESP_URL}/esp/events/query", json={"events": []})
    responses.post(f"{MOCK_ESP_URL}/esp/news/search", json={"items": []})
    srv.esp_query_events(mode="window", start_utc="2025-01-01T00:00:00Z",
                         end_utc="2025-01-09T00:00:00Z", now_utc="2030-01-01T00:00:00Z",
                         session_id="sess_1")
    ev = [c for c in responses.calls if "/esp/events/query" in c.request.url][-1]
    body = json.loads(ev.request.body)
    flat = json.dumps(body)
    assert "2030-01-01" not in flat                       # agent's now_utc overridden
    assert "2025-01-09" not in flat                       # window end capped
    assert "2025-01-02T14:31:00" in flat
    srv.esp_search_news(tickers=["AAPL"], session_id="sess_1")
    news = [c for c in responses.calls if "/news/search" in c.request.url][-1]
    assert "2025-01-02T14:31:00" in news.request.body.decode() \
        if isinstance(news.request.body, bytes) else news.request.body


@responses.activate
def test_chain_snapshot_defaults_to_session_time():
    _clock()
    responses.get(f"{MOCK_UPQ_URL}/option/chain_snapshot", json=[{"ticker": "O:X"}])
    out = json.loads(srv.upq_chain_snapshot("SPY", session_id="sess_1"))
    q = _qs(responses.calls[-1])
    assert out == [{"ticker": "O:X"}]
    assert (q["at"], q["as_of"]) == ("2025-01-02T14:31:00", "2025-01-02T14:31:00Z")


# ── fixed lock (the chat's cutoff, or X-QFZ-As-Of) ───────────────────────

CUTOFF = "2026-01-01T14:00:00Z"           # 09:00 ET on New Year's Day


def test_fixed_lock_helpers(monkeypatch):
    assert timelock.fixed_as_of() is None
    monkeypatch.setenv("QFZ_TIME_LOCK_AS_OF", "2026-01-01T09:00:00-05:00")
    assert timelock.fixed_as_of() == CUTOFF
    assert timelock.fixed_as_of("2025-06-02T20:00:00Z") == "2025-06-02T20:00:00Z"      # the header wins
    with pytest.raises(timelock.TimeLockError):
        timelock.fixed_as_of("next tuesday")
    assert timelock.earliest(None, "2026-01-02T00:00:00Z", CUTOFF) == CUTOFF
    assert timelock.last_closed_day(CUTOFF) == "2025-12-31"
    assert timelock.last_closed_day("2026-01-02T21:00:00Z") == "2026-01-02"           # 16:00 ET
    assert not timelock.day_complete("2026-01-01", CUTOFF) and timelock.day_complete("2025-12-31", CUTOFF)


@responses.activate
def test_fixed_lock_caps_data_tools_whatever_the_agent_asks(monkeypatch):
    """The chat bug: a cutoff of 2026-01-01 09:00 ET, the model asks for daily bars to 2026-02-24."""
    monkeypatch.setenv("QFZ_TIME_LOCK_AS_OF", CUTOFF)
    responses.get(f"{MOCK_UPQ_URL}/stock/daily", json=[])
    srv.upq_stock_daily(["MU", "WDC", "STX"], "2026-01-01", "2026-02-24")
    assert _qs(responses.calls[-1])["as_of"] == CUTOFF
    # a session clock later than the cutoff does not lift it; an earlier one wins
    _clock()
    responses.get(f"{MOCK_UPQ_URL}/stock", json=[])
    srv.upq_stock_minute(["AAPL"], "2025-01-02T14:00:00", "2025-01-02T21:00:00", session_id="sess_1")
    assert _qs(responses.calls[-1])["as_of"] == "2025-01-02T14:31:00Z"
    # the header sets it too
    monkeypatch.delenv("QFZ_TIME_LOCK_AS_OF")
    ctx = NS(request_context=NS(request=NS(headers={"x-qfz-as-of": CUTOFF})))
    srv.upq_stock_daily(["MU"], "2026-01-01", "2026-02-24", ctx=ctx)
    assert _qs(responses.calls[-1])["as_of"] == CUTOFF


@responses.activate
def test_fixed_lock_guards_day_accounts_and_sessions(monkeypatch):
    monkeypatch.setenv("QFZ_TIME_LOCK_AS_OF", CUTOFF)
    with pytest.raises(timelock.TimeLockError, match="after the last day closed"):
        srv.pmb_create_account(start_date="2026-01-02")
    responses.post(f"{MOCK_PMB_URL}/v1/accounts", json={"account_id": "1"})
    srv.pmb_create_account(start_date="2025-12-31")
    # a day account standing on the cutoff day (its close is not known at 09:00) cannot quote or trade
    responses.get(f"{MOCK_PMB_URL}/v1/accounts/7", json={"current_date": "2026-01-02"})
    with pytest.raises(timelock.TimeLockError):
        srv.pmb_quote("7", "SPY")
    responses.get(f"{MOCK_PMB_URL}/v1/accounts/8", json={"current_date": "2025-12-31"})
    with pytest.raises(timelock.TimeLockError, match="next trading day"):
        srv.pmb_next_day("8")                                     # -> 2026-01-01, not closed by 09:00
    # sessions end by the last bar closed at the cutoff
    responses.post(f"{MOCK_PMB_URL}/v1/sessions", json={"session_id": "s"})
    srv.pmb_create_session("1", "1m", "2025-12-31T14:30:00", "2026-01-31T21:00:00", stock_universe=["SPY"])
    sent = json.loads([c for c in responses.calls if c.request.url.endswith("/v1/sessions")][-1].request.body)
    assert sent["end_ts"] == "2026-01-01T13:59:00"
    with pytest.raises(timelock.TimeLockError):
        srv.pmb_create_session("1", "1d", "2026-01-05", "2026-01-30", stock_universe=["SPY"])
    responses.get(f"{MOCK_PMB_URL}/v1/sessions/late/state",
                  json={"clock": {"frequency": "1m", "end_ts": "2026-03-01T21:00:00", "current_ts": "2025-12-31T15:00:00"}})
    with pytest.raises(timelock.TimeLockError, match="ends at"):
        srv.pmb_step_session("late", 5)


@responses.activate
def test_fixed_lock_covers_the_store_description_tools(monkeypatch):
    monkeypatch.setenv("QFZ_TIME_LOCK_AS_OF", CUTOFF)
    monkeypatch.setattr(srv, "DATA_ADMIN_URL", "http://mock-data-admin:19340")
    responses.get("http://mock-data-admin:19340/coverage/extent", json={"stores": {
        "minute": {"start": "2025-08-24", "end": "2026-10-16", "days": 352},
        "crypto_minute": {"start": "2026-02-01", "end": "2026-02-24", "days": 24}}, "suggested": [{"ticker": "NBIS"}]})
    out = json.loads(srv.data_extent())
    assert out["stores"]["minute"] == {"start": "2025-08-24", "end": "2026-01-01", "days": None}
    assert out["stores"]["crypto_minute"] is None and "suggested" not in out
    responses.get("http://mock-data-admin:19340/coverage/matrix", json={"cells": {}, "kinds": {}})
    srv.data_coverage(["SPY"], "2025-12-01", "2026-03-01")
    assert "end=2026-01-01" in responses.calls[-1].request.url
    with pytest.raises(timelock.TimeLockError):
        srv.data_day("SPY", "2026-01-01")
    with pytest.raises(timelock.TimeLockError):
        srv.upq_freshness()
    with pytest.raises(timelock.TimeLockError):
        srv.admin_data_catalog()
