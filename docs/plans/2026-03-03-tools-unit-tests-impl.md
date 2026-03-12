# Tools Unit & Regression Test Suite — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add ~117 unit/regression tests covering all 34 MCP tools, 3 REST clients, and pure utility functions to prevent regressions on code changes.

**Architecture:** HTTP-level mock tests using `responses` library. Each test intercepts `requests` calls at the transport layer, validating the full stack: MCP tool → client → HTTP request → response parsing. Pure utility functions tested without mocks.

**Tech Stack:** Python 3.10+, pytest, responses library

---

### Task 1: Project Setup — Add `responses` dependency and `tests/` scaffold

**Files:**
- Modify: `pyproject.toml:12-13`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Update pyproject.toml to add `responses` dependency**

In `pyproject.toml`, change:
```toml
dev = ["pytest"]
```
to:
```toml
dev = ["pytest", "responses"]
```

**Step 2: Install dev dependencies**

Run: `pip install -e ".[dev]"`
Expected: Successfully installed responses

**Step 3: Create tests directory and conftest.py**

Create `tests/__init__.py` (empty).

Create `tests/conftest.py`:

```python
"""Shared test fixtures for tools unit tests."""

import os
import pytest

# Mock base URLs — no real servers needed
MOCK_UPQ_URL = "http://mock-upq:19350"
MOCK_NPP_URL = "http://mock-npp:19330"
MOCK_PMB_URL = "http://mock-pmb:19320"


@pytest.fixture
def mock_env(monkeypatch):
    """Patch env vars so MCP tools use mock URLs."""
    monkeypatch.setenv("QFINZERO_UPQ_URL", MOCK_UPQ_URL)
    monkeypatch.setenv("QFINZERO_NPP_URL", MOCK_NPP_URL)
    monkeypatch.setenv("QFINZERO_PMB_URL", MOCK_PMB_URL)
```

**Step 4: Verify pytest discovers the tests directory**

Run: `pytest tests/ --collect-only`
Expected: "no tests ran" (0 items collected, no errors)

**Step 5: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/conftest.py
git commit -m "chore: scaffold tests/ directory with conftest and responses dep"
```

---

### Task 2: Pure Utility Tests — `make_opra`, `ns_to_iso`, `StepResult`

**Files:**
- Create: `tests/test_pure_utils.py`

These are pure functions with no HTTP calls — no mocking needed.

**Step 1: Write the test file**

Create `tests/test_pure_utils.py`:

```python
"""Tests for pure utility functions — no HTTP mocking needed."""

import json
from datetime import datetime, timezone

import pytest

from clients.upq.client import UPQClient
from clients.pmb.client import StepResult


# ═══════════════════════════════════════════════════════════════════
# UPQClient.make_opra
# ═══════════════════════════════════════════════════════════════════


class TestMakeOpra:
    def test_basic_call(self):
        result = UPQClient.make_opra("NVDA", "2025-01-17", "C", 136.0)
        assert result == "O:NVDA250117C00136000"

    def test_put_option(self):
        result = UPQClient.make_opra("AAPL", "2025-06-20", "P", 200.0)
        assert result == "O:AAPL250620P00200000"

    def test_fractional_strike(self):
        result = UPQClient.make_opra("SPY", "2025-03-21", "C", 450.50)
        assert result == "O:SPY250321C00450500"

    def test_small_strike(self):
        result = UPQClient.make_opra("F", "2025-12-19", "P", 12.0)
        assert result == "O:F251219P00012000"

    def test_large_strike(self):
        result = UPQClient.make_opra("BRK", "2026-01-16", "C", 99999.0)
        assert result == "O:BRK260116C99999000"

    def test_single_char_underlying(self):
        result = UPQClient.make_opra("X", "2025-09-19", "C", 25.0)
        assert result == "O:X250919C00025000"


# ═══════════════════════════════════════════════════════════════════
# upq_ns_to_iso (via server.py function)
# ═══════════════════════════════════════════════════════════════════


class TestNsToIso:
    """Test the ns-to-ISO conversion used by upq_ns_to_iso tool."""

    @staticmethod
    def _convert(ns: int) -> str:
        """Replicate the conversion logic from mcp/server.py."""
        return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc).isoformat()

    def test_epoch_zero(self):
        assert self._convert(0) == "1970-01-01T00:00:00+00:00"

    def test_known_timestamp(self):
        # 2024-01-15T14:30:00 UTC = 1705326600 seconds
        ns = 1705326600 * 1_000_000_000
        result = self._convert(ns)
        assert result == "2024-01-15T14:30:00+00:00"

    def test_sub_second_truncated(self):
        # 500ms past epoch should still show :00
        ns = 500_000_000
        result = self._convert(ns)
        assert result.startswith("1970-01-01T00:00:00")


