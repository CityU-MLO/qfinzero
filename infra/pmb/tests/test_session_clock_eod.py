"""Unit tests for SessionClock.is_last_bar_of_date."""
from domain.session_clock import SessionClock, iso_to_ns
from models.enums import Frequency


def _ts(*iso_times: str) -> list[int]:
    return [iso_to_ns(t) for t in iso_times]


# ---------------------------------------------------------------------------
# DAILY session — always EOD
# ---------------------------------------------------------------------------

def test_daily_single_bar_is_eod():
    ts = _ts("2025-01-17T00:00:00+00:00")
    clock = SessionClock(ts, Frequency.DAILY, "2025-01-17T23:59:59+00:00")
    assert clock.is_last_bar_of_date(ts[0]) is True


def test_daily_first_of_two_bars_is_eod():
    """Daily bars are each their own day — every bar is EOD for that date."""
    ts = _ts("2025-01-17T00:00:00+00:00", "2025-01-18T00:00:00+00:00")
    clock = SessionClock(ts, Frequency.DAILY, "2025-01-18T23:59:59+00:00")
    assert clock.is_last_bar_of_date(ts[0]) is True
    assert clock.is_last_bar_of_date(ts[1]) is True


# ---------------------------------------------------------------------------
# MINUTE session — only last bar of each date is EOD
# ---------------------------------------------------------------------------

def test_minute_first_bar_of_day_not_eod():
    ts = _ts(
        "2025-01-17T14:31:00+00:00",  # 09:31 ET — first bar
        "2025-01-17T14:32:00+00:00",
        "2025-01-17T20:59:00+00:00",  # 15:59 ET — last bar of the day
    )
    clock = SessionClock(ts, Frequency.MINUTE, "2025-01-17T21:00:00+00:00")
    assert clock.is_last_bar_of_date(ts[0]) is False
    assert clock.is_last_bar_of_date(ts[1]) is False


def test_minute_last_bar_of_day_is_eod():
    ts = _ts(
        "2025-01-17T14:31:00+00:00",
        "2025-01-17T20:59:00+00:00",  # last bar on 2025-01-17
        "2025-01-18T14:31:00+00:00",  # next day
    )
    clock = SessionClock(ts, Frequency.MINUTE, "2025-01-18T21:00:00+00:00")
    assert clock.is_last_bar_of_date(ts[1]) is True


def test_minute_last_bar_of_session_is_eod():
    """The very last bar in the session is always EOD regardless of time."""
    ts = _ts(
        "2025-01-17T14:31:00+00:00",
        "2025-01-17T15:00:00+00:00",  # last bar — no next bar exists
    )
    clock = SessionClock(ts, Frequency.MINUTE, "2025-01-17T21:00:00+00:00")
    assert clock.is_last_bar_of_date(ts[1]) is True


def test_minute_multi_day_eod_gates():
    """Verify EOD detection across multiple days in one session."""
    ts = _ts(
        "2025-01-17T14:31:00+00:00",  # day 1, bar 1
        "2025-01-17T20:59:00+00:00",  # day 1, last bar
        "2025-01-18T14:31:00+00:00",  # day 2, bar 1
        "2025-01-18T20:59:00+00:00",  # day 2, last bar
    )
    clock = SessionClock(ts, Frequency.MINUTE, "2025-01-18T21:00:00+00:00")
    assert clock.is_last_bar_of_date(ts[0]) is False
    assert clock.is_last_bar_of_date(ts[1]) is True
    assert clock.is_last_bar_of_date(ts[2]) is False
    assert clock.is_last_bar_of_date(ts[3]) is True
