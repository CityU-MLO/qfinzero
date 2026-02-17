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

    def step(self, n: int = 1) -> list[int]:
        """Advance n bars. Returns list of timestamp_ns values traversed."""
        traversed = []
        for _ in range(n):
            if self.is_done:
                break
            self._index += 1
            traversed.append(self._timestamps[self._index])
        return traversed
