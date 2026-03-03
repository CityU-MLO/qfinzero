"""Tests for PMB client — HTTP-level mocks via responses library."""

import json

import pytest
import responses

from clients.pmb.client import PMBClient, PMBError, StepResult

MOCK_URL = "http://mock-pmb:19320"


@pytest.fixture
def client():
    c = PMBClient(MOCK_URL)
    yield c
    c.close()


# ═══════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════


class TestHealth:
    @responses.activate
    def test_health_happy_path(self, client):
        responses.get(f"{MOCK_URL}/v1/health", json={"status": "ok"})
        result = client.health()
        assert result["status"] == "ok"

    @responses.activate
    def test_health_error(self, client):
        responses.get(f"{MOCK_URL}/v1/health", json={"message": "down"}, status=500)
        with pytest.raises(PMBError):
            client.health()


# ═══════════════════════════════════════════════════════════════════
# Account
# ═══════════════════════════════════════════════════════════════════


class TestAccount:
    @responses.activate
    def test_create_account(self, client):
        resp = {"account_id": "acct-1", "created_at": "2025-01-06"}
        responses.post(f"{MOCK_URL}/v1/accounts", json=resp)
        result = client.create_account(initial_cash=100000.0, start_date="2025-01-06")
        assert result["account_id"] == "acct-1"
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["initial_cash"] == 100000.0
        assert req_body["account_type"] == "MARGIN"
        assert req_body["start_date"] == "2025-01-06"

    @responses.activate
    def test_create_cash_account(self, client):
        responses.post(f"{MOCK_URL}/v1/accounts", json={"account_id": "acct-2"})
        client.create_account(initial_cash=50000.0, account_type="CASH", start_date="2025-01-06")
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["account_type"] == "CASH"

    @responses.activate
    def test_get_account(self, client):
        resp = {"account_id": "acct-1", "cash_available": 100000.0}
        responses.get(f"{MOCK_URL}/v1/accounts/acct-1", json=resp)
        result = client.get_account("acct-1")
        assert result["cash_available"] == 100000.0


# ═══════════════════════════════════════════════════════════════════
# Positions / Orders / Trades
# ═══════════════════════════════════════════════════════════════════


class TestAccountData:
    @responses.activate
    def test_get_positions(self, client):
        resp = {"positions": [{"symbol": "AAPL", "qty": 100}]}
        responses.get(f"{MOCK_URL}/v1/accounts/acct-1/positions", json=resp)
        result = client.get_positions("acct-1")
        assert result == [{"symbol": "AAPL", "qty": 100}]

    @responses.activate
    def test_get_positions_empty(self, client):
        responses.get(f"{MOCK_URL}/v1/accounts/acct-1/positions", json={"positions": []})
        result = client.get_positions("acct-1")
        assert result == []

    @responses.activate
    def test_get_orders(self, client):
        resp = {"orders": [{"order_id": "ord-1", "status": "FILLED"}]}
        responses.get(f"{MOCK_URL}/v1/accounts/acct-1/orders", json=resp)
        result = client.get_orders("acct-1")
        assert result[0]["order_id"] == "ord-1"

    @responses.activate
    def test_get_orders_with_session_filter(self, client):
        responses.get(f"{MOCK_URL}/v1/accounts/acct-1/orders", json={"orders": []})
        client.get_orders("acct-1", session_id="sess-1")
        req = responses.calls[0].request
        assert "session_id=sess-1" in req.url

    @responses.activate
    def test_get_trades(self, client):
        resp = {"trades": [{"trade_id": "t-1", "price": 185.0}]}
        responses.get(f"{MOCK_URL}/v1/accounts/acct-1/trades", json=resp)
        result = client.get_trades("acct-1")
        assert result[0]["trade_id"] == "t-1"


# ═══════════════════════════════════════════════════════════════════
# Session
# ═══════════════════════════════════════════════════════════════════


