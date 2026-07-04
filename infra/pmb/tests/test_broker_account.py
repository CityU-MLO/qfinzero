"""Unit tests for the day-gated broker account service.

These exercise AccountService directly (no HTTP server needed).
"""

import pytest

from models.enums import Market, AccountStatus, Side, MARKET_PROFILE
from models.account import CreateAccountRequest
from services.account_service import (
    AccountService,
    FrozenAccountError,
    AccountClosedError,
)


@pytest.fixture
def svc():
    return AccountService()


def mk(svc, market=Market.US, cash=100_000.0, open_date="2024-01-02"):
    return svc.create_account(
        CreateAccountRequest(market=market, initial_cash=cash, open_date=open_date)
    )


# ── account ids ────────────────────────────────────────────────────────


def test_account_id_is_unique_10_digits(svc):
    ids = {mk(svc).account_id for _ in range(200)}
    assert len(ids) == 200
    assert all(len(i) == 10 and i.isdigit() for i in ids)


@pytest.mark.parametrize("market", [Market.US, Market.CN, Market.HK])
def test_leading_digit_encodes_market(svc, market):
    acct = mk(svc, market=market)
    assert acct.account_id[0] == MARKET_PROFILE[market]["lead_digit"]


def test_market_sets_currency_and_timezone(svc):
    cn = mk(svc, market=Market.CN)
    assert cn.base_currency == "CNY"
    assert cn.timezone == "Asia/Shanghai"
    hk = mk(svc, market=Market.HK)
    assert hk.base_currency == "HKD"


# ── open date handling ─────────────────────────────────────────────────


def test_open_date_alias_and_back_compat(svc):
    # start_date still accepted and mirrored onto open_date
    a = svc.create_account(CreateAccountRequest(initial_cash=1000, start_date="2025-03-10"))
    assert a.open_date == "2025-03-10"
    assert a.start_date == "2025-03-10"
    assert a.current_date == "2025-03-10"


def test_default_open_date_when_omitted(svc):
    a = svc.create_account(CreateAccountRequest(initial_cash=1000))
    assert a.open_date  # non-empty default
    assert a.current_date == a.open_date


# ── initial status ─────────────────────────────────────────────────────


def test_initial_status(svc):
    acct = mk(svc, cash=50_000.0)
    st = svc.status_view(acct.account_id)
    assert st["status"] == "ACTIVE"
    assert st["can_trade"] is True
    assert st["trading_day"] == 1
    assert st["equity"] == 50_000.0
    assert st["cash"] == 50_000.0
    assert st["cash_available"] == 50_000.0  # session-snapshot alias preserved
    assert st["num_positions"] == 0


# ── trading ────────────────────────────────────────────────────────────


def test_buy_then_sell_realizes_pnl(svc):
    acct = mk(svc, cash=100_000.0)
    aid = acct.account_id
    svc.trade(aid, "AAPL", Side.BUY, 100, 100.0)
    st = svc.status_view(aid)
    assert st["cash"] == 90_000.0
    assert st["num_positions"] == 1
    assert st["positions"][0]["qty"] == 100

    fill = svc.trade(aid, "AAPL", Side.SELL, 100, 110.0)
    assert fill.realized_pnl == pytest.approx(1000.0)
    st = svc.status_view(aid)
    assert st["realized_pnl"] == pytest.approx(1000.0)
    assert st["num_positions"] == 0
    assert st["cash"] == pytest.approx(101_000.0)


def test_partial_sell_keeps_position(svc):
    acct = mk(svc)
    aid = acct.account_id
    svc.trade(aid, "MSFT", Side.BUY, 100, 50.0)
    svc.trade(aid, "MSFT", Side.SELL, 40, 60.0)
    st = svc.status_view(aid)
    assert st["positions"][0]["qty"] == 60
    assert st["realized_pnl"] == pytest.approx(400.0)  # 40 * (60-50)


