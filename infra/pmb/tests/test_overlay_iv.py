"""Tests for IV integration in overlay helpers and LLM agent prompt."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock


# --- Test 1: query_option_chain passes include_greeks ---

def test_query_option_chain_sends_include_greeks():
    """query_option_chain should send include_greeks=true to UPQ."""
    from demos.overlay_helpers import query_option_chain

    with patch("demos.overlay_helpers.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"ticker": "O:QQQ250117C00500000", "strike": 500.0, "close": 3.50, "iv": 0.22}
        ]
        mock_get.return_value = mock_resp

        result = query_option_chain(
            underlying="QQQ", date="2025-01-06", option_type="C",
            strike_min=495.0, strike_max=510.0,
        )

        # Verify include_greeks was sent in the request params
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["include_greeks"] == "true", (
            f"Expected include_greeks='true' in params, got: {params}"
        )


# --- Test 2: build_user_prompt shows IV when present ---

def test_build_user_prompt_includes_iv():
    """build_user_prompt should display IV for contracts that have it."""
    from demos.overlay_llm_agent import build_user_prompt

    chain = [
        {"ticker": "O:QQQ250117C00500000", "strike": 500.0, "close": 3.50,
         "expiry": "2025-01-17", "iv": 0.22},
        {"ticker": "O:QQQ250124C00505000", "strike": 505.0, "close": 2.10,
         "expiry": "2025-01-24", "iv": 0.18},
    ]

    prompt = build_user_prompt(
        strategy="profit", underlying="QQQ", date="2025-01-06",
        price=498.0, cash=100000.0, equity=5000000.0,
        active_options=[], chain=chain,
    )

    assert "iv=0.22" in prompt or "IV=0.22" in prompt or "iv=22.0%" in prompt, (
        f"Expected IV value for first contract in prompt, got:\n{prompt}"
    )
    assert "iv=0.18" in prompt or "IV=0.18" in prompt or "iv=18.0%" in prompt, (
        f"Expected IV value for second contract in prompt, got:\n{prompt}"
    )


# --- Test 3: build_user_prompt handles missing IV gracefully ---

def test_build_user_prompt_handles_missing_iv():
    """build_user_prompt should not crash when IV is None or absent."""
    from demos.overlay_llm_agent import build_user_prompt

    chain = [
        {"ticker": "O:QQQ250117C00500000", "strike": 500.0, "close": 3.50,
         "expiry": "2025-01-17", "iv": None},
        {"ticker": "O:QQQ250124C00505000", "strike": 505.0, "close": 2.10,
         "expiry": "2025-01-24"},  # no iv key at all
    ]

    prompt = build_user_prompt(
        strategy="profit", underlying="QQQ", date="2025-01-06",
        price=498.0, cash=100000.0, equity=5000000.0,
        active_options=[], chain=chain,
    )

    # Should not crash and should still contain the contract info
    assert "500.00" in prompt
    assert "505.00" in prompt
