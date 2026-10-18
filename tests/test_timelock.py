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
