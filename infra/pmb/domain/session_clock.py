from datetime import datetime, timezone

from models.enums import Frequency, SessionStatus


def ns_to_iso(ns: int) -> str:
    dt = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + dt.strftime("%z")[:3] + ":" + dt.strftime("%z")[3:]


def iso_to_ns(iso_str: str) -> int:
    iso_str = iso_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


class SessionClock:
    """Manages simulation time progression through a sorted list of bar timestamps."""

    def __init__(self, timestamps_ns: list[int], frequency: Frequency, end_ts: str):
        self._timestamps = sorted(timestamps_ns)
        self._ts_index_map: dict[int, int] = {ts: i for i, ts in enumerate(self._timestamps)}
        self._index = -1  # before first bar
        self._frequency = frequency
        self._end_ts = end_ts

    @property
    def current_ns(self) -> int | None:
        if self._index < 0:
            return None
        return self._timestamps[self._index]

    @property
    def current_ts(self) -> str:
        if self._index < 0 and self._timestamps:
            return ns_to_iso(self._timestamps[0])
        if self._index < 0:
            return ""
        return ns_to_iso(self._timestamps[self._index])

    @property
    def prev_ts(self) -> str | None:
        if self._index <= 0:
            return None
        return ns_to_iso(self._timestamps[self._index - 1])

    @property
    def frequency(self) -> Frequency:
        return self._frequency

    @property
    def end_ts(self) -> str:
        return self._end_ts

    @property
    def status(self) -> SessionStatus:
        if self._index >= len(self._timestamps) - 1:
            return SessionStatus.FINISHED
        return SessionStatus.RUNNING

    @property
    def is_done(self) -> bool:
        return self._index >= len(self._timestamps) - 1

    @property
    def step_count(self) -> int:
        return max(0, self._index + 1)

    @property
    def total_bars(self) -> int:
        return len(self._timestamps)

    def is_last_bar_of_date(self, ts_ns: int) -> bool:
        """Return True if ts_ns is the last bar on its calendar date.

        For DAILY sessions this is always True (one bar = one day = EOD).
        For MINUTE sessions this returns True only when the next bar is on a
        different date (or there is no next bar), so option expiry and order
        cancellation fire at the last intraday bar rather than at 09:31.
        """
        if self._frequency == Frequency.DAILY:
            return True
        idx = self._ts_index_map.get(ts_ns)
        if idx is None:
            return True
        if idx + 1 >= len(self._timestamps):
            return True  # last bar in the whole session
        next_date = ns_to_iso(self._timestamps[idx + 1])[:10]
        current_date = ns_to_iso(ts_ns)[:10]
        return next_date != current_date

    def step(self, n: int = 1) -> list[int]:
        """Advance n bars. Returns list of timestamp_ns values traversed."""
        traversed = []
        for _ in range(n):
            if self.is_done:
                break
            self._index += 1
            traversed.append(self._timestamps[self._index])
        return traversed
