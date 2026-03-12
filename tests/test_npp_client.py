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
