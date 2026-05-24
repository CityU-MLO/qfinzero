"""Tests for MCP tool functions in mcp/server.py.

These test that the tool layer correctly:
1. Forwards parameters to client methods
2. Serializes return values as JSON strings
3. Handles special logic (date conversion, universe building)

Note: The local ``mcp/`` directory name collides with the ``mcp`` pip package
(FastMCP).  ``import mcp.server`` resolves to the *pip* package, not our local
file.  We therefore load the module via ``importlib`` from its file path and
register it under a private name so every test can reference it cleanly.
"""

import importlib.util
import json
import os
import sys

import pytest
import responses

# ── Resolve project root the same way server.py does ─────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.conftest import MOCK_UPQ_URL, MOCK_ESP_URL, MOCK_PMB_URL

# ── Load mcp/server.py via importlib (avoids pip-package collision) ──────
_SERVER_PATH = os.path.join(PROJECT_ROOT, "mcp", "server.py")
_spec = importlib.util.spec_from_file_location("_qfz_mcp_server", _SERVER_PATH)
_srv_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_srv_mod)


@pytest.fixture(autouse=True)
def _patch_urls(monkeypatch):
    """Ensure all tools use mock URLs."""
    monkeypatch.setattr(_srv_mod, "UPQ_URL", MOCK_UPQ_URL)
    monkeypatch.setattr(_srv_mod, "ESP_URL", MOCK_ESP_URL)
    monkeypatch.setattr(_srv_mod, "PMB_URL", MOCK_PMB_URL)


def _srv():
    """Return the patched server module."""
    return _srv_mod


# ═══════════════════════════════════════════════════════════════════
# UPQ Tools
# ═══════════════════════════════════════════════════════════════════


class TestUPQTools:
    @responses.activate
    def test_upq_health(self):
        responses.get(f"{MOCK_UPQ_URL}/health", json={"status": "ok"})
        result = _srv().upq_health()
        assert json.loads(result) == {"status": "ok"}

    @responses.activate
    def test_upq_stock_daily(self):
        bars = [{"ticker": "AAPL", "close": 185.0}]
        responses.get(f"{MOCK_UPQ_URL}/stock/daily", json=bars)
        result = _srv().upq_stock_daily(["AAPL"], "2025-01-06", "2025-01-31")
        assert json.loads(result) == bars

    @responses.activate
    def test_upq_stock_minute(self):
        bars = [{"ticker": "AAPL", "close": 185.0}]
        responses.get(f"{MOCK_UPQ_URL}/stock", json=bars)
        result = _srv().upq_stock_minute(["AAPL"], "2025-01-06T14:30:00", "2025-01-06T21:00:00")
        assert json.loads(result) == bars

    @responses.activate
    def test_upq_option_chain(self):
        chain = [{"ticker": "O:NVDA250117C00136000"}]
        responses.get(f"{MOCK_UPQ_URL}/option/chain_query", json=chain)
        result = _srv().upq_option_chain("NVDA", "2025-01-06")
        assert json.loads(result) == chain

    @responses.activate
    def test_upq_option_chain_with_greeks(self):
        responses.get(f"{MOCK_UPQ_URL}/option/chain_query", json=[])
        _srv().upq_option_chain("NVDA", "2025-01-06", include_greeks=True, greek_model="bsm")
        req = responses.calls[0].request
        assert "include_greeks=true" in req.url
        assert "greek_model=bsm" in req.url

    @responses.activate
    def test_upq_option_contract(self):
        bars = [{"close": 5.50}]
        responses.get(f"{MOCK_UPQ_URL}/option/ticker_query", json=bars)
        result = _srv().upq_option_contract("O:NVDA250117C00136000", "2025-01-06", "2025-01-17")
        assert json.loads(result) == bars

    @responses.activate
    def test_upq_rates(self):
        rates = [{"date": "2025-01-06"}]
        responses.get(f"{MOCK_UPQ_URL}/rates/query", json=rates)
        result = _srv().upq_rates("2025-01-06", "2025-01-31")
        assert json.loads(result) == rates

    def test_upq_make_opra(self):
        result = _srv().upq_make_opra("NVDA", "2025-01-17", "C", 136.0)
        assert json.loads(result) == "O:NVDA250117C00136000"

    def test_upq_ns_to_iso(self):
        ns = 1705329000 * 1_000_000_000
        result = _srv().upq_ns_to_iso(ns)
        assert "2024-01-15T14:30:00" in result


# ═══════════════════════════════════════════════════════════════════
# ESP Tools
# ═══════════════════════════════════════════════════════════════════