# ═══════════════════════════════════════════════════════════════════
# StepResult
# ═══════════════════════════════════════════════════════════════════


class TestStepResult:
    def test_is_running_true(self):
        sr = StepResult({"ok": True, "clock": {"status": "RUNNING"}})
        assert sr.is_running is True

    def test_is_running_false_when_finished(self):
        sr = StepResult({"ok": True, "clock": {"status": "FINISHED"}})
        assert sr.is_running is False

    def test_is_running_false_when_not_ok(self):
        sr = StepResult({"ok": False, "clock": {"status": "RUNNING"}})
        assert sr.is_running is False

    def test_current_ts(self):
        sr = StepResult({"ok": True, "clock": {"current_ts": "2025-01-15T10:00:00"}})
        assert sr.current_ts == "2025-01-15T10:00:00"

    def test_current_ts_empty_when_missing(self):
        sr = StepResult({"ok": True, "clock": {}})
        assert sr.current_ts == ""

    def test_get_event_found(self):
        sr = StepResult({"ok": True, "clock": {}, "events": [
            {"type": "MARKET_TICK", "payload": {"stocks": []}},
        ]})
        assert sr.get_event("MARKET_TICK") == {"stocks": []}

    def test_get_event_not_found(self):
        sr = StepResult({"ok": True, "clock": {}, "events": []})
        assert sr.get_event("MARKET_TICK") is None

    def test_get_stock_price(self):
        sr = StepResult({"ok": True, "clock": {}, "events": [
            {"type": "MARKET_TICK", "payload": {
                "stocks": [{"symbol": "AAPL", "close": 185.50}],
            }},
        ]})
        assert sr.get_stock_price("AAPL") == 185.50

    def test_get_stock_price_missing_symbol(self):
        sr = StepResult({"ok": True, "clock": {}, "events": [
            {"type": "MARKET_TICK", "payload": {
                "stocks": [{"symbol": "MSFT", "close": 400.0}],
            }},
        ]})
        assert sr.get_stock_price("AAPL") is None

    def test_get_stock_price_no_tick(self):
        sr = StepResult({"ok": True, "clock": {}, "events": []})
        assert sr.get_stock_price("AAPL") is None
```

**Step 2: Run tests to verify they pass**

Run: `cd /Users/efan404/Codes/research/qfinzero && python -m pytest tests/test_pure_utils.py -v`
Expected: All ~17 tests PASS

**Step 3: Commit**

```bash
git add tests/test_pure_utils.py
git commit -m "test: add pure utility tests for make_opra, ns_to_iso, StepResult"
```

---

### Task 3: UPQ Client Tests

**Files:**
- Create: `tests/test_upq_client.py`

**Context:** UPQClient (in `clients/upq/client.py`) is a synchronous REST client using `requests`. It has:
- `_get(path, params)` → sends GET, parses JSON, raises `UPQError` on 4xx/5xx
- Methods: `health()`, `freshness()`, `stock_daily()`, `stock_minute()`, `option_chain()`, `option_contract()`, `rates()`
- URL pattern: `{base_url}{path}` (no `/v1` prefix, unlike PMB)

**Step 1: Write the test file**

Create `tests/test_upq_client.py`:

```python
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
```

**Step 2: Run tests**

Run: `cd /Users/efan404/Codes/research/qfinzero && python -m pytest tests/test_upq_client.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/test_upq_client.py
git commit -m "test: add UPQ client unit tests with HTTP mocks"
```

---

### Task 4: NPP Client Tests

**Files:**
- Create: `tests/test_npp_client.py`

**Context:** NPPClient (in `clients/npp/client.py`) uses both `_get()` and `_post()`. Key difference from UPQ: most methods use POST with JSON body (not GET with query params). URL prefix is `/npp/`.

**Step 1: Write the test file**

Create `tests/test_npp_client.py`:

```python
"""Tests for NPP client — HTTP-level mocks via responses library."""

import json

import pytest
import responses

from clients.npp.client import NPPClient, NPPError

MOCK_URL = "http://mock-npp:19330"