def test_trade_rejects_bad_inputs(svc):
    aid = mk(svc).account_id
    with pytest.raises(ValueError):
        svc.trade(aid, "AAPL", Side.BUY, 0, 100.0)
    with pytest.raises(ValueError):
        svc.trade(aid, "AAPL", Side.BUY, 10, 0.0)


def test_trade_unknown_account_raises(svc):
    with pytest.raises(KeyError):
        svc.trade("9999999999", "AAPL", Side.BUY, 1, 1.0)


# ── day gating: freeze until next day ──────────────────────────────────


def test_end_day_freezes_and_records_history(svc):
    acct = mk(svc, cash=100_000.0)
    aid = acct.account_id
    svc.trade(aid, "AAPL", Side.BUY, 100, 100.0)
    svc.mark_prices(aid, {"AAPL": 105.0})

    rec = svc.end_day(aid)
    assert rec.trading_day == 1
    assert rec.num_trades == 1
    assert rec.closing_equity == pytest.approx(100_500.0)  # 90k cash + 100*105

    st = svc.status_view(aid)
    assert st["status"] == "FROZEN"
    assert st["frozen"] is True
    assert st["history_days"] == 1


def test_frozen_account_rejects_trades(svc):
    aid = mk(svc).account_id
    svc.end_day(aid)
    with pytest.raises(FrozenAccountError):
        svc.trade(aid, "AAPL", Side.BUY, 1, 100.0)


def test_end_day_is_idempotent(svc):
    aid = mk(svc).account_id
    r1 = svc.end_day(aid)
    r2 = svc.end_day(aid)
    assert r1.trading_day == r2.trading_day
    assert len(svc.get_account(aid).history) == 1


def test_next_day_unfreezes_and_advances(svc):
    acct = mk(svc, open_date="2024-01-02")  # Tuesday
    aid = acct.account_id
    svc.trade(aid, "AAPL", Side.BUY, 100, 100.0)
    svc.mark_prices(aid, {"AAPL": 105.0})
    svc.end_day(aid)

    after = svc.next_day(aid)
    assert after.status == AccountStatus.ACTIVE
    assert after.trading_day == 2
    assert after.current_date == "2024-01-03"
    # opening equity for the new day equals carried equity
    assert after.day_opening_equity == pytest.approx(100_500.0)
    # trading allowed again
    svc.trade(aid, "AAPL", Side.SELL, 50, 106.0)


def test_next_day_auto_closes_open_day(svc):
    aid = mk(svc).account_id
    svc.trade(aid, "AAPL", Side.BUY, 10, 10.0)
    # call next_day without end_day → should auto-record the day first
    svc.next_day(aid)
    assert len(svc.get_account(aid).history) == 1
    assert svc.status_view(aid)["trading_day"] == 2


def test_next_day_skips_weekend(svc):
    aid = mk(svc, open_date="2024-01-05").account_id  # Friday
    svc.next_day(aid)
    assert svc.status_view(aid)["current_date"] == "2024-01-08"  # Monday


def test_multi_day_history_steps(svc):
    aid = mk(svc, cash=10_000.0, open_date="2024-01-02").account_id
    prices = [100.0, 101.0, 99.0]
    for i, px in enumerate(prices):
        svc.trade(aid, "SPY", Side.BUY, 1, px)
        svc.next_day(aid)
    days = svc.history_view(aid)
    assert len(days) == 3
    assert [d["trading_day"] for d in days] == [1, 2, 3]
    assert [d["date"] for d in days] == ["2024-01-02", "2024-01-03", "2024-01-04"]


# ── closing ────────────────────────────────────────────────────────────


def test_close_account_blocks_everything(svc):
    aid = mk(svc).account_id
    svc.close_account(aid)
    assert svc.status_view(aid)["status"] == "CLOSED"
    with pytest.raises(AccountClosedError):
        svc.trade(aid, "AAPL", Side.BUY, 1, 1.0)
    with pytest.raises(AccountClosedError):
        svc.next_day(aid)
