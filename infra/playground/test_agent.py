"""Tests for agent system prompt timezone handling."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from agent import build_system_prompt


ET = ZoneInfo("America/New_York")


class TestSystemPromptUTC:
    def test_system_prompt_contains_utc_instruction(self):
        prompt = build_system_prompt("2025-01-15T14:00:00.000Z")
        assert "All tool datetime parameters use UTC" in prompt
        assert "Convert user-mentioned times" in prompt

    def test_system_prompt_contains_utc_timestamp(self):
        prompt = build_system_prompt("2025-01-15T14:00:00.000Z")
        assert "2025-01-15T14:00:00Z" in prompt


class TestETDisplay:
    def test_et_display_est_in_winter(self):
        """January should display EST."""
        prompt = build_system_prompt("2025-01-15T14:00:00.000Z")
        assert "EST" in prompt
        # 14:00 UTC = 09:00 EST
        assert "09:00" in prompt

    def test_et_display_edt_in_summer(self):
        """July should display EDT."""
        prompt = build_system_prompt("2025-07-15T14:00:00.000Z")
        assert "EDT" in prompt
        # 14:00 UTC = 10:00 EDT
        assert "10:00" in prompt

    def test_dst_transition_march(self):
        """2025 DST spring-forward: March 9. March 10 should be EDT."""
        # March 10, 2025: first Monday after spring forward
        prompt = build_system_prompt("2025-03-10T14:00:00.000Z")
        assert "EDT" in prompt
        # 14:00 UTC = 10:00 EDT
        assert "10:00" in prompt

    def test_dst_transition_march_before(self):
        """March 8, 2025 (before spring forward) should be EST."""
        prompt = build_system_prompt("2025-03-08T14:00:00.000Z")
        assert "EST" in prompt
        # 14:00 UTC = 09:00 EST
        assert "09:00" in prompt

    def test_dst_transition_november(self):
        """2025 DST fall-back: November 2. November 3 should be EST."""
        # November 3, 2025: first Monday after fall back
        prompt = build_system_prompt("2025-11-03T14:00:00.000Z")
        assert "EST" in prompt
        # 14:00 UTC = 09:00 EST
        assert "09:00" in prompt

    def test_dst_transition_november_before(self):
        """November 1, 2025 (before fall back) should be EDT."""
        prompt = build_system_prompt("2025-11-01T14:00:00.000Z")
        assert "EDT" in prompt
        # 14:00 UTC = 10:00 EDT
        assert "10:00" in prompt
