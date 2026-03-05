"""Tests for pure utility functions — no HTTP mocking needed."""

import json
import sys
import os
from datetime import datetime, timezone

import pytest

from clients.upq.client import UPQClient
from clients.pmb.client import StepResult

# Allow importing from infra/npp without installing it as a package
_NPP = os.path.join(os.path.dirname(__file__), "..", "infra", "npp")
sys.path.insert(0, os.path.join(_NPP, "services"))
sys.path.insert(0, _NPP)


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
        # 2024-01-15T14:30:00 UTC = 1705329000 seconds
        ns = 1705329000 * 1_000_000_000
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


# ═══════════════════════════════════════════════════════════════════
# NPP data_sources pure builder functions
# ═══════════════════════════════════════════════════════════════════


class TestBuildEarningsSnippet:
    def test_scheduled_snippet_omits_actual_eps_and_revenue(self):
        from data_sources import build_earnings_snippet
        row = {"ticker": "AAPL", "fiscal_period": "Q1", "fiscal_year": "2026",
               "actual_eps": 2.10, "estimated_eps": 2.05, "actual_revenue": 120_000_000}
        snippet = build_earnings_snippet(row, occurred=False)
        assert "2.10" not in snippet
        assert "120" not in snippet

    def test_scheduled_snippet_keeps_estimated_eps(self):
        from data_sources import build_earnings_snippet
        row = {"ticker": "AAPL", "fiscal_period": "Q1", "fiscal_year": "2026",
               "actual_eps": None, "estimated_eps": 2.05, "actual_revenue": None}
        snippet = build_earnings_snippet(row, occurred=False)
        assert "2.05" in snippet

    def test_occurred_snippet_includes_actual_eps(self):
        from data_sources import build_earnings_snippet
        row = {"ticker": "AAPL", "fiscal_period": "Q1", "fiscal_year": "2026",
               "actual_eps": 2.10, "estimated_eps": 2.05, "actual_revenue": 120_000_000}
        snippet = build_earnings_snippet(row, occurred=True)
        assert "EPS 2.1" in snippet
        assert "120,000,000" in snippet

    def test_empty_row_returns_empty_string(self):
        from data_sources import build_earnings_snippet
        assert build_earnings_snippet({}, occurred=False) == ""


class TestBuildEarningsPayload:
    def test_scheduled_payload_nulls_actual_fields(self):
        from data_sources import build_earnings_payload
        row = {"actual_eps": 2.10, "estimated_eps": 2.05, "previous_eps": 1.90,
               "eps_surprise": 0.05, "eps_surprise_percent": 2.4,
               "actual_revenue": 120_000_000, "estimated_revenue": 118_000_000,
               "revenue_surprise": 2_000_000, "revenue_surprise_percent": 1.7,
               "fiscal_period": "Q1", "fiscal_year": "2026", "company_name": "Apple"}
        payload = build_earnings_payload(row, occurred=False)
        assert payload["actual_eps"] is None
        assert payload["previous_eps"] is None
        assert payload["eps_surprise"] is None
        assert payload["eps_surprise_percent"] is None
        assert payload["actual_revenue"] is None
        assert payload["revenue_surprise"] is None
        assert payload["revenue_surprise_percent"] is None

    def test_scheduled_payload_keeps_estimated_fields(self):
        from data_sources import build_earnings_payload
        row = {"actual_eps": 2.10, "estimated_eps": 2.05, "previous_eps": 1.90,
               "eps_surprise": 0.05, "eps_surprise_percent": 2.4,
               "actual_revenue": 120_000_000, "estimated_revenue": 118_000_000,
               "revenue_surprise": 2_000_000, "revenue_surprise_percent": 1.7,
               "fiscal_period": "Q1", "fiscal_year": "2026", "company_name": "Apple"}
        payload = build_earnings_payload(row, occurred=False)
        assert payload["estimated_eps"] == 2.05
        assert payload["estimated_revenue"] == 118_000_000

    def test_occurred_payload_includes_all_actual_fields(self):
        from data_sources import build_earnings_payload
        row = {"actual_eps": 2.10, "estimated_eps": 2.05, "previous_eps": 1.90,
               "eps_surprise": 0.05, "eps_surprise_percent": 2.4,
               "actual_revenue": 120_000_000, "estimated_revenue": 118_000_000,
               "revenue_surprise": 2_000_000, "revenue_surprise_percent": 1.7,
               "fiscal_period": "Q1", "fiscal_year": "2026", "company_name": "Apple"}
        payload = build_earnings_payload(row, occurred=True)
        assert payload["actual_eps"] == 2.10
        assert payload["eps_surprise"] == 0.05
        assert payload["actual_revenue"] == 120_000_000


class TestBuildEconSnippet:
    def test_scheduled_snippet_omits_actual_and_previous(self):
        from data_sources import build_econ_snippet
        row = {"actual": "3.2%", "consensus": "3.0%", "previous": "3.1%"}
        snippet = build_econ_snippet(row, occurred=False)
        assert "3.2%" not in snippet
        assert "Previous" not in snippet

    def test_scheduled_snippet_keeps_consensus(self):
        from data_sources import build_econ_snippet
        row = {"actual": "3.2%", "consensus": "3.0%", "previous": "3.1%"}
        snippet = build_econ_snippet(row, occurred=False)
        assert "3.0%" in snippet

    def test_occurred_snippet_includes_actual(self):
        from data_sources import build_econ_snippet
        row = {"actual": "3.2%", "consensus": "3.0%", "previous": "3.1%"}
        snippet = build_econ_snippet(row, occurred=True)
        assert "3.2%" in snippet
        assert "3.1%" in snippet


class TestBuildEconPayload:
    def test_scheduled_payload_nulls_actual_and_previous(self):
        from data_sources import build_econ_payload
        row = {"actual": "3.2%", "consensus": "3.0%", "previous": "3.1%",
               "description": "CPI data"}
        payload = build_econ_payload(row, occurred=False)
        assert payload["actual"] is None
        assert payload["previous"] is None

    def test_scheduled_payload_keeps_consensus_and_description(self):
        from data_sources import build_econ_payload
        row = {"actual": "3.2%", "consensus": "3.0%", "previous": "3.1%",
               "description": "CPI data"}
        payload = build_econ_payload(row, occurred=False)
        assert payload["consensus"] == "3.0%"
        assert payload["description"] == "CPI data"

    def test_occurred_payload_includes_actual_and_previous(self):
        from data_sources import build_econ_payload
        row = {"actual": "3.2%", "consensus": "3.0%", "previous": "3.1%",
               "description": "CPI data"}
        payload = build_econ_payload(row, occurred=True)
        assert payload["actual"] == "3.2%"
        assert payload["previous"] == "3.1%"