@pytest.fixture
def client():
    c = NPPClient(MOCK_URL)
    yield c
    c.close()


# ═══════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════


class TestHealth:
    @responses.activate
    def test_health_happy_path(self, client):
        responses.get(f"{MOCK_URL}/npp/health", json={"status": "ok", "version": "1.0"})
        result = client.health()
        assert result["status"] == "ok"

    @responses.activate
    def test_health_error(self, client):
        responses.get(f"{MOCK_URL}/npp/health", json={"message": "down"}, status=500)
        with pytest.raises(NPPError) as exc:
            client.health()
        assert exc.value.status_code == 500


# ═══════════════════════════════════════════════════════════════════
# Query Events
# ═══════════════════════════════════════════════════════════════════


class TestQueryEvents:
    @responses.activate
    def test_happy_path(self, client):
        body = {"server_time_utc": "2025-01-15T14:00:00Z", "events": [], "next_cursor": None}
        responses.post(f"{MOCK_URL}/npp/events/query", json=body)
        result = client.query_events(mode="upcoming")
        assert result["events"] == []

    @responses.activate
    def test_sends_correct_body(self, client):
        responses.post(f"{MOCK_URL}/npp/events/query", json={"events": []})
        client.query_events(
            mode="window",
            start_utc="2025-01-15T00:00:00Z",
            end_utc="2025-01-15T23:59:59Z",
            event_types=["earnings", "breaking_news"],
            tickers=["AAPL"],
            min_importance="high",
            limit=10,
            view="full",
        )
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["mode"] == "window"
        assert req_body["start_utc"] == "2025-01-15T00:00:00Z"
        assert req_body["event_types"] == ["earnings", "breaking_news"]
        assert req_body["tickers"] == ["AAPL"]
        assert req_body["min_importance"] == "high"
        assert req_body["limit"] == 10

    @responses.activate
    def test_optional_params_omitted(self, client):
        responses.post(f"{MOCK_URL}/npp/events/query", json={"events": []})
        client.query_events(mode="upcoming")
        req_body = json.loads(responses.calls[0].request.body)
        assert "start_utc" not in req_body
        assert "end_utc" not in req_body
        assert "event_types" not in req_body
        assert "tickers" not in req_body
        assert "min_importance" not in req_body
        assert "cursor" not in req_body
        assert "now_utc" not in req_body


# ═══════════════════════════════════════════════════════════════════
# Get Event
# ═══════════════════════════════════════════════════════════════════


class TestGetEvent:
    @responses.activate
    def test_happy_path(self, client):
        event = {"event_id": "ev123", "title": "FOMC Meeting"}
        responses.get(f"{MOCK_URL}/npp/events/ev123", json=event)
        result = client.get_event("ev123")
        assert result["event_id"] == "ev123"

    @responses.activate
    def test_not_found(self, client):
        responses.get(f"{MOCK_URL}/npp/events/bad-id", json={"message": "not found"}, status=404)
        with pytest.raises(NPPError) as exc:
            client.get_event("bad-id")
        assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Stream
# ═══════════════════════════════════════════════════════════════════


class TestStream:
    @responses.activate
    def test_happy_path(self, client):
        body = {"server_time_utc": "2025-01-15T14:00:00Z", "events": [{"event_id": "e1"}], "next_cursor": "cur2"}
        responses.post(f"{MOCK_URL}/npp/events/stream", json=body)
        result = client.stream(cursor="cur1")
        assert result["next_cursor"] == "cur2"

    @responses.activate
    def test_body_params(self, client):
        responses.post(f"{MOCK_URL}/npp/events/stream", json={"events": []})
        client.stream(cursor="cur1", event_types=["earnings"], tickers=["NVDA"], limit=10)
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["cursor"] == "cur1"
        assert req_body["event_types"] == ["earnings"]
        assert req_body["tickers"] == ["NVDA"]


# ═══════════════════════════════════════════════════════════════════
# Econ Calendar
# ═══════════════════════════════════════════════════════════════════


class TestEconCalendar:
    @responses.activate
    def test_happy_path(self, client):
        body = {"events": [{"title": "CPI"}]}
        responses.post(f"{MOCK_URL}/npp/calendar/econ", json=body)
        result = client.econ_calendar(start_date="2025-01-01", end_date="2025-01-31")
        assert result["events"][0]["title"] == "CPI"

    @responses.activate
    def test_body_params(self, client):
        responses.post(f"{MOCK_URL}/npp/calendar/econ", json={"events": []})
        client.econ_calendar(
            start_date="2025-01-01", end_date="2025-01-31",
            min_importance="high", limit=5,
        )
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["start_date"] == "2025-01-01"
        assert req_body["min_importance"] == "high"
        assert req_body["limit"] == 5


