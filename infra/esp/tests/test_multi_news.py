"""News spread over per-vendor collections reads as one source."""

import asyncio
from types import SimpleNamespace

from services.data_sources import MultiMongoNewsSource


class _Part:
    def __init__(self, events, docs=None, available=True):
        self.events, self.docs, self.available, self.asked = events, docs or {}, available, []

    async def query_window(self, start, end, tickers, limit, cursor, now):
        return [e for e in self.events if not cursor or (e.time_utc, e.event_id) > cursor][:limit]

    async def search_news(self, start, end, tickers, kw, pub, limit, cursor, now):
        return await self.query_window(start, end, tickers, limit, cursor, now)

    async def get_by_id(self, news_id):
        self.asked.append(news_id)
        return self.docs.get(news_id)


def _ev(t, i):
    return SimpleNamespace(time_utc=f"2026-08-01T{t}:00Z", event_id=f"news_{i}")


def _multi(parts, prefixes=None):
    m = MultiMongoNewsSource.__new__(MultiMongoNewsSource)
    m.collections = [(sid, f"news_{sid}") for sid, _ in parts]
    m._parts = parts
    m._prefixes = prefixes or {}
    return m


def test_window_merges_in_time_order_and_keeps_the_limit():
    bz = _Part([_ev("13:00", "bz_1"), _ev("14:00", "bz_2"), _ev("16:00", "bz_3")])
    ts = _Part([_ev("13:30", "ts_1"), _ev("14:00", "ts_0")])
    m = _multi([("benzinga", bz), ("tushare", ts)])
    got = asyncio.run(m.query_window(None, None, None, 4, None, None))
    assert [e.event_id for e in got] == ["news_bz_1", "news_ts_1", "news_bz_2", "news_ts_0"]
    # the next page starts after the cursor in every collection
    nxt = asyncio.run(m.query_window(None, None, None, 4, (got[-1].time_utc, got[-1].event_id), None))
    assert [e.event_id for e in nxt] == ["news_bz_3"]


def test_unavailable_collection_is_skipped():
    m = _multi([("benzinga", _Part([_ev("13:00", "bz_1")])), ("tushare", _Part([_ev("12:00", "ts_1")], available=False))])
    assert [e.event_id for e in asyncio.run(m.search_news(None, None, None, None, None, 10, None, None))] == ["news_bz_1"]


def test_get_by_id_asks_the_vendor_with_the_prefix_first():
    bz = _Part([], {"bz_7": {"_id": "bz_7"}})
    ts = _Part([])
    m = _multi([("tushare", ts), ("benzinga", bz)], {"benzinga": "bz_", "tushare": "ts_"})
    assert asyncio.run(m.get_by_id("bz_7")) == {"_id": "bz_7"}
    assert ts.asked == []
    assert asyncio.run(m.get_by_id("zz_1")) is None
    assert ts.asked == ["zz_1"] and bz.asked == ["bz_7", "zz_1"]
