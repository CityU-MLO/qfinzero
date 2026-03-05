from domain.option_lifecycle import parse_opra_expiry


def test_parse_nvda_call():
    assert parse_opra_expiry("O:NVDA250117C00136000") == "2025-01-17"


def test_parse_spx_put():
    assert parse_opra_expiry("O:SPX260320P05800000") == "2026-03-20"


def test_parse_single_letter_symbol():
    assert parse_opra_expiry("O:A251231C00050000") == "2025-12-31"


def test_parse_invalid_returns_none():
    assert parse_opra_expiry("STOCK:NVDA") is None
    assert parse_opra_expiry("O:BAD") is None
