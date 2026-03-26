"""Tests for UPQ client — HTTP-level mocks via responses library."""

import json

import pytest
import responses

from clients.upq.client import UPQClient, UPQError

MOCK_URL = "http://mock-upq:19350"


@pytest.fixture
def client():
    c = UPQClient(MOCK_URL)
    yield c
    c.close()


# ═══════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════


class TestHealth:
    def test_default_base_url_uses_standard_upq_port(self):
        client = UPQClient()
        try:
            assert client.base_url == "http://127.0.0.1:19703"
        finally:
            client.close()

    @responses.activate
    def test_health_happy_path(self, client):
        responses.get(f"{MOCK_URL}/health", json={"status": "ok"})
        result = client.health()
        assert result == {"status": "ok"}
        assert responses.calls[0].request.url == f"{MOCK_URL}/health"

    @responses.activate
    def test_health_server_error(self, client):
        responses.get(f"{MOCK_URL}/health", json={"message": "down"}, status=500)
        with pytest.raises(UPQError) as exc:
            client.health()
        assert exc.value.status_code == 500

    @responses.activate
    def test_freshness(self, client):
        body = {"sources": [{"name": "stock_daily", "latest": "2025-01-31"}]}
        responses.get(f"{MOCK_URL}/health/freshness", json=body)
        result = client.freshness()
        assert result["sources"][0]["name"] == "stock_daily"


# ═══════════════════════════════════════════════════════════════════
# Stock Daily
# ═══════════════════════════════════════════════════════════════════


class TestStockDaily:
    @responses.activate
    def test_happy_path(self, client):
        bars = [{"ticker": "AAPL", "date": "2025-01-06", "close": 185.0}]
        responses.get(f"{MOCK_URL}/stock/daily", json=bars)
        result = client.stock_daily(["AAPL"], "2025-01-06", "2025-01-31")
        assert result == bars
        # Verify query params
        req = responses.calls[0].request
        assert "tickers=AAPL" in req.url
        assert "start=2025-01-06" in req.url
        assert "end=2025-01-31" in req.url

    @responses.activate
    def test_multiple_tickers(self, client):
        responses.get(f"{MOCK_URL}/stock/daily", json=[])
        client.stock_daily(["AAPL", "NVDA"], "2025-01-06", "2025-01-31")
        req = responses.calls[0].request
        assert "tickers=AAPL%2CNVDA" in req.url or "tickers=AAPL,NVDA" in req.url

    @responses.activate
    def test_with_fields(self, client):
        responses.get(f"{MOCK_URL}/stock/daily", json=[])
        client.stock_daily(["AAPL"], "2025-01-06", "2025-01-31", fields="date,close")
        req = responses.calls[0].request
        assert "fields=date%2Cclose" in req.url or "fields=date,close" in req.url

    @responses.activate
    def test_without_fields(self, client):
        responses.get(f"{MOCK_URL}/stock/daily", json=[])
        client.stock_daily(["AAPL"], "2025-01-06", "2025-01-31")
        req = responses.calls[0].request
        assert "fields" not in req.url

    @responses.activate
    def test_error_400(self, client):
        responses.get(
            f"{MOCK_URL}/stock/daily",
            json={"message": "invalid date", "code": "BAD_REQUEST"},
            status=400,
        )
        with pytest.raises(UPQError) as exc:
            client.stock_daily(["AAPL"], "bad-date", "2025-01-31")
        assert exc.value.status_code == 400
        assert "invalid date" in str(exc.value)


# ═══════════════════════════════════════════════════════════════════
# Stock Minute
# ═══════════════════════════════════════════════════════════════════


class TestStockMinute:
    @responses.activate
    def test_happy_path(self, client):
        bars = [{"ticker": "AAPL", "window_start": 1705326600000000000, "close": 185.0}]
        responses.get(f"{MOCK_URL}/stock", json=bars)
        result = client.stock_minute(["AAPL"], "2025-01-06T14:30:00", "2025-01-06T21:00:00")
        assert result == bars

    @responses.activate
    def test_with_limit(self, client):
        responses.get(f"{MOCK_URL}/stock", json=[])
        client.stock_minute(["AAPL"], "2025-01-06T14:30:00", "2025-01-06T21:00:00", limit=500)
        req = responses.calls[0].request
        assert "limit=500" in req.url

    @responses.activate
    def test_default_no_limit_param(self, client):
        responses.get(f"{MOCK_URL}/stock", json=[])
        client.stock_minute(["AAPL"], "2025-01-06T14:30:00", "2025-01-06T21:00:00")
        req = responses.calls[0].request
        assert "limit" not in req.url


# ═══════════════════════════════════════════════════════════════════
# Option Chain
# ═══════════════════════════════════════════════════════════════════