class TestESPTools:
    @responses.activate
    def test_esp_health(self):
        responses.get(f"{MOCK_ESP_URL}/esp/health", json={"status": "ok"})
        result = _srv().esp_health()
        assert json.loads(result)["status"] == "ok"

    @responses.activate
    def test_esp_query_events(self):
        body = {"events": [{"event_id": "e1"}]}
        responses.post(f"{MOCK_ESP_URL}/esp/events/query", json=body)
        result = _srv().esp_query_events(mode="upcoming")
        assert len(json.loads(result)["events"]) == 1

    @responses.activate
    def test_esp_query_events_date_conversion(self):
        """start_date/end_date should be converted to start_utc/end_utc."""
        responses.post(f"{MOCK_ESP_URL}/esp/events/query", json={"events": []})
        _srv().esp_query_events(
            mode="window",
            start_date="2025-01-15",
            end_date="2025-01-16",
        )
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["start_utc"] == "2025-01-15T00:00:00+00:00"
        assert req_body["end_utc"] == "2025-01-16T23:59:59+00:00"

    @responses.activate
    def test_esp_query_events_start_utc_takes_precedence(self):
        """If start_utc is provided, start_date should not override it."""
        responses.post(f"{MOCK_ESP_URL}/esp/events/query", json={"events": []})
        _srv().esp_query_events(
            mode="window",
            start_utc="2025-01-15T10:00:00Z",
            start_date="2025-01-15",
        )
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["start_utc"] == "2025-01-15T10:00:00Z"

    @responses.activate
    def test_esp_get_event(self):
        responses.get(f"{MOCK_ESP_URL}/esp/events/ev1", json={"event_id": "ev1"})
        result = _srv().esp_get_event("ev1")
        assert json.loads(result)["event_id"] == "ev1"

    @responses.activate
    def test_esp_stream_events(self):
        responses.post(f"{MOCK_ESP_URL}/esp/events/stream", json={"events": []})
        result = _srv().esp_stream_events(cursor="c1")
        assert json.loads(result)["events"] == []

    @responses.activate
    def test_esp_econ_calendar(self):
        responses.post(f"{MOCK_ESP_URL}/esp/calendar/econ", json={"events": []})
        result = _srv().esp_econ_calendar(start_date="2025-01-01")
        assert json.loads(result)["events"] == []

    @responses.activate
    def test_esp_earnings_calendar(self):
        responses.post(f"{MOCK_ESP_URL}/esp/calendar/earnings", json={"events": []})
        result = _srv().esp_earnings_calendar(tickers=["AAPL"])
        assert json.loads(result)["events"] == []

    @responses.activate
    def test_esp_next_triggers(self):
        responses.post(f"{MOCK_ESP_URL}/esp/triggers/next", json={"triggers": []})
        result = _srv().esp_next_triggers(tickers=["AAPL"])
        assert json.loads(result)["triggers"] == []

    @responses.activate
    def test_esp_news_body(self):
        responses.get(f"{MOCK_ESP_URL}/esp/news/n1/body", json={"title": "News"})
        result = _srv().esp_news_body("n1")
        assert json.loads(result)["title"] == "News"

    @responses.activate
    def test_esp_search_news(self):
        responses.post(f"{MOCK_ESP_URL}/esp/news/search", json={"events": []})
        result = _srv().esp_search_news(keyword="earnings")
        assert json.loads(result)["events"] == []

    @responses.activate
    def test_esp_timeline(self):
        responses.post(f"{MOCK_ESP_URL}/esp/timeline", json={"buckets": []})
        result = _srv().esp_timeline(tickers=["AAPL"])
        assert json.loads(result)["buckets"] == []


# ═══════════════════════════════════════════════════════════════════
# PMB Tools
# ═══════════════════════════════════════════════════════════════════


