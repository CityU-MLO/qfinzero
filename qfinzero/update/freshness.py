"""Freshness — compare raw vs converted state per source.

Pure functions over the ``registry.scan()`` output; no I/O. ``today`` is a
parameter so the logic is deterministic and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Optional

from .sources import Source

# Business-day lag thresholds for the freshness colour.
GREEN_MAX_LAG = 1   # <= 1 business day behind today → fresh/green
AMBER_MAX_LAG = 5   # <= 5 → amber, else red


def _parse(d: Optional[str]) -> Optional[date]:
    if not d:
        return None
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _business_days_between(a: date, b: date) -> int:
    """Count weekdays strictly after ``a`` up to and including ``b`` (0 if b<=a)."""
    if b <= a:
        return 0
    days = 0
    cur = a
    while cur < b:
        cur = date.fromordinal(cur.toordinal() + 1)
        if cur.weekday() < 5:
            days += 1
    return days


@dataclass
class Freshness:
    source_id: str
    domain: str
    raw_max: Optional[str]
    store_max: Optional[str]
    behind_days: Optional[int]   # calendar days raw_max - store_max (dated sources)
    lag_days: Optional[int]      # business days store_max .. today
    state: str                   # fresh|behind|missing|no_raw|unavailable
    stale: bool
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def compute_freshness(source: Source, scan: dict, today: Optional[date] = None) -> Freshness:
    today = today or date.today()
    raw_max = source.raw_get(scan)
    store_max = source.store_get(scan)

    def mk(state: str, stale: bool, behind=None, lag=None) -> Freshness:
        return Freshness(
            source_id=source.id, domain=source.domain,
            raw_max=raw_max, store_max=store_max,
            behind_days=behind, lag_days=lag,
            state=state, stale=stale, note=source.note,
        )

    if not source.available:
        return mk("unavailable", False)
    if raw_max is None:
        return mk("no_raw", False)
    if store_max is None:
        return mk("missing", True)

    if not source.dated:
        # presence-only sources (rates / corp_actions): both present → assume fresh
        return mk("fresh", False)

    raw_d, store_d = _parse(raw_max), _parse(store_max)
    if raw_d is None or store_d is None:
        return mk("fresh", False)

    behind = (raw_d - store_d).days
    lag = _business_days_between(store_d, today)
    if behind > 0:
        return mk("behind", True, behind=behind, lag=lag)
    return mk("fresh", False, behind=0, lag=lag)


def colour(fr: Freshness) -> str:
    """Map a freshness to a green/amber/red/grey label for the UI."""
    if fr.state in ("unavailable", "no_raw"):
        return "grey"
    if fr.state in ("missing", "behind"):
        return "red" if (fr.lag_days is None or fr.lag_days > AMBER_MAX_LAG) else "amber"
    # fresh — colour by how stale the underlying data is vs today
    if fr.lag_days is None or fr.lag_days <= GREEN_MAX_LAG:
        return "green"
    return "amber" if fr.lag_days <= AMBER_MAX_LAG else "red"
