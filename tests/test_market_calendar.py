"""NYSE calendar rules against the published 2024-2026 schedules."""

from datetime import date

import pytest

from qfinzero import market_calendar as cal

PUBLISHED = {
    2024: ["2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27", "2024-06-19",
           "2024-07-04", "2024-09-02", "2024-11-28", "2024-12-25"],
    2025: ["2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
           "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25"],
    2026: ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
           "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"],
}


@pytest.mark.parametrize("year", sorted(PUBLISHED))
def test_holidays_match_published_schedule(year):
    assert sorted(d.isoformat() for d in cal.holidays(year)) == PUBLISHED[year]


def test_observance_rules():
    assert date(2021, 12, 31) not in cal.holidays(2021)      # Saturday New Year is not observed
    assert date(2022, 1, 1) not in cal.holidays(2022)
    assert date(2021, 6, 18) not in cal.holidays(2021)       # Juneteenth starts in 2022
    assert date(2022, 6, 20) in cal.holidays(2022)           # Sunday -> Monday
    assert date(2022, 12, 26) in cal.holidays(2022)
    assert date(2012, 10, 29) in cal.holidays(2012)          # Hurricane Sandy


def test_early_closes():
    assert [d for d in cal.trading_days(date(2025, 1, 1), date(2025, 12, 31)) if cal.is_early_close(d)] == [
        date(2025, 7, 3), date(2025, 11, 28), date(2025, 12, 24)]
    assert not cal.is_early_close(date(2026, 7, 3))           # the holiday itself
    assert cal.regular_close(date(2025, 12, 24)) == 13 * 60 and cal.post_close(date(2025, 12, 24)) == 17 * 60


def test_navigation_and_counts():
    assert cal.next_trading_day(date(2025, 4, 17)) == date(2025, 4, 21)
    assert cal.previous_trading_day(date(2025, 1, 21)) == date(2025, 1, 17)
    assert len(cal.trading_days(date(2025, 1, 1), date(2025, 12, 31))) == 250


def test_sample_calendar_agrees():
    from qfinzero.sample.universe import DAYS
    assert DAYS == cal.trading_days(DAYS[0], DAYS[-1])