class TestOptionChain:
    @responses.activate
    def test_happy_path(self, client):
        chain = [{"ticker": "O:NVDA250117C00136000", "close": 5.50}]
        responses.get(f"{MOCK_URL}/option/chain_query", json=chain)
        result = client.option_chain("NVDA", "2025-01-06")
        assert result == chain
        req = responses.calls[0].request
        assert "underlying=NVDA" in req.url
        assert "date=2025-01-06" in req.url

    @responses.activate
    def test_all_filters(self, client):
        responses.get(f"{MOCK_URL}/option/chain_query", json=[])
        client.option_chain(
            "NVDA", "2025-01-06",
            expiry_min="2025-01-17", expiry_max="2025-02-21",
            strike_min=130.0, strike_max=150.0,
            type="C", fields="ticker,close",
        )
        req = responses.calls[0].request
        assert "expiry_min=2025-01-17" in req.url
        assert "expiry_max=2025-02-21" in req.url
        assert "strike_min=130" in req.url
        assert "strike_max=150" in req.url
        assert "type=C" in req.url

    @responses.activate
    def test_optional_params_omitted(self, client):
        responses.get(f"{MOCK_URL}/option/chain_query", json=[])
        client.option_chain("NVDA", "2025-01-06")
        req = responses.calls[0].request
        assert "expiry_min" not in req.url
        assert "strike_min" not in req.url
        assert "type" not in req.url

    @responses.activate
    def test_with_greeks(self, client):
        responses.get(f"{MOCK_URL}/option/chain_query", json=[])
        client.option_chain("NVDA", "2025-01-06", include_greeks=True)
        req = responses.calls[0].request
        assert "include_greeks=true" in req.url


# ═══════════════════════════════════════════════════════════════════
# Option Contract
# ═══════════════════════════════════════════════════════════════════


class TestOptionContract:
    @responses.activate
    def test_happy_path(self, client):
        bars = [{"contract": "O:NVDA250117C00136000", "close": 5.50}]
        responses.get(f"{MOCK_URL}/option/ticker_query", json=bars)
        result = client.option_contract("O:NVDA250117C00136000", "2025-01-06", "2025-01-17")
        assert result == bars
        req = responses.calls[0].request
        assert "contract=O%3ANVDA250117C00136000" in req.url or "contract=O:NVDA250117C00136000" in req.url

    @responses.activate
    def test_minute_resolution(self, client):
        responses.get(f"{MOCK_URL}/option/ticker_query", json=[])
        client.option_contract("O:NVDA250117C00136000", "2025-01-06T14:30:00", "2025-01-06T21:00:00", resolution="minute")
        req = responses.calls[0].request
        assert "resolution=minute" in req.url

    @responses.activate
    def test_with_greeks(self, client):
        responses.get(f"{MOCK_URL}/option/ticker_query", json=[])
        client.option_contract(
            "O:NVDA250117C00136000", "2025-01-06", "2025-01-17",
            include_greeks=True, greek_model="bsm", greek_price_field="close",
        )
        req = responses.calls[0].request
        assert "include_greeks=true" in req.url
        assert "greek_model=bsm" in req.url
        assert "greek_price_field=close" in req.url


# ═══════════════════════════════════════════════════════════════════
# Rates
# ═══════════════════════════════════════════════════════════════════


class TestRates:
    @responses.activate
    def test_happy_path(self, client):
        rates = [{"date": "2025-01-06", "yield_10_year": 4.60}]
        responses.get(f"{MOCK_URL}/rates/query", json=rates)
        result = client.rates("2025-01-06", "2025-01-31")
        assert result == rates

    @responses.activate
    def test_with_tenors(self, client):
        responses.get(f"{MOCK_URL}/rates/query", json=[])
        client.rates("2025-01-06", "2025-01-31", tenors="1M,10Y")
        req = responses.calls[0].request
        assert "tenors=1M%2C10Y" in req.url or "tenors=1M,10Y" in req.url

    @responses.activate
    def test_without_tenors(self, client):
        responses.get(f"{MOCK_URL}/rates/query", json=[])
        client.rates("2025-01-06", "2025-01-31")
        req = responses.calls[0].request
        assert "tenors" not in req.url


# ═══════════════════════════════════════════════════════════════════
# Error Handling (shared patterns)
# ═══════════════════════════════════════════════════════════════════


class TestErrorHandling:
    @responses.activate
    def test_non_json_response(self, client):
        responses.get(f"{MOCK_URL}/health", body="not json", status=502)
        with pytest.raises(UPQError, match="Non-JSON response"):
            client.health()

    @responses.activate
    def test_error_preserves_code(self, client):
        responses.get(
            f"{MOCK_URL}/health",
            json={"message": "not found", "code": "NOT_FOUND"},
            status=404,
        )
        with pytest.raises(UPQError) as exc:
            client.health()
        assert exc.value.code == "NOT_FOUND"
        assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Context Manager
# ═══════════════════════════════════════════════════════════════════


class TestContextManager:
    @responses.activate
    def test_context_manager(self):
        responses.get(f"{MOCK_URL}/health", json={"status": "ok"})
        with UPQClient(MOCK_URL) as c:
            result = c.health()
        assert result == {"status": "ok"}
