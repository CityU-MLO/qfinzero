"""Source registry — one declaration shared by the CLI, the manifest, and the
(future) data-admin API.

A *source* is one updatable thing (a price store, a news feed, …). Price sources
are wired to the existing :class:`qfinzero.pipeline.convert.Converter`; the
non-price sources are declared for completeness but flagged ``available=False``
until their load-only entry points land (design §3.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing duckdb/polars just to enumerate sources
    from qfinzero.pipeline.convert import ConvertResult, Converter


def _dig(scan: dict, *keys, default=None):
    """Safely walk a nested dict (the registry.scan() output)."""
    cur = scan
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _present(value) -> Optional[str]:
    """Normalize a presence/count flag to the ``"present"`` sentinel or None."""
    return "present" if value else None


@dataclass(frozen=True)
class Source:
    id: str
    domain: str                       # price | news | econ | earnings
    market: Optional[str]             # us | cn | None (global)
    owner: str                        # qfz | shared  ("shared" = Assay also updates raw)
    store: str                        # primary storage key (for the freshness label)
    raw_get: Callable[[dict], Optional[str]]    # latest raw date/sentinel from scan()
    store_get: Callable[[dict], Optional[str]]  # latest converted date/sentinel from scan()
    run: Optional[Callable[["Converter", Optional[str], bool], "ConvertResult"]] = None
    dated: bool = True                # True = compare ISO dates; False = presence-only
    available: bool = True            # False = loader not wired yet
    note: str = ""

    def matches_market(self, market: Optional[str]) -> bool:
        return market is None or self.market is None or self.market == market


# ── Price sources (wired to the existing converter) ─────────────────────

SOURCES: list[Source] = [
    Source(
        id="us_stock_daily", domain="price", market="us", owner="shared",
        store="stock_daily",
        raw_get=lambda s: _dig(s, "raw", "massive", "stock_daily", "end"),
        store_get=lambda s: _dig(s, "storage", "stock_daily", "end"),
        run=lambda cv, start, force: cv.convert_us_stock_daily(start=start, force=force),
    ),
    Source(
        id="us_stock_minute", domain="price", market="us", owner="shared",
        store="stock_minute",
        raw_get=lambda s: _dig(s, "raw", "massive", "stock_minute", "end"),
        store_get=lambda s: _dig(s, "storage", "stock_minute", "end"),
        run=lambda cv, start, force: cv.convert_us_stock_minute(start=start, force=force),
    ),
    Source(
        id="us_option_day", domain="price", market="us", owner="qfz",
        store="option_day",
        raw_get=lambda s: _dig(s, "raw", "massive", "option_day", "end"),
        store_get=lambda s: _dig(s, "storage", "option_day", "end"),
        run=lambda cv, start, force: cv.convert_us_option_day(start=start, force=force),
    ),
    Source(
        id="us_option_minute", domain="price", market="us", owner="qfz",
        store="option_minute",
        raw_get=lambda s: _dig(s, "raw", "massive", "option_minute", "end"),
        store_get=lambda s: _dig(s, "storage", "option_minute", "end"),
        run=lambda cv, start, force: cv.convert_us_option_minute(start=start, force=force),
    ),
    Source(
        id="cn_stock_daily", domain="price", market="cn", owner="shared",
        store="stock_daily",
        raw_get=lambda s: _dig(s, "raw", "tushare", "cn_daily", "end"),
        # store_max is the shared stock_daily end (US+CN coexist); a coarse signal.
        store_get=lambda s: _dig(s, "storage", "stock_daily", "end"),
        run=lambda cv, start, force: cv.convert_cn_stock_daily(start=start, force=force),
        note="store_max approximated by the shared stock_daily partition range",
    ),
    Source(
        id="rates", domain="price", market=None, owner="qfz",
        store="rates", dated=False,
        raw_get=lambda s: _present(_dig(s, "raw", "massive", "rates", "present")),
        store_get=lambda s: _present(_dig(s, "storage", "rates/rates.parquet")),
        run=lambda cv, start, force: cv.convert_rates(force=force),
    ),
    Source(
        id="corp_actions", domain="price", market=None, owner="qfz",
        store="corporate_actions", dated=False,
        raw_get=lambda s: _present(
            _dig(s, "raw", "massive", "splits_files")
            or _dig(s, "raw", "tushare", "cn_dividend_files")
        ),
        store_get=lambda s: _present(
            _dig(s, "storage", "corporate_actions/corporate_actions.parquet")
        ),
        run=lambda cv, start, force: cv.convert_corporate_actions(
            include_massive=True, include_tushare=True
        ),
        note="rebuilt when any stock/option source converts new partitions",
    ),
    # ── Non-price sources: declared, loaders deferred (design §3.6) ──────
    Source(
        id="news", domain="news", market=None, owner="qfz", store="mongo:ticker_news",
        dated=False, available=False,
        raw_get=lambda s: None, store_get=lambda s: None,
        note="ESP news loader not wired yet",
    ),
    Source(
        id="econ", domain="econ", market=None, owner="qfz", store="sqlite:econ_events",
        dated=False, available=False,
        raw_get=lambda s: None, store_get=lambda s: None,
        note="ESP econ loader not wired yet",
    ),
    Source(
        id="earnings", domain="earnings", market=None, owner="qfz", store="sqlite:earnings",
        dated=False, available=False,
        raw_get=lambda s: None, store_get=lambda s: None,
        note="ESP Benzinga loader not wired yet (optional)",
    ),
]

BY_ID: dict[str, Source] = {s.id: s for s in SOURCES}

# Domain aliases accepted on the CLI.
_DOMAIN_ALIASES = {
    "prices": "price",
    "price": "price",
    "news": "news",
    "econ": "econ",
    "earnings": "earnings",
}


def select(arg: str | None, market: str | None = None) -> list[Source]:
    """Resolve a selection string into an ordered, de-duplicated source list.

    ``arg`` accepts ``"all"``, domain names (``prices``/``news``/…), explicit
    source ids, or a comma-separated mix. ``market`` further filters by market.
    """
    tokens = [t.strip() for t in (arg or "all").split(",") if t.strip()]
    chosen: set[str] = set()
    for tok in tokens:
        low = tok.lower()
        if low == "all":
            chosen.update(BY_ID)
        elif low in _DOMAIN_ALIASES:
            dom = _DOMAIN_ALIASES[low]
            chosen.update(s.id for s in SOURCES if s.domain == dom)
        elif tok in BY_ID:
            chosen.add(tok)
        else:
            raise ValueError(f"unknown source/domain: {tok!r}")
    return [s for s in SOURCES if s.id in chosen and s.matches_market(market)]
