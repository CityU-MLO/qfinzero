"""US trading sessions: which segment a bar is in and which trading date it belongs to.

Segments (US/Eastern wall clock):

==========  ==============  =============================================
segment     hours (ET)      notes
==========  ==============  =============================================
OVERNIGHT   20:00 - 04:00   Blue Ocean ATS; belongs to the *next* trading day
PRE         04:00 - 09:30   pre-market
REGULAR     09:30 - 16:00   the only segment options trade in
POST        16:00 - 20:00   after-hours
==========  ==============  =============================================

An order's ``trading_hours`` decides where it may execute:

* ``REGULAR``   (default) REGULAR only; any order type.
* ``EXTENDED``  PRE + REGULAR + POST; LIMIT orders only.
* ``OVERNIGHT`` all four segments (24/5); LIMIT orders only.

Options always execute in REGULAR only. Futures trade whenever their venue
prints a bar (CME Globex: 18:00-17:00 ET), whatever ``trading_hours`` says,
and settle on CME session dates (see ``domain/futures.py``). Daily-frequency
sessions have one bar per day, so every bar is REGULAR and is its own trading
date.

Exchange holidays and 13:00 early closes come from :mod:`qfinzero.market_calendar`:
on an early-close day REGULAR ends at 13:00 and POST at 17:00.

The trading date is what DAY orders and option expiry key on. It replaces the
UTC calendar date the clock used before, which broke at 19:00/20:00 ET.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from models.enums import Frequency, InstrumentType, OrderType, TradingHours
from qfinzero.market_calendar import is_trading_day, next_trading_day, post_close, regular_close

ET = ZoneInfo("America/New_York")

REGULAR_OPEN_MIN = 9 * 60 + 30
REGULAR_CLOSE_MIN = 16 * 60
PRE_OPEN_MIN = 4 * 60
POST_CLOSE_MIN = 20 * 60


class Segment(str, Enum):
    OVERNIGHT = "OVERNIGHT"
    PRE = "PRE"
    REGULAR = "REGULAR"
    POST = "POST"


ALLOWED: dict[TradingHours, frozenset[Segment]] = {
    TradingHours.REGULAR: frozenset({Segment.REGULAR}),
    TradingHours.EXTENDED: frozenset({Segment.PRE, Segment.REGULAR, Segment.POST}),
    TradingHours.OVERNIGHT: frozenset(Segment),
}


def _et(ts_ns: int) -> datetime:
    return datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).astimezone(ET)


def segment_of(ts_ns: int, frequency: Frequency = Frequency.MINUTE) -> Segment:
    """Session segment of a bar starting at ``ts_ns``."""
    if frequency == Frequency.DAILY:
        return Segment.REGULAR
    t = _et(ts_ns)
    m = t.hour * 60 + t.minute
    close = regular_close(t.date())
    if REGULAR_OPEN_MIN <= m < close:
        return Segment.REGULAR
    if PRE_OPEN_MIN <= m < REGULAR_OPEN_MIN:
        return Segment.PRE
    if close <= m < post_close(t.date()):
        return Segment.POST
    return Segment.OVERNIGHT


def trading_date_of(ts_ns: int, frequency: Frequency = Frequency.MINUTE) -> str:
    """Trading date (``YYYY-MM-DD``) a bar belongs to.

    Daily bars keep the date they are stamped with. Minute bars use the ET
    date, except that the overnight segment from 20:00 ET belongs to the next
    trading day (Friday night belongs to Monday, the night before a holiday to
    the day after it). Bars between 00:00 and 04:00 ET already carry that date
    unless it is not a trading day.
    """
    if frequency == Frequency.DAILY:
        return datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).date().isoformat()
    t = _et(ts_ns)
    d = t.date()
    if t.hour * 60 + t.minute >= post_close(d):
        d = next_trading_day(d)
    elif not is_trading_day(d):     # weekend / holiday overnight bars
        d = next_trading_day(d)
    return d.isoformat()


def is_option(instrument_id: str) -> bool:
    return instrument_id.startswith("OPTION:")


def order_may_execute(trading_hours: TradingHours, instrument_id: str,
                      segment: Segment) -> bool:
    """Whether an order with these hours may match against a bar in ``segment``."""
    if instrument_id.startswith("FUTURE:"):
        return True
    if is_option(instrument_id):
        return segment == Segment.REGULAR
    return segment in ALLOWED[trading_hours]


def validate_trading_hours(trading_hours: TradingHours, order_type: OrderType,
                           instrument_type: InstrumentType | None) -> str | None:
    """Submission-time rule check. Returns an error message or ``None``."""
    if trading_hours == TradingHours.REGULAR or instrument_type == InstrumentType.FUTURE:
        return None
    if instrument_type == InstrumentType.OPTION:
        return "options trade in regular hours only (trading_hours must be REGULAR)"
    if order_type != OrderType.LIMIT:
        return f"{trading_hours.value} hours accept LIMIT orders only"
    return None