# ═══════════════════════════════════════════════════════════════════
# Earnings Calendar
# ═══════════════════════════════════════════════════════════════════


class TestEarningsCalendar:
    @responses.activate
    def test_happy_path(self, client):
        body = {"events": [{"title": "AAPL Earnings"}]}
        responses.post(f"{MOCK_URL}/npp/calendar/earnings", json=body)
        result = client.earnings_calendar(tickers=["AAPL"])
        assert len(result["events"]) == 1

    @responses.activate
    def test_body_params(self, client):
        responses.post(f"{MOCK_URL}/npp/calendar/earnings", json={"events": []})
        client.earnings_calendar(
            start_date="2025-01-01", end_date="2025-03-31",
            tickers=["AAPL", "NVDA"], min_importance=3,
        )
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["tickers"] == ["AAPL", "NVDA"]
        assert req_body["min_importance"] == 3


# ═══════════════════════════════════════════════════════════════════
# Next Triggers
# ═══════════════════════════════════════════════════════════════════


class TestNextTriggers:
    @responses.activate
    def test_happy_path(self, client):
        body = {"server_time_utc": "now", "triggers": [{"event_id": "e1"}]}
        responses.post(f"{MOCK_URL}/npp/triggers/next", json=body)
        result = client.next_triggers(tickers=["AAPL"])
        assert len(result["triggers"]) == 1

    @responses.activate
    def test_body_params(self, client):
        responses.post(f"{MOCK_URL}/npp/triggers/next", json={"triggers": []})
        client.next_triggers(tickers=["AAPL"], min_importance="high", horizon_minutes=60, limit=3)
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["tickers"] == ["AAPL"]
        assert req_body["min_importance"] == "high"
        assert req_body["horizon_minutes"] == 60
        assert req_body["limit"] == 3


# ═══════════════════════════════════════════════════════════════════
# News Body
# ═══════════════════════════════════════════════════════════════════


class TestNewsBody:
    @responses.activate
    def test_happy_path(self, client):
        body = {"news_id": "n1", "title": "Breaking news"}
        responses.get(f"{MOCK_URL}/npp/news/n1/body", json=body)
        result = client.news_body("n1")
        assert result["title"] == "Breaking news"


# ═══════════════════════════════════════════════════════════════════
# Search News
# ═══════════════════════════════════════════════════════════════════


class TestSearchNews:
    @responses.activate
    def test_happy_path(self, client):
        body = {"events": [{"title": "NVDA beats"}], "next_cursor": None}
        responses.post(f"{MOCK_URL}/npp/news/search", json=body)
        result = client.search_news(tickers=["NVDA"], keyword="beats")
        assert len(result["events"]) == 1

    @responses.activate
    def test_body_params(self, client):
        responses.post(f"{MOCK_URL}/npp/news/search", json={"events": []})
        client.search_news(
            tickers=["AAPL"],
            start_utc="2025-01-01T00:00:00Z",
            end_utc="2025-01-31T23:59:59Z",
            keyword="earnings",
            publisher="Reuters",
            limit=100,
        )
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["tickers"] == ["AAPL"]
        assert req_body["keyword"] == "earnings"
        assert req_body["publisher"] == "Reuters"
        assert req_body["limit"] == 100


# ═══════════════════════════════════════════════════════════════════
# Timeline
# ═══════════════════════════════════════════════════════════════════


class TestTimeline:
    @responses.activate
    def test_happy_path(self, client):
        body = {"buckets": [{"bucket_start_utc": "2025-01-15T14:00:00Z", "count": 3}]}
        responses.post(f"{MOCK_URL}/npp/timeline", json=body)
        result = client.timeline(tickers=["AAPL"])
        assert result["buckets"][0]["count"] == 3

    @responses.activate
    def test_body_params(self, client):
        responses.post(f"{MOCK_URL}/npp/timeline", json={"buckets": []})
        client.timeline(
            tickers=["AAPL", "NVDA"],
            start_utc="2025-01-15T00:00:00Z",
            end_utc="2025-01-15T23:59:59Z",
            bucket_minutes=30,
        )
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["tickers"] == ["AAPL", "NVDA"]
        assert req_body["bucket_minutes"] == 30