class TestSession:
    @responses.activate
    def test_create_session(self, client):
        resp = {"session_id": "sess-1", "clock": {"status": "RUNNING"}}
        responses.post(f"{MOCK_URL}/v1/sessions", json=resp)
        result = client.create_session(
            account_id="acct-1", frequency="1d",
            start_ts="2025-01-06", end_ts="2025-01-31",
            universe={"stocks": ["AAPL"]},
        )
        assert result["session_id"] == "sess-1"
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["account_id"] == "acct-1"
        assert req_body["frequency"] == "1d"
        assert req_body["universe"] == {"stocks": ["AAPL"]}

    @responses.activate
    def test_step_returns_step_result(self, client):
        resp = {"ok": True, "clock": {"status": "RUNNING", "current_ts": "2025-01-07"}, "events": []}
        responses.post(f"{MOCK_URL}/v1/sessions/sess-1/step", json=resp)
        result = client.step("sess-1")
        assert isinstance(result, StepResult)
        assert result.is_running is True
        assert result.current_ts == "2025-01-07"

    @responses.activate
    def test_step_with_n(self, client):
        resp = {"ok": True, "clock": {"status": "RUNNING"}, "events": []}
        responses.post(f"{MOCK_URL}/v1/sessions/sess-1/step", json=resp)
        client.step("sess-1", n=5)
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["step"] == 5

    @responses.activate
    def test_stop_session(self, client):
        responses.post(f"{MOCK_URL}/v1/sessions/sess-1/stop", json={"ok": True})
        result = client.stop_session("sess-1")
        assert result["ok"] is True

    @responses.activate
    def test_get_summary(self, client):
        resp = {"total_return": 0.05, "sharpe_ratio": 1.2}
        responses.get(f"{MOCK_URL}/v1/sessions/sess-1/summary", json=resp)
        result = client.get_summary("sess-1")
        assert result["sharpe_ratio"] == 1.2

    @responses.activate
    def test_get_market(self, client):
        resp = {"stocks": [{"symbol": "AAPL", "close": 185.0}]}
        responses.get(f"{MOCK_URL}/v1/sessions/sess-1/market", json=resp)
        result = client.get_market("sess-1")
        assert result["stocks"][0]["symbol"] == "AAPL"


# ═══════════════════════════════════════════════════════════════════
# Export
# ═══════════════════════════════════════════════════════════════════


class TestExport:
    @responses.activate
    def test_export_json(self, client):
        resp = {"trades": [], "metrics": {}}
        responses.get(f"{MOCK_URL}/v1/sessions/sess-1/export", json=resp)
        result = client.export("sess-1", fmt="json")
        assert isinstance(result, dict)

    @responses.activate
    def test_export_csv(self, client):
        responses.get(f"{MOCK_URL}/v1/sessions/sess-1/export", body="date,pnl\n2025-01-06,100\n")
        result = client.export("sess-1", fmt="csv")
        assert isinstance(result, str)
        assert "date,pnl" in result


# ═══════════════════════════════════════════════════════════════════
# Orders — buy/sell stock
# ═══════════════════════════════════════════════════════════════════


