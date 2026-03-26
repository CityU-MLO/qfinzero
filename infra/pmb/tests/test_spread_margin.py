"""Tests for spread margin calculation."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.margin_engine import MarginEngine
from models.account import MarginConfig
from models.enums import Side, InstrumentType


def test_spread_margin_uses_width_not_individual():
    engine = MarginEngine(MarginConfig())

    # Put spread: sell 390 put, buy 380 put → width = $10 → max loss = $1000
    spread_margin = engine.margin_for_spread(
        spread_width=10.0,
        qty=1,
        multiplier=100,
    )
    assert spread_margin == 1000.0  # $10 × 100 × 1

    # Compare: individual margin for selling a $390 put would be much higher
    # sell 390 put: 0.20 × 1 × 390.0 × 100 = $7,800
    individual = engine.initial_margin_for_order(
        Side.SELL, InstrumentType.OPTION, 1, 390.0
    )
    assert spread_margin < individual


def test_spread_margin_scales_with_qty():
    engine = MarginEngine(MarginConfig())

    margin_1 = engine.margin_for_spread(spread_width=10.0, qty=1, multiplier=100)
    margin_5 = engine.margin_for_spread(spread_width=10.0, qty=5, multiplier=100)
    assert margin_5 == margin_1 * 5


def test_spread_margin_zero_width():
    engine = MarginEngine(MarginConfig())
    margin = engine.margin_for_spread(spread_width=0.0, qty=1, multiplier=100)
    assert margin == 0.0