# ═══════════════════════════════════════════════════════════════════
# Error Handling
# ═══════════════════════════════════════════════════════════════════


class TestErrorHandling:
    @responses.activate
    def test_non_json_response(self, client):
        responses.get(f"{MOCK_URL}/npp/health", body="bad gateway", status=502)
        with pytest.raises(NPPError, match="Non-JSON response"):
            client.health()

    @responses.activate
    def test_error_preserves_code(self, client):
        responses.get(
            f"{MOCK_URL}/npp/health",
            json={"message": "rate limited", "code": "RATE_LIMIT"},
            status=429,
        )
        with pytest.raises(NPPError) as exc:
            client.health()
        assert exc.value.code == "RATE_LIMIT"
```

**Step 2: Run tests**

Run: `cd /Users/efan404/Codes/research/qfinzero && python -m pytest tests/test_npp_client.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/test_npp_client.py
git commit -m "test: add NPP client unit tests with HTTP mocks"
```

---

### Task 5: PMB Client Tests

**Files:**
- Create: `tests/test_pmb_client.py`

**Context:** PMBClient (in `clients/pmb/client.py`) differs from UPQ/NPP:
- URL prefix: `/v1` (via `_url()` method)
- `get_positions/orders/trades` extract nested keys (e.g. `data.get("positions", [])`)
- `step()` returns `StepResult` wrapper (not raw dict)
- `export()` has special handling: CSV returns text, JSON returns parsed dict
- `_place_order()` is a shared helper used by buy/sell/buy_option/sell_option

**Step 1: Write the test file**

Create `tests/test_pmb_client.py`:

```python
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
```

**Step 2: Run tests**

Run: `cd /Users/efan404/Codes/research/qfinzero && python -m pytest tests/test_pmb_client.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/test_pmb_client.py
git commit -m "test: add PMB client unit tests with HTTP mocks"
```

---

### Task 6: MCP Tool Layer Tests

**Files:**
- Create: `tests/test_mcp_tools.py`

**Context:** The MCP tools in `mcp/server.py` are thin wrappers. They:
1. Create a client via context manager
2. Call the client method
3. `json.dumps()` the result

Key things to test:
- Parameter forwarding from tool args to client methods
- `json.dumps()` serialization of the return value
- `npp_query_events` has date-to-UTC conversion logic (`start_date` → `start_utc`)
- `pmb_create_session` builds `universe` dict from `stock_universe`/`option_universe`
- `pmb_step_session` accesses `result._raw` (not the dict directly)

**Step 1: Write the test file**

Create `tests/test_mcp_tools.py`:

```python
"""Tests for MCP tool functions in mcp/server.py.

These test that the tool layer correctly:
1. Forwards parameters to client methods
2. Serializes return values as JSON strings
3. Handles special logic (date conversion, universe building)
"""

import json
import os
import sys

import pytest
import responses

# Ensure project root is on path (same as server.py does)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.conftest import MOCK_UPQ_URL, MOCK_NPP_URL, MOCK_PMB_URL


@pytest.fixture(autouse=True)
def _patch_urls(monkeypatch):
    """Ensure all tools use mock URLs."""
    monkeypatch.setenv("QFINZERO_UPQ_URL", MOCK_UPQ_URL)
    monkeypatch.setenv("QFINZERO_NPP_URL", MOCK_NPP_URL)
    monkeypatch.setenv("QFINZERO_PMB_URL", MOCK_PMB_URL)
    # Re-import to pick up patched env vars
    import mcp.server as srv
    monkeypatch.setattr(srv, "UPQ_URL", MOCK_UPQ_URL)
    monkeypatch.setattr(srv, "NPP_URL", MOCK_NPP_URL)
    monkeypatch.setattr(srv, "PMB_URL", MOCK_PMB_URL)


# Lazy import so env patches take effect
def _srv():
    import mcp.server as srv
    return srv


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
        ns = 1705326600 * 1_000_000_000
        result = _srv().upq_ns_to_iso(ns)
        assert "2024-01-15T14:30:00" in result


# ═══════════════════════════════════════════════════════════════════
# NPP Tools
# ═══════════════════════════════════════════════════════════════════