class TestStockOrders:
    @responses.activate
    def test_buy_market_order(self, client):
        resp = {"order_id": "ord-1", "status": "PENDING"}
        responses.post(f"{MOCK_URL}/v1/orders", json=resp)
        result = client.buy("sess-1", "acct-1", "AAPL", 100)
        assert result["order_id"] == "ord-1"
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["order"]["instrument"] == {"type": "STOCK", "symbol": "AAPL"}
        assert req_body["order"]["side"] == "BUY"
        assert req_body["order"]["qty"] == 100
        assert req_body["order"]["order_type"] == "MARKET"

    @responses.activate
    def test_buy_limit_order(self, client):
        responses.post(f"{MOCK_URL}/v1/orders", json={"order_id": "ord-2"})
        client.buy("sess-1", "acct-1", "AAPL", 50, order_type="LIMIT", limit_price=180.0)
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["order"]["order_type"] == "LIMIT"
        assert req_body["order"]["limit_price"] == 180.0

    @responses.activate
    def test_sell_market_order(self, client):
        responses.post(f"{MOCK_URL}/v1/orders", json={"order_id": "ord-3"})
        result = client.sell("sess-1", "acct-1", "AAPL", 50)
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["order"]["side"] == "SELL"

    @responses.activate
    def test_buy_stop_limit_order(self, client):
        responses.post(f"{MOCK_URL}/v1/orders", json={"order_id": "ord-4"})
        client.buy(
            "sess-1", "acct-1", "AAPL", 100,
            order_type="STOP_LIMIT", limit_price=185.0, stop_price=184.0,
        )
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["order"]["order_type"] == "STOP_LIMIT"
        assert req_body["order"]["limit_price"] == 185.0
        assert req_body["order"]["stop_price"] == 184.0

    @responses.activate
    def test_client_order_id(self, client):
        responses.post(f"{MOCK_URL}/v1/orders", json={"order_id": "ord-5"})
        client.buy("sess-1", "acct-1", "AAPL", 100, client_order_id="my-id-1")
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["client_order_id"] == "my-id-1"

    @responses.activate
    def test_no_client_order_id_when_omitted(self, client):
        responses.post(f"{MOCK_URL}/v1/orders", json={"order_id": "ord-6"})
        client.buy("sess-1", "acct-1", "AAPL", 100)
        req_body = json.loads(responses.calls[0].request.body)
        assert "client_order_id" not in req_body

    @responses.activate
    def test_time_in_force(self, client):
        responses.post(f"{MOCK_URL}/v1/orders", json={"order_id": "ord-7"})
        client.buy("sess-1", "acct-1", "AAPL", 100, time_in_force="GTC")
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["order"]["time_in_force"] == "GTC"


# ═══════════════════════════════════════════════════════════════════
# Orders — buy/sell option
# ═══════════════════════════════════════════════════════════════════


class TestOptionOrders:
    @responses.activate
    def test_buy_option_market(self, client):
        responses.post(f"{MOCK_URL}/v1/orders", json={"order_id": "ord-10"})
        result = client.buy_option("sess-1", "acct-1", "O:NVDA250117C00136000", 5)
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["order"]["instrument"] == {"type": "OPTION", "contract": "O:NVDA250117C00136000"}
        assert req_body["order"]["side"] == "BUY"
        assert req_body["order"]["qty"] == 5

    @responses.activate
    def test_sell_option_limit(self, client):
        responses.post(f"{MOCK_URL}/v1/orders", json={"order_id": "ord-11"})
        client.sell_option("sess-1", "acct-1", "O:NVDA250117C00136000", 5, order_type="LIMIT", limit_price=6.50)
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["order"]["side"] == "SELL"
        assert req_body["order"]["order_type"] == "LIMIT"
        assert req_body["order"]["limit_price"] == 6.50

    @responses.activate
    def test_option_default_tif_is_gtc(self, client):
        responses.post(f"{MOCK_URL}/v1/orders", json={"order_id": "ord-12"})
        client.buy_option("sess-1", "acct-1", "O:NVDA250117C00136000", 1)
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["order"]["time_in_force"] == "GTC"


# ═══════════════════════════════════════════════════════════════════
# Cancel Order
# ═══════════════════════════════════════════════════════════════════


class TestCancelOrder:
    @responses.activate
    def test_cancel_order(self, client):
        responses.post(f"{MOCK_URL}/v1/orders/ord-1/cancel", json={"ok": True})
        result = client.cancel_order("ord-1", "sess-1", "acct-1")
        assert result["ok"] is True
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["session_id"] == "sess-1"
        assert req_body["account_id"] == "acct-1"


# ═══════════════════════════════════════════════════════════════════
# Error Handling
# ═══════════════════════════════════════════════════════════════════


class TestErrorHandling:
    @responses.activate
    def test_non_json_response(self, client):
        responses.get(f"{MOCK_URL}/v1/health", body="bad gateway", status=502)
        with pytest.raises(PMBError, match="Non-JSON response"):
            client.health()

    @responses.activate
    def test_error_preserves_status_and_response(self, client):
        error_data = {"message": "insufficient funds", "detail": "not enough cash"}
        responses.post(f"{MOCK_URL}/v1/orders", json=error_data, status=400)
        with pytest.raises(PMBError) as exc:
            client.buy("sess-1", "acct-1", "AAPL", 100)
        assert exc.value.status_code == 400
        assert exc.value.response == error_data
