import pytest
from domain.option_lifecycle import parse_opra_expiry, check_option_expiries, ExpiryAction
from models.position import Position
from models.enums import InstrumentType, Side


def test_parse_nvda_call():
    assert parse_opra_expiry("O:NVDA250117C00136000") == "2025-01-17"


def test_parse_spx_put():
    assert parse_opra_expiry("O:SPX260320P05800000") == "2026-03-20"


def test_parse_single_letter_symbol():
    assert parse_opra_expiry("O:A251231C00050000") == "2025-12-31"


def test_parse_invalid_returns_none():
    assert parse_opra_expiry("STOCK:NVDA") is None
    assert parse_opra_expiry("O:BAD") is None


def test_parse_impossible_date_returns_none():
    # Month 13 passes regex but is not a valid date
    assert parse_opra_expiry("O:NVDA251332C00136000") is None


def test_parse_lowercase_ticker_returns_none():
    assert parse_opra_expiry("O:nvda250117C00136000") is None


def test_parse_empty_string_returns_none():
    assert parse_opra_expiry("") is None


def _make_option_pos(contract: str, qty: int) -> Position:
    return Position(
        instrument_id=f"OPTION:{contract}",
        type=InstrumentType.OPTION,
        qty=qty,
        avg_price=3.50,
        mark_price=0.10,
    )


def _make_stock_pos(symbol: str, qty: int) -> Position:
    return Position(
        instrument_id=f"STOCK:{symbol}",
        type=InstrumentType.STOCK,
        qty=qty,
        avg_price=130.0,
        mark_price=140.0,
    )


def test_short_call_otm_expiry():
    contract = "O:NVDA250117C00150000"  # strike 150, expires 2025-01-17
    positions = {
        f"OPTION:{contract}": _make_option_pos(contract, -1),
        "STOCK:NVDA": _make_stock_pos("NVDA", 100),
    }
    # underlying = 140 < 150 strike → OTM
    actions = check_option_expiries(positions, "2025-01-17", {"NVDA": 140.0})
    assert len(actions) == 1
    a = actions[0]
    assert a.is_itm is False
    assert a.intrinsic_value == 0.0
    assert a.stock_side is None


def test_short_call_itm_expiry():
    contract = "O:NVDA250117C00136000"  # strike 136, expires 2025-01-17
    positions = {
        f"OPTION:{contract}": _make_option_pos(contract, -2),
        "STOCK:NVDA": _make_stock_pos("NVDA", 200),
    }
    # underlying = 145 > 136 strike → ITM
    actions = check_option_expiries(positions, "2025-01-17", {"NVDA": 145.0})
    assert len(actions) == 1
    a = actions[0]
    assert a.is_itm is True
    assert a.intrinsic_value == pytest.approx(9.0)   # 145 - 136
    assert a.stock_side == Side.SELL
    assert a.strike == 136.0
    assert a.stock_qty == 200   # 2 contracts × 100


def test_short_put_itm_expiry():
    contract = "O:NVDA250117P00130000"  # strike 130, expires 2025-01-17
    positions = {
        f"OPTION:{contract}": _make_option_pos(contract, -1),
    }
    # underlying = 125 < 130 strike → ITM put
    actions = check_option_expiries(positions, "2025-01-17", {"NVDA": 125.0})
    assert len(actions) == 1
    a = actions[0]
    assert a.is_itm is True
    assert a.intrinsic_value == pytest.approx(5.0)   # 130 - 125
    assert a.stock_side == Side.BUY
    assert a.strike == 130.0
    assert a.stock_qty == 100


def test_not_expired_yet():
    contract = "O:NVDA250120C00136000"  # expires 2025-01-20
    positions = {f"OPTION:{contract}": _make_option_pos(contract, -1)}
    actions = check_option_expiries(positions, "2025-01-17", {"NVDA": 145.0})
    assert actions == []


def test_long_call_otm_expiry():
    contract = "O:NVDA250117C00150000"  # strike 150
    positions = {f"OPTION:{contract}": _make_option_pos(contract, 1)}
    actions = check_option_expiries(positions, "2025-01-17", {"NVDA": 140.0})
    assert len(actions) == 1
    a = actions[0]
    assert a.is_itm is False
    assert a.stock_side is None   # long option: no stock transaction


def test_missing_underlying_price():
    contract = "O:NVDA250117C00136000"
    positions = {f"OPTION:{contract}": _make_option_pos(contract, -1)}
    # No NVDA in underlying_prices
    actions = check_option_expiries(positions, "2025-01-17", {})
    assert len(actions) == 1
    a = actions[0]
    # Can't determine ITM/OTM → treat as OTM, no assignment
    assert a.is_itm is False
    assert a.stock_side is None


def test_long_call_itm_no_assignment():
    """Long call expires ITM: recognized as ITM but no stock transaction (no assignment for longs)."""
    contract = "O:NVDA250117C00136000"  # strike 136
    positions = {f"OPTION:{contract}": _make_option_pos(contract, 1)}  # qty=+1, long
    # underlying = 145 > 136 strike → ITM
    actions = check_option_expiries(positions, "2025-01-17", {"NVDA": 145.0})
    assert len(actions) == 1
    a = actions[0]
    assert a.is_itm is True
    assert a.intrinsic_value == pytest.approx(9.0)  # 145 - 136
    assert a.stock_side is None  # no assignment for long positions