class TestPMBTools:
    @responses.activate
    def test_pmb_health(self):
        responses.get(f"{MOCK_PMB_URL}/v1/health", json={"status": "ok"})
        result = _srv().pmb_health()
        assert json.loads(result)["status"] == "ok"

    @responses.activate
    def test_pmb_create_account(self):
        responses.post(f"{MOCK_PMB_URL}/v1/accounts", json={"account_id": "a1"})
        result = _srv().pmb_create_account(100000.0, "2025-01-06")
        assert json.loads(result)["account_id"] == "a1"

    @responses.activate
    def test_pmb_get_account(self):
        responses.get(f"{MOCK_PMB_URL}/v1/accounts/a1", json={"cash": 100000.0})
        result = _srv().pmb_get_account("a1")
        assert json.loads(result)["cash"] == 100000.0

    @responses.activate
    def test_pmb_create_session_builds_universe(self):
        """stock_universe and option_universe should be combined into universe dict."""
        responses.post(f"{MOCK_PMB_URL}/v1/sessions", json={"session_id": "s1"})
        _srv().pmb_create_session(
            "a1", "1d", "2025-01-06", "2025-01-31",
            stock_universe=["AAPL", "NVDA"],
            option_universe=["SPY"],
        )
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["universe"] == {"stocks": ["AAPL", "NVDA"], "options": ["SPY"]}

    @responses.activate
    def test_pmb_create_session_empty_universe(self):
        """No stock_universe/option_universe -> empty universe."""
        responses.post(f"{MOCK_PMB_URL}/v1/sessions", json={"session_id": "s1"})
        _srv().pmb_create_session("a1", "1d", "2025-01-06", "2025-01-31")
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["universe"] == {}

    @responses.activate
    def test_pmb_step_session(self):
        resp = {"ok": True, "clock": {"status": "RUNNING"}, "events": [], "session_id": "s1"}
        responses.post(f"{MOCK_PMB_URL}/v1/sessions/s1/step", json=resp)
        result = _srv().pmb_step_session("s1")
        parsed = json.loads(result)
        assert parsed["ok"] is True

    @responses.activate
    def test_pmb_buy_stock(self):
        responses.post(f"{MOCK_PMB_URL}/v1/orders", json={"order_id": "o1"})
        result = _srv().pmb_buy_stock("s1", "a1", "AAPL", 100)
        assert json.loads(result)["order_id"] == "o1"

    @responses.activate
    def test_pmb_sell_stock(self):
        responses.post(f"{MOCK_PMB_URL}/v1/orders", json={"order_id": "o2"})
        result = _srv().pmb_sell_stock("s1", "a1", "AAPL", 50)
        assert json.loads(result)["order_id"] == "o2"

    @responses.activate
    def test_pmb_buy_option(self):
        responses.post(f"{MOCK_PMB_URL}/v1/orders", json={"order_id": "o3"})
        result = _srv().pmb_buy_option("s1", "a1", "O:NVDA250117C00136000", 5)
        assert json.loads(result)["order_id"] == "o3"

    @responses.activate
    def test_pmb_sell_option(self):
        responses.post(f"{MOCK_PMB_URL}/v1/orders", json={"order_id": "o4"})
        result = _srv().pmb_sell_option("s1", "a1", "O:NVDA250117C00136000", 5)
        assert json.loads(result)["order_id"] == "o4"

    @responses.activate
    def test_pmb_cancel_order(self):
        responses.post(f"{MOCK_PMB_URL}/v1/orders/o1/cancel", json={"ok": True})
        result = _srv().pmb_cancel_order("o1", "s1", "a1")
        assert json.loads(result)["ok"] is True

    @responses.activate
    def test_pmb_get_positions(self):
        responses.get(f"{MOCK_PMB_URL}/v1/accounts/a1/positions", json={"positions": []})
        result = _srv().pmb_get_positions("a1")
        assert json.loads(result) == []

    @responses.activate
    def test_pmb_get_orders(self):
        responses.get(f"{MOCK_PMB_URL}/v1/accounts/a1/orders", json={"orders": []})
        result = _srv().pmb_get_orders("a1")
        assert json.loads(result) == []

    @responses.activate
    def test_pmb_get_trades(self):
        responses.get(f"{MOCK_PMB_URL}/v1/accounts/a1/trades", json={"trades": []})
        result = _srv().pmb_get_trades("a1")
        assert json.loads(result) == []

    @responses.activate
    def test_pmb_get_market(self):
        responses.get(f"{MOCK_PMB_URL}/v1/sessions/s1/market", json={"stocks": []})
        result = _srv().pmb_get_market("s1")
        assert json.loads(result)["stocks"] == []

    @responses.activate
    def test_pmb_stop_session(self):
        responses.post(f"{MOCK_PMB_URL}/v1/sessions/s1/stop", json={"ok": True})
        result = _srv().pmb_stop_session("s1")
        assert json.loads(result)["ok"] is True

    @responses.activate
    def test_pmb_get_summary(self):
        responses.get(f"{MOCK_PMB_URL}/v1/sessions/s1/summary", json={"total_return": 0.05})
        result = _srv().pmb_get_summary("s1")
        assert json.loads(result)["total_return"] == 0.05

    @responses.activate
    def test_pmb_export_json(self):
        responses.get(f"{MOCK_PMB_URL}/v1/sessions/s1/export", json={"trades": []})
        result = _srv().pmb_export_session("s1", fmt="json")
        assert json.loads(result)["trades"] == []

    @responses.activate
    def test_pmb_export_csv(self):
        responses.get(f"{MOCK_PMB_URL}/v1/sessions/s1/export", body="date,pnl\n")
        result = _srv().pmb_export_session("s1", fmt="csv")
        assert "date,pnl" in result
