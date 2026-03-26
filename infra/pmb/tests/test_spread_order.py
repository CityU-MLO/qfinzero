"""Tests for SpreadOrderSpec model."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.order import SpreadOrderSpec, OrderSpec
from models.instrument import Instrument
from models.enums import Side, OrderType, InstrumentType


def test_spread_order_spec_has_two_legs():
    leg1 = OrderSpec(
        instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
        side=Side.BUY, order_type=OrderType.MARKET, qty=1,
    )
    leg2 = OrderSpec(
        instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00380000"),
        side=Side.SELL, order_type=OrderType.MARKET, qty=1,
    )
    spread = SpreadOrderSpec(legs=[leg1, leg2], spread_type="PUT_DEBIT_SPREAD")
    assert len(spread.legs) == 2
    assert spread.spread_type == "PUT_DEBIT_SPREAD"
    assert spread.max_loss_per_unit() == 10.0  # $390 - $380 = $10 width


def test_spread_order_spec_validates_same_underlying():
    leg1 = OrderSpec(
        instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
        side=Side.BUY, order_type=OrderType.MARKET, qty=1,
    )
    leg2 = OrderSpec(
        instrument=Instrument(type=InstrumentType.OPTION, contract="O:NVDA240119P00130000"),
        side=Side.SELL, order_type=OrderType.MARKET, qty=1,
    )
    spread = SpreadOrderSpec(legs=[leg1, leg2], spread_type="PUT_DEBIT_SPREAD")
    err = spread.validate_spread()
    assert err is not None
    assert "underlying" in err.lower()


def test_spread_order_spec_validates_leg_count():
    leg1 = OrderSpec(
        instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
        side=Side.BUY, order_type=OrderType.MARKET, qty=1,
    )
    spread = SpreadOrderSpec(legs=[leg1], spread_type="PUT_DEBIT_SPREAD")
    err = spread.validate_spread()
    assert err is not None
    assert "2 legs" in err.lower()


def test_spread_order_spec_same_underlying_passes():
    leg1 = OrderSpec(
        instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
        side=Side.BUY, order_type=OrderType.MARKET, qty=1,
    )
    leg2 = OrderSpec(
        instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00380000"),
        side=Side.SELL, order_type=OrderType.MARKET, qty=1,
    )
    spread = SpreadOrderSpec(legs=[leg1, leg2], spread_type="PUT_DEBIT_SPREAD")
    assert spread.validate_spread() is None


def test_create_order_request_has_spread_id():
    from models.order import CreateOrderRequest
    req = CreateOrderRequest(
        session_id="s1",
        account_id="a1",
        client_order_id="test",
        order=OrderSpec(
            instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
            side=Side.BUY, order_type=OrderType.MARKET, qty=1,
        ),
        spread_id="spread_001",
    )
    assert req.spread_id == "spread_001"


def test_create_order_request_spread_id_optional():
    from models.order import CreateOrderRequest
    req = CreateOrderRequest(
        session_id="s1",
        account_id="a1",
        order=OrderSpec(
            instrument=Instrument(type=InstrumentType.OPTION, contract="O:QQQ240119P00390000"),
            side=Side.BUY, order_type=OrderType.MARKET, qty=1,
        ),
    )
    assert req.spread_id is None
