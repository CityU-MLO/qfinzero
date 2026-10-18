"""Time lock: bind data queries to a simulation session's clock.

An agent trading inside a PMB session must not see data from after the bar it
is deciding on. The time lock turns a session into an ``as_of`` timestamp that
the UPQ service enforces on every query (see ``infra/upq/.../as_of.rs``) and
that ESP queries use as ``now_utc`` and as the upper end of their windows.

Where the session comes from, highest priority first:

1. the ``X-QFZ-Session`` header of the MCP / HTTP connection (benchmark
   runners set it; the agent cannot change it),
2. the ``QFZ_TIME_LOCK_SESSION`` environment variable (one MCP server per
   episode),
3. a ``session_id`` the caller passes.

With ``QFZ_REQUIRE_SESSION=1`` a data query without any session is refused.

``as_of`` for a session is the close of the current bar: ``current + 60s`` for
minute sessions; 16:00 ET of the current trading date for daily sessions
(PMB shows the agent that day's bar when it decides).
"""

from __future__ import annotations

import os
from datetime import datetime, time, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HEADER = "x-qfz-session"


class TimeLockError(ValueError):
    """A time-locked query could not be resolved (missing or unknown session)."""


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def as_of_for_clock(clock: dict) -> Optional[str]:
    """``as_of`` (ISO UTC) for a PMB clock dict (``frequency``, ``current_ts``,
    optional ``trading_date``)."""
    cur = clock.get("current_ts")
    if not cur:
        return None
    if clock.get("frequency") == "1d":
        day = clock.get("trading_date") or cur[:10]
        close = datetime.combine(datetime.fromisoformat(day).date(), time(16, 0), tzinfo=ET)
        out = close.astimezone(timezone.utc)
    else:
        out = _parse_iso(cur).astimezone(timezone.utc) + timedelta(seconds=60)
    return out.strftime("%Y-%m-%dT%H:%M:%SZ")


def bound_session(header_session: Optional[str], session_id: Optional[str]) -> Optional[str]:
    """The session a call is locked to, applying the priority above."""
    return header_session or os.environ.get("QFZ_TIME_LOCK_SESSION") or session_id or None


def resolve(
    session: Optional[str],
    fetch_clock: Callable[[str], dict],
) -> Optional[str]:
    """``as_of`` for ``session`` (or ``None`` when unlocked).

    Raises :class:`TimeLockError` when ``QFZ_REQUIRE_SESSION`` is set and there
    is no session, or when the session's clock cannot be read.
    """
    if not session:
        if os.environ.get("QFZ_REQUIRE_SESSION", "").strip() not in ("", "0", "false"):
            raise TimeLockError("time-locked mode: pass session_id (or connect with X-QFZ-Session)")
        return None
    try:
        clock = fetch_clock(session)
    except Exception as e:  # noqa: BLE001 - unknown session -> refuse, never leak
        raise TimeLockError(f"cannot read clock of session {session!r}: {e}") from e
    as_of = as_of_for_clock(clock or {})
    if as_of is None:
        raise TimeLockError(f"session {session!r} has no clock yet")
    return as_of


def utc_iso(ts: str) -> str:
    """``YYYY-MM-DDTHH:MM:SS`` in UTC for any ISO datetime (offsets honoured)."""
    return _parse_iso(ts).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def clamp_end(end: Optional[str], as_of: Optional[str]) -> Optional[str]:
    """The earlier of an ISO ``end`` and ``as_of`` (``as_of`` when ``end`` is unset)."""
    if as_of is None:
        return end
    if not end:
        return as_of
    try:
        return as_of if _parse_iso(end) > _parse_iso(as_of) else end
    except ValueError:
        return as_of


def clamp_date(end_date: Optional[str], as_of: Optional[str]) -> Optional[str]:
    """The earlier of a ``YYYY-MM-DD`` end and the ET date of ``as_of``."""
    if as_of is None:
        return end_date
    cap = _parse_iso(as_of).astimezone(ET).date().isoformat()
    return cap if not end_date or end_date > cap else end_date
