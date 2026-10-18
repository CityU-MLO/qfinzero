"""NYSE trading calendar: holidays, special closures and early closes.

Rule based, so it covers any year without a data file:

* New Year's Day, MLK Day, Washington's Birthday, Good Friday, Memorial Day,
  Juneteenth (from 2022), Independence Day, Labor Day, Thanksgiving and
  Christmas, moved to Friday when on a Saturday and to Monday when on a
  Sunday. New Year's Day on a Saturday is not observed (NYSE Rule 7.2).
* Unscheduled closures since 2001 (:data:`SPECIAL_CLOSURES`).
* Early closes at 13:00 ET (extended hours then end at 17:00): July 3, the
  day after Thanksgiving and December 24, when they are trading days.

    >>> from datetime import date
    >>> is_trading_day(date(2025, 1, 9))       # national day of mourning
    False
    >>> next_trading_day(date(2025, 4, 17))    # Good Friday follows
    datetime.date(2025, 4, 21)
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

SPECIAL_CLOSURES = frozenset({
    date(2001, 9, 11), date(2001, 9, 12), date(2001, 9, 13), date(2001, 9, 14),  # September 11
    date(2004, 6, 11),                                                           # President Reagan
    date(2007, 1, 2),                                                            # President Ford
    date(2012, 10, 29), date(2012, 10, 30),                                      # Hurricane Sandy
    date(2018, 12, 5),                                                           # President G. H. W. Bush
    date(2025, 1, 9),                                                            # President Carter
})

REGULAR_OPEN = 9 * 60 + 30      # minutes after midnight ET
REGULAR_CLOSE = 16 * 60
EARLY_CLOSE = 13 * 60
PRE_OPEN = 4 * 60
POST_CLOSE = 20 * 60


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th ``weekday`` (Mon=0) of a month; n=-1 for the last one."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    nxt = date(year + month // 12, month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date | None:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def holidays(year: int) -> frozenset[date]:
    """Full-day closures in ``year`` (observed dates, special closures included)."""
    out = set()
    ny = date(year, 1, 1)
    if ny.weekday() != 5:                       # a Saturday New Year is not observed
        out.add(_observed(ny))
    out.add(_nth_weekday(year, 1, 0, 3))        # Martin Luther King Jr. Day
    out.add(_nth_weekday(year, 2, 0, 3))        # Washington's Birthday
    out.add(_easter(year) - timedelta(days=2))  # Good Friday
    out.add(_nth_weekday(year, 5, 0, -1))       # Memorial Day
    if year >= 2022:
        out.add(_observed(date(year, 6, 19)))   # Juneteenth
    out.add(_observed(date(year, 7, 4)))        # Independence Day
    out.add(_nth_weekday(year, 9, 0, 1))        # Labor Day
    out.add(_nth_weekday(year, 11, 3, 4))       # Thanksgiving
    out.add(_observed(date(year, 12, 25)))      # Christmas
    out |= {d for d in SPECIAL_CLOSURES if d.year == year}
    return frozenset(d for d in out if d.year == year)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def next_trading_day(d: date) -> date:
    """The first trading day strictly after ``d``."""
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def previous_trading_day(d: date) -> date:
    """The last trading day strictly before ``d``."""
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def trading_days(start: date, end: date) -> list[date]:
    """Trading days in ``[start, end]``."""
    out, d = [], start
    while d <= end:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def is_early_close(d: date) -> bool:
    if not is_trading_day(d):
        return False
    thanksgiving = _nth_weekday(d.year, 11, 3, 4)
    return d in (date(d.year, 7, 3), thanksgiving + timedelta(days=1), date(d.year, 12, 24))


def regular_close(d: date) -> int:
    """Close of the regular session on ``d``, minutes after midnight ET."""
    return EARLY_CLOSE if is_early_close(d) else REGULAR_CLOSE


def post_close(d: date) -> int:
    """End of after-hours trading on ``d`` (four hours after the close)."""
    return regular_close(d) + 4 * 60