class TestNPPTools:
    @responses.activate
    def test_npp_health(self):
        responses.get(f"{MOCK_NPP_URL}/npp/health", json={"status": "ok"})
        result = _srv().npp_health()
        assert json.loads(result)["status"] == "ok"

    @responses.activate
    def test_npp_query_events(self):
        body = {"events": [{"event_id": "e1"}]}
        responses.post(f"{MOCK_NPP_URL}/npp/events/query", json=body)
        result = _srv().npp_query_events(mode="upcoming")
        assert len(json.loads(result)["events"]) == 1

    @responses.activate
    def test_npp_query_events_date_conversion(self):
        """start_date/end_date should be converted to start_utc/end_utc."""
        responses.post(f"{MOCK_NPP_URL}/npp/events/query", json={"events": []})
        _srv().npp_query_events(
            mode="window",
            start_date="2025-01-15",
            end_date="2025-01-16",
        )
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["start_utc"] == "2025-01-15T00:00:00+00:00"
        assert req_body["end_utc"] == "2025-01-16T23:59:59+00:00"

    @responses.activate
    def test_npp_query_events_start_utc_takes_precedence(self):
        """If start_utc is provided, start_date should not override it."""
        responses.post(f"{MOCK_NPP_URL}/npp/events/query", json={"events": []})
        _srv().npp_query_events(
            mode="window",
            start_utc="2025-01-15T10:00:00Z",
            start_date="2025-01-15",
        )
        req_body = json.loads(responses.calls[0].request.body)
        assert req_body["start_utc"] == "2025-01-15T10:00:00Z"

    @responses.activate
    def test_npp_get_event(self):
        responses.get(f"{MOCK_NPP_URL}/npp/events/ev1", json={"event_id": "ev1"})
        result = _srv().npp_get_event("ev1")
        assert json.loads(result)["event_id"] == "ev1"

    @responses.activate
    def test_npp_stream_events(self):
        responses.post(f"{MOCK_NPP_URL}/npp/events/stream", json={"events": []})
        result = _srv().npp_stream_events(cursor="c1")
        assert json.loads(result)["events"] == []

    @responses.activate
    def test_npp_econ_calendar(self):
        responses.post(f"{MOCK_NPP_URL}/npp/calendar/econ", json={"events": []})
        result = _srv().npp_econ_calendar(start_date="2025-01-01")
        assert json.loads(result)["events"] == []

    @responses.activate
    def test_npp_earnings_calendar(self):
        responses.post(f"{MOCK_NPP_URL}/npp/calendar/earnings", json={"events": []})
        result = _srv().npp_earnings_calendar(tickers=["AAPL"])
        assert json.loads(result)["events"] == []

    @responses.activate
    def test_npp_next_triggers(self):
        responses.post(f"{MOCK_NPP_URL}/npp/triggers/next", json={"triggers": []})
        result = _srv().npp_next_triggers(tickers=["AAPL"])
        assert json.loads(result)["triggers"] == []

    @responses.activate
    def test_npp_news_body(self):
        responses.get(f"{MOCK_NPP_URL}/npp/news/n1/body", json={"title": "News"})
        result = _srv().npp_news_body("n1")
        assert json.loads(result)["title"] == "News"

    @responses.activate
    def test_npp_search_news(self):
        responses.post(f"{MOCK_NPP_URL}/npp/news/search", json={"events": []})
        result = _srv().npp_search_news(keyword="earnings")
        assert json.loads(result)["events"] == []

    @responses.activate
    def test_npp_timeline(self):
        responses.post(f"{MOCK_NPP_URL}/npp/timeline", json={"buckets": []})
        result = _srv().npp_timeline(tickers=["AAPL"])
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
        """No stock_universe/option_universe → empty universe."""
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
```

**Step 2: Run tests**

Run: `cd /Users/efan404/Codes/research/qfinzero && python -m pytest tests/test_mcp_tools.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/test_mcp_tools.py
git commit -m "test: add MCP tool layer tests with HTTP mocks"
```

---

### Task 7: Run Full Suite and Final Commit

**Step 1: Run entire test suite**

Run: `cd /Users/efan404/Codes/research/qfinzero && python -m pytest tests/ -v --tb=short`
Expected: ~117 tests all PASS, 0 failures

**Step 2: Verify no regressions in existing tests**

Run: `cd /Users/efan404/Codes/research/qfinzero && python -m pytest -v --tb=short`
Expected: All tests pass (including existing `infra/playground/test_agent.py`)

**Step 3: Final summary commit (if any fixups needed)**

No commit needed if all prior tasks committed cleanly.
