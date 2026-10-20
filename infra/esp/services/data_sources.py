"""
Data source connectors for ESP.

Async connectors that normalise raw rows into the canonical Event schema:
  - MongoNewsSource   (motor / MongoDB)
  - SQLiteNewsSource  (aiosqlite; same interface, used by the synthetic sample
                       and for deployments without MongoDB)
  - SQLiteEarningsSource  (aiosqlite)
  - SQLiteEconEventsSource (aiosqlite)

Point in time: earnings and macro results (actual EPS, actual prints) are
returned only when the event's time is not after the query's ``now_utc``;
before that the event is SCHEDULED with its actuals blanked.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Optional

import html as html_mod

from models import Event, EventType, EventStatus, Importance
from qfinzero.esp_schema import NEWS_SCHEMA  # noqa: F401  (documented on SQLiteNewsSource)

logger = logging.getLogger("esp.data_sources")

EST = ZoneInfo("America/New_York")
# A keyword search over a large collection may scan a long window: stop it after this
# and answer with the other collections' results and a warning (the clients time out at 30 s).
NEWS_SEARCH_MAX_MS = int(os.environ.get("ESP_NEWS_SEARCH_MAX_MS", "20000"))
CONTENT_LEVELS = ("headline", "summary", "full")


def _levels(min_content: Optional[str]) -> Optional[list[str]]:
    """Content levels kept by a ``min_content`` filter (``None``: all articles)."""
    if not min_content or min_content == "headline":
        return None
    return list(CONTENT_LEVELS[CONTENT_LEVELS.index(min_content):])


def _content_of(doc: dict) -> tuple[str, int]:
    """(content_level, content_chars): stored by the loader, else worked out from the doc."""
    if doc.get("content_level") in CONTENT_LEVELS:
        return doc["content_level"], int(doc.get("content_chars") or 0)
    body = str(doc.get("body_text") or "").strip()
    desc = str(doc.get("description") or "").strip()
    return ("full" if body else "summary" if desc else "headline"), len(body or desc)


def _mongo_content_filter(min_content: Optional[str]) -> Optional[dict]:
    """Mongo filter for ``min_content``; documents loaded before content levels existed
    are judged from their text fields."""
    levels = _levels(min_content)
    if levels is None:
        return None
    text = {"$nin": [None, ""]}
    raw = {"body_text": text} if levels == ["full"] else {"$or": [{"body_text": text}, {"description": text}]}
    return {"$or": [{"content_level": {"$in": levels}}, {"content_level": {"$exists": False}, **raw}]}

# ── Importance inference for economic events ─────────────────────

_HIGH_KEYWORDS = [
    "FOMC", "Fed Interest Rate", "Non-Farm Payrolls", "Nonfarm Payrolls",
    "CPI", "GDP", "Unemployment Rate", "PCE", "Retail Sales",
    "ISM Manufacturing", "Federal Funds Rate",
]
_MEDIUM_KEYWORDS = [
    "PPI", "Durable Goods", "Housing Starts", "Consumer Confidence",
    "Initial Jobless Claims", "Trade Balance", "Industrial Production",
    "Building Permits", "Existing Home Sales", "New Home Sales",
]


def _infer_econ_importance(event_name: str) -> Importance:
    upper = (event_name or "").upper()
    for kw in _HIGH_KEYWORDS:
        if kw.upper() in upper:
            return Importance.HIGH
    for kw in _MEDIUM_KEYWORDS:
        if kw.upper() in upper:
            return Importance.MEDIUM
    return Importance.LOW


def _earnings_importance(val: Any) -> Importance:
    v = val or 0
    if v >= 4:
        return Importance.HIGH
    if v >= 2:
        return Importance.MEDIUM
    return Importance.LOW


# ── Helpers ──────────────────────────────────────────────────────

def _parse_utc(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _known_at(event_utc: datetime, now_utc: Optional[datetime]) -> bool:
    """Whether an event at ``event_utc`` has happened by ``now_utc`` (None = now)."""
    return now_utc is None or event_utc <= now_utc


def _news_end(end_utc: datetime, now_utc: Optional[datetime]) -> datetime:
    """News published after ``now_utc`` does not exist yet: cap the window end."""
    if now_utc is None:
        return end_utc
    return min(end_utc, now_utc + timedelta(microseconds=1))


def _clean_html(s: str) -> str:
    """Strip &nbsp; and other HTML entities."""
    if not s:
        return ""
    return html_mod.unescape(s).strip()


# ── Pure builder functions (no DB dependency, easily unit-tested) ─

def build_earnings_snippet(row: dict, *, occurred: bool) -> str:
    """Build a human-readable snippet for an earnings event.

    When occurred=False (scheduled), actual values are omitted to avoid
    leaking results that haven't happened yet.
    """
    parts = []
    ticker = row.get("ticker") or ""
    period = row.get("fiscal_period") or ""
    fy = row.get("fiscal_year") or ""
    if ticker:
        parts.append(ticker)
    if period and fy:
        parts.append(f"{period} FY{fy}")

    if occurred:
        eps = row.get("actual_eps")
        est = row.get("estimated_eps")
        if eps is not None and est is not None:
            parts.append(f"EPS {eps} vs est {est}")
        elif eps is not None:
            parts.append(f"EPS {eps}")
        rev = row.get("actual_revenue")
        if rev is not None:
            parts.append(f"Rev {rev:,.0f}")
    else:
        est = row.get("estimated_eps")
        if est is not None:
            parts.append(f"Est EPS {est}")

    return " | ".join(parts) if parts else ""


def build_earnings_payload(row: dict, *, occurred: bool) -> dict:
    """Build the payload dict for an earnings event.

    When occurred=False (scheduled), actual/surprise fields are set to None
    so future events never expose result data.
    """
    fp = row.get("fiscal_period") or ""
    fy = row.get("fiscal_year") or ""
    return {
        "actual_eps": row.get("actual_eps") if occurred else None,
        "estimated_eps": row.get("estimated_eps"),
        "previous_eps": row.get("previous_eps") if occurred else None,
        "eps_surprise": row.get("eps_surprise") if occurred else None,
        "eps_surprise_percent": row.get("eps_surprise_percent") if occurred else None,
        "actual_revenue": row.get("actual_revenue") if occurred else None,
        "estimated_revenue": row.get("estimated_revenue"),
        "revenue_surprise": row.get("revenue_surprise") if occurred else None,
        "revenue_surprise_percent": row.get("revenue_surprise_percent") if occurred else None,
        "fiscal_period": fp,
        "fiscal_year": fy,
        "company_name": row.get("company_name"),
    }


def build_econ_snippet(row: dict, *, occurred: bool) -> str:
    """Build a human-readable snippet for an economic calendar event.

    When occurred=False (scheduled), actual and previous are omitted.
    """
    parts = []
    consensus = _clean_html(row.get("consensus") or "")
    if occurred:
        actual = _clean_html(row.get("actual") or "")
        previous = _clean_html(row.get("previous") or "")
        if actual:
            parts.append(f"Actual: {actual}")
        if consensus:
            parts.append(f"Consensus: {consensus}")
        if previous:
            parts.append(f"Previous: {previous}")
    else:
        if consensus:
            parts.append(f"Consensus: {consensus}")
    return " | ".join(parts) if parts else ""


def build_econ_payload(row: dict, *, occurred: bool) -> dict:
    """Build the payload dict for an economic calendar event.

    When occurred=False (scheduled), actual and previous are set to None.
    """
    return {
        "actual": (_clean_html(row.get("actual") or "") or None) if occurred else None,
        "consensus": _clean_html(row.get("consensus") or "") or None,
        "previous": (_clean_html(row.get("previous") or "") or None) if occurred else None,
        "description": row.get("description"),
    }


# ── Cursor helpers ───────────────────────────────────────────────

def _cursor_where_sql(cursor: Optional[tuple[str, str]], time_col: str, id_col: str):
    """Return (sql_fragment, params) for cursor-based pagination."""
    if not cursor:
        return "", []
    return (
        f"AND ({time_col} > ? OR ({time_col} = ? AND {id_col} > ?))",
        [cursor[0], cursor[0], cursor[1]],
    )


# =====================================================================
# MongoNewsSource
# =====================================================================

def news_doc_to_event(doc: dict, now_utc: datetime) -> Event:
    """A news document (Mongo shape) -> Event."""
    pub_utc = doc.get("published_utc")
    if isinstance(pub_utc, datetime):
        if pub_utc.tzinfo is None:
            pub_utc = pub_utc.replace(tzinfo=timezone.utc)
    else:
        pub_utc = _parse_utc(str(pub_utc)) if pub_utc else _utc_now()

    age_hours = (now_utc - pub_utc).total_seconds() / 3600
    event_type = EventType.BREAKING_NEWS if age_hours < 4 else EventType.DAILY_NEWS

    publisher = doc.get("publisher")
    pub_name = publisher.get("name") if isinstance(publisher, dict) else None

    return Event(
        event_id=f"news_{doc['_id']}",
        event_type=event_type,
        title=html_mod.unescape(doc.get("title") or ""),   # Benzinga titles carry HTML entities
        time_utc=pub_utc.isoformat(),
        importance=Importance.MEDIUM,
        status=EventStatus.OCCURRED,
        tickers=doc.get("tickers") or [],
        country="CN" if str(doc.get("market") or "").lower() == "cn" else "US",
        snippet=(doc.get("description") or "")[:200],
        payload={
            "article_url": doc.get("article_url"),
            "author": doc.get("author"),
            "publisher": pub_name,
            "keywords": doc.get("keywords") or [],
        },
        source=doc.get("source") or "polygon_news",
        source_id=str(doc["_id"]),
        content_level=_content_of(doc)[0],
        content_chars=_content_of(doc)[1],
    )


def _rate(total: int, unique: int) -> dict:
    return {"total": total, "unique": unique,
            "duplicate_rate": round((total - unique) / total, 4) if total > 0 else 0.0}


class MongoNewsSource:
    kind = "mongo"

    def __init__(self, mongo_uri: str, db_name: str, coll_name: str):
        self._uri = mongo_uri
        self._db_name = db_name
        self._coll_name = coll_name
        self._client = None
        self._coll = None

    async def connect(self):
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            self._client = AsyncIOMotorClient(self._uri, serverSelectionTimeoutMS=3000)
            # Force a connection check
            await self._client.server_info()
            self._coll = self._client[self._db_name][self._coll_name]
            logger.info("MongoDB connected: %s/%s", self._db_name, self._coll_name)
        except Exception as e:
            logger.warning("MongoDB unavailable (%s), news source degraded", e)
            self._client = None
            self._coll = None

    async def close(self):
        if self._client:
            self._client.close()

    @property
    def available(self) -> bool:
        return self._coll is not None

    async def get_freshness(self) -> Optional[str]:
        if not self.available:
            return None
        doc = await self._coll.find_one(sort=[("published_utc", -1)])
        if doc and doc.get("published_utc"):
            return doc["published_utc"].isoformat()
        return None

    async def query_window(
        self,
        start_utc: datetime,
        end_utc: datetime,
        tickers: Optional[list[str]],
        limit: int,
        cursor: Optional[tuple[str, str]],
        now_utc: datetime,
        min_content: Optional[str] = None,
    ) -> list[Event]:
        if not self.available:
            return []
        end_utc = _news_end(end_utc, now_utc)

        query: dict[str, Any] = {
            "published_utc": {"$gte": start_utc, "$lt": end_utc},
        }
        if tickers:
            query["tickers"] = {"$in": [t.upper() for t in tickers]}
        if (cf := _mongo_content_filter(min_content)) is not None:
            query["$and"] = [cf]
        if cursor:
            cursor_time = _parse_utc(cursor[0])
            cursor_id = cursor[1].removeprefix("news_")
            query["$or"] = [
                {"published_utc": {"$gt": cursor_time}},
                {"published_utc": cursor_time, "_id": {"$gt": cursor_id}},
            ]
            # Remove the simpler range, $or takes over
            query["published_utc"] = {"$gte": start_utc, "$lt": end_utc}

        docs = (
            self._coll.find(query)
            .sort([("published_utc", 1), ("_id", 1)])
            .limit(limit)
        )
        events = []
        async for doc in docs:
            events.append(self._to_event(doc, now_utc))
        return events

    async def search_news(
        self,
        start_utc: datetime,
        end_utc: datetime,
        tickers: Optional[list[str]],
        keyword: Optional[str],
        publisher: Optional[str],
        limit: int,
        cursor: Optional[tuple[str, str]],
        now_utc: datetime,
        warnings: Optional[list[str]] = None,
        min_content: Optional[str] = None,
    ) -> list[Event]:
        if not self.available:
            return []
        end_utc = _news_end(end_utc, now_utc)

        query: dict[str, Any] = {
            "published_utc": {"$gte": start_utc, "$lt": end_utc},
        }
        if tickers:
            query["tickers"] = {"$in": [t.upper() for t in tickers]}
        if keyword:
            query["title"] = {"$regex": re.escape(keyword), "$options": "i"}
        if publisher:
            query["publisher.name"] = {"$regex": re.escape(publisher), "$options": "i"}
        if (cf := _mongo_content_filter(min_content)) is not None:
            query["$and"] = [cf]
        if cursor:
            cursor_time = _parse_utc(cursor[0])
            cursor_id = cursor[1].removeprefix("news_")
            query["$or"] = [
                {"published_utc": {"$gt": cursor_time}},
                {"published_utc": cursor_time, "_id": {"$gt": cursor_id}},
            ]
            query["published_utc"] = {"$gte": start_utc, "$lt": end_utc}

        docs = (
            self._coll.find(query)
            .sort([("published_utc", 1), ("_id", 1)])
            .limit(limit)
            .max_time_ms(NEWS_SEARCH_MAX_MS)
        )
        events = []
        try:
            async for doc in docs:
                events.append(self._to_event(doc, now_utc))
        except Exception as e:  # noqa: BLE001 - pymongo ExecutionTimeout (code 50); others re-raised
            if getattr(e, "code", None) != 50:
                raise
            logger.warning("news search on %s stopped after %d ms", self._coll_name, NEWS_SEARCH_MAX_MS)
            if warnings is not None:
                warnings.append(f"{self._coll_name}: the search stopped after {NEWS_SEARCH_MAX_MS // 1000} s "
                                "without finishing; narrow the time window or add tickers")
        return events

    async def get_by_id(self, news_id: str) -> Optional[dict]:
        if not self.available:
            return None
        return await self._coll.find_one({"_id": news_id})

    def _to_event(self, doc: dict, now_utc: datetime) -> Event:
        return news_doc_to_event(doc, now_utc)

    async def info(self) -> dict:
        """Latest timestamp, record count and distinct tickers (health page)."""
        out = {"latest_timestamp": None, "record_count": 0, "unique_keys": 0}
        if not self.available:
            return out
        latest = await self._coll.find_one(sort=[("published_utc", -1)])
        if latest and latest.get("published_utc"):
            pub = latest["published_utc"]
            out["latest_timestamp"] = pub.isoformat() if hasattr(pub, "isoformat") else str(pub)
        out["record_count"] = await self._coll.estimated_document_count()   # a full count scans every document
        out["unique_keys"] = len(await self._coll.distinct("tickers"))
        return out

    async def stats(self, since: datetime) -> dict:
        coll = self._coll
        match = {"$match": {"published_utc": {"$gte": since}}}
        total_count = await coll.count_documents({"published_utc": {"$gte": since}})
        first = await coll.find_one({"published_utc": {"$gte": since}}, sort=[("published_utc", 1)])
        last = await coll.find_one({"published_utc": {"$gte": since}}, sort=[("published_utc", -1)])
        daily = [{"date": d["_id"], "count": d["count"]} async for d in coll.aggregate([
            match, {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$published_utc"}},
                               "count": {"$sum": 1}}}, {"$sort": {"_id": 1}}])]
        tickers = [{"ticker": d["_id"], "count": d["count"]} async for d in coll.aggregate([
            match, {"$unwind": "$tickers"}, {"$group": {"_id": "$tickers", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}, {"$limit": 20}])]
        pubs = [{"publisher": d["_id"], "count": d["count"]} async for d in coll.aggregate([
            match, {"$group": {"_id": "$publisher.name", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}, {"$limit": 10}])]

        async def dup(field: str) -> dict:
            async for d in coll.aggregate([
                    match, {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                    {"$group": {"_id": None, "total": {"$sum": "$count"}, "unique": {"$sum": 1}}}]):
                return _rate(d["total"], d["unique"])
            return _rate(0, 0)

        return {
            "total_count": total_count,
            "date_range": {"earliest": first["published_utc"].isoformat() if first else None,
                           "latest": last["published_utc"].isoformat() if last else None},
            "daily_counts": daily, "top_tickers": tickers, "top_publishers": pubs,
            "duplicate_stats": {"by_url": await dup("article_url"), "by_title": await dup("title")},
        }

    async def count(self, start: datetime, end: datetime, tickers: Optional[list[str]]) -> int:
        q: dict[str, Any] = {"published_utc": {"$gte": start, "$lt": end}}
        if tickers:
            q["tickers"] = {"$in": tickers}
        return await self._coll.count_documents(q)

    async def iter_docs(self, start: datetime, end: datetime, tickers: Optional[list[str]], limit: int):
        q: dict[str, Any] = {"published_utc": {"$gte": start, "$lt": end}}
        if tickers:
            q["tickers"] = {"$in": tickers}
        async for doc in self._coll.find(q).sort([("published_utc", 1)]).limit(limit):
            yield doc

    async def daily_counts(self, start: datetime, end: datetime, tickers: list[str]) -> list[dict]:
        """Articles per (ticker, US/Eastern date) in ``[start, end)``."""
        pipeline = [
            {"$match": {"published_utc": {"$gte": start, "$lt": end}, "tickers": {"$in": tickers}}},
            {"$unwind": "$tickers"},
            {"$match": {"tickers": {"$in": tickers}}},
            {"$group": {"_id": {"t": "$tickers", "d": {"$dateToString": {
                "format": "%Y-%m-%d", "date": "$published_utc", "timezone": "America/New_York"}}},
                "n": {"$sum": 1}}},
        ]
        return [{"ticker": r["_id"]["t"], "date": r["_id"]["d"], "count": r["n"]}
                async for r in self._coll.aggregate(pipeline)]


class MultiMongoNewsSource:
    """News spread over one MongoDB collection per vendor (``news_benzinga``,
    ``news_tushare``…), read as one source: each query runs on every
    collection and the results are merged in (time, id) order, so limits and
    cursors behave as with a single collection. A document is found by id
    through its vendor's prefix (``bz_``, ``ts_``)."""

    kind = "mongo"

    def __init__(self, mongo_uri: str, db_name: str, collections: list[tuple[str, str]],
                 prefixes: Optional[dict[str, str]] = None):
        self.collections = collections
        self._parts = [(sid, MongoNewsSource(mongo_uri, db_name, coll)) for sid, coll in collections]
        self._prefixes = prefixes or {}

    async def connect(self):
        for _, p in self._parts:
            await p.connect()

    async def close(self):
        for _, p in self._parts:
            await p.close()

    @property
    def available(self) -> bool:
        return any(p.available for _, p in self._parts)

    def _live(self) -> list[MongoNewsSource]:
        return [p for _, p in self._parts if p.available]

    @staticmethod
    def _merge(lists: list[list[Event]], limit: int) -> list[Event]:
        out = [e for lst in lists for e in lst]
        out.sort(key=lambda e: (e.time_utc, e.event_id))
        return out[:limit]

    async def get_freshness(self) -> Optional[str]:
        vals = [v for p in self._live() if (v := await p.get_freshness())]
        return max(vals) if vals else None

    async def query_window(self, start_utc, end_utc, tickers, limit, cursor, now_utc,
                           min_content: Optional[str] = None) -> list[Event]:
        lists = await asyncio.gather(*(p.query_window(start_utc, end_utc, tickers, limit, cursor, now_utc,
                                                      min_content=min_content) for p in self._live()))
        return self._merge(list(lists), limit)

    async def search_news(self, start_utc, end_utc, tickers, keyword, publisher, limit, cursor,
                          now_utc, warnings: Optional[list[str]] = None,
                          min_content: Optional[str] = None) -> list[Event]:
        # the collections are searched at once: a slow one does not hold up the others
        lists = await asyncio.gather(*(p.search_news(start_utc, end_utc, tickers, keyword, publisher, limit, cursor,
                                                     now_utc, warnings=warnings, min_content=min_content)
                                       for p in self._live()))
        return self._merge(list(lists), limit)

    async def get_by_id(self, news_id: str) -> Optional[dict]:
        first = [p for sid, p in self._parts if self._prefixes.get(sid) and news_id.startswith(self._prefixes[sid])]
        for p in first + [p for _, p in self._parts if p not in first]:
            if p.available and (doc := await p.get_by_id(news_id)) is not None:
                return doc
        return None

    def _to_event(self, doc: dict, now_utc: datetime) -> Event:
        return news_doc_to_event(doc, now_utc)

    async def info(self) -> dict:
        parts = [await p.info() for p in self._live()]
        latest = [x["latest_timestamp"] for x in parts if x["latest_timestamp"]]
        return {"latest_timestamp": max(latest) if latest else None,
                "record_count": sum(x["record_count"] for x in parts),
                "unique_keys": sum(x["unique_keys"] for x in parts),   # tickers rarely span vendors
                "collections": [c for _, c in self.collections]}

    async def stats(self, since: datetime) -> dict:
        parts = [await p.stats(since) for p in self._live()]
        if not parts:
            return {"total_count": 0, "date_range": {"earliest": None, "latest": None}, "daily_counts": [],
                    "top_tickers": [], "top_publishers": [], "duplicate_stats": {"by_url": _rate(0, 0), "by_title": _rate(0, 0)}}

        def add(key: str, field: str, limit: Optional[int] = None) -> list[dict]:
            acc: dict[str, int] = {}
            for x in parts:
                for r in x[key]:
                    acc[r[field]] = acc.get(r[field], 0) + r["count"]
            rows = [{field: k, "count": v} for k, v in acc.items()]
            rows.sort(key=(lambda r: r[field]) if limit is None else (lambda r: -r["count"]))
            return rows if limit is None else rows[:limit]

        firsts = [x["date_range"]["earliest"] for x in parts if x["date_range"]["earliest"]]
        lasts = [x["date_range"]["latest"] for x in parts if x["date_range"]["latest"]]

        def dup(f: str) -> dict:
            return _rate(sum(x["duplicate_stats"][f]["total"] for x in parts),
                         sum(x["duplicate_stats"][f]["unique"] for x in parts))

        return {"total_count": sum(x["total_count"] for x in parts),
                "date_range": {"earliest": min(firsts) if firsts else None, "latest": max(lasts) if lasts else None},
                "daily_counts": add("daily_counts", "date"), "top_tickers": add("top_tickers", "ticker", 20),
                "top_publishers": add("top_publishers", "publisher", 10),
                "duplicate_stats": {"by_url": dup("by_url"), "by_title": dup("by_title")}}

    async def count(self, start: datetime, end: datetime, tickers: Optional[list[str]]) -> int:
        return sum([await p.count(start, end, tickers) for p in self._live()])

    async def iter_docs(self, start: datetime, end: datetime, tickers: Optional[list[str]], limit: int):
        docs = []
        for p in self._live():
            docs += [d async for d in p.iter_docs(start, end, tickers, limit)]
        docs.sort(key=lambda d: (d.get("published_utc") or datetime.min, str(d.get("_id"))))
        for d in docs[:limit]:
            yield d

    async def daily_counts(self, start: datetime, end: datetime, tickers: list[str]) -> list[dict]:
        acc: dict[tuple[str, str], int] = {}
        for p in self._live():
            for r in await p.daily_counts(start, end, tickers):
                acc[(r["ticker"], r["date"])] = acc.get((r["ticker"], r["date"]), 0) + r["count"]
        return [{"ticker": t, "date": d, "count": n} for (t, d), n in acc.items()]


# =====================================================================
# SQLiteNewsSource
# =====================================================================



class SQLiteNewsSource:
    """News from a SQLite file with :data:`NEWS_SCHEMA` (same interface as Mongo)."""

    kind = "sqlite"

    def __init__(self, db_path: str):
        self._path = db_path
        self._db: Optional[Any] = None

    async def connect(self):
        import aiosqlite
        if not os.path.isfile(self._path):
            logger.warning("news DB %s missing; news source unavailable", self._path)
            return
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        logger.info("News DB (sqlite) connected: %s", self._path)

    async def close(self):
        if self._db:
            await self._db.close()

    @property
    def available(self) -> bool:
        return self._db is not None

    @staticmethod
    def _iso(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).isoformat()

    def _doc(self, row) -> dict:
        r = dict(row)
        return {
            "_id": r["id"],
            "published_utc": _parse_utc(r["published_utc"]),
            "title": r.get("title") or "",
            "description": r.get("description"),
            "article_url": r.get("article_url"),
            "author": r.get("author"),
            "publisher": {"name": r.get("publisher")} if r.get("publisher") else None,
            "tickers": json.loads(r.get("tickers") or "[]"),
            "keywords": json.loads(r.get("keywords") or "[]"),
            "image_url": r.get("image_url"),
            "insights": json.loads(r["insights"]) if r.get("insights") else None,
            "source": r.get("source"),
        }

    def _where(self, start, end, tickers, keyword=None, publisher=None, cursor=None, min_content=None):
        sql = " FROM news WHERE published_utc >= ? AND published_utc < ?"
        args: list[Any] = [self._iso(start), self._iso(end)]
        if tickers:
            ph = ",".join("?" for _ in tickers)
            sql += f" AND id IN (SELECT news_id FROM news_tickers WHERE ticker IN ({ph}))"
            args += [t.upper() for t in tickers]
        if keyword:
            sql += " AND title LIKE ? ESCAPE '\\'"
            args.append("%" + keyword.replace("%", "\\%").replace("_", "\\_") + "%")
        if publisher:
            sql += " AND publisher LIKE ?"
            args.append(f"%{publisher}%")
        levels = _levels(min_content)
        if levels is not None:     # no article text in this schema: a summary is the most there is
            sql += " AND 0" if levels == ["full"] else " AND coalesce(trim(description), '') != ''"
        if cursor:
            ct = self._iso(_parse_utc(cursor[0]))
            cid = cursor[1].removeprefix("news_")
            sql += " AND (published_utc > ? OR (published_utc = ? AND id > ?))"
            args += [ct, ct, cid]
        return sql, args

    async def _events(self, sql: str, args: list, now_utc: datetime) -> list[Event]:
        out = []
        async with self._db.execute(sql, args) as cur:
            async for row in cur:
                out.append(news_doc_to_event(self._doc(row), now_utc))
        return out

    async def get_freshness(self) -> Optional[str]:
        if not self.available:
            return None
        async with self._db.execute("SELECT MAX(published_utc) FROM news") as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def query_window(self, start_utc, end_utc, tickers, limit, cursor, now_utc,
                           min_content: Optional[str] = None) -> list[Event]:
        if not self.available:
            return []
        where, args = self._where(start_utc, _news_end(end_utc, now_utc), tickers, cursor=cursor,
                                  min_content=min_content)
        return await self._events("SELECT *" + where + " ORDER BY published_utc, id LIMIT ?",
                                  args + [limit], now_utc)

    async def search_news(self, start_utc, end_utc, tickers, keyword, publisher, limit, cursor,
                          now_utc, warnings: Optional[list[str]] = None,
                          min_content: Optional[str] = None) -> list[Event]:
        if not self.available:
            return []
        where, args = self._where(start_utc, _news_end(end_utc, now_utc), tickers, keyword, publisher, cursor,
                                  min_content)
        return await self._events("SELECT *" + where + " ORDER BY published_utc, id LIMIT ?",
                                  args + [limit], now_utc)

    async def get_by_id(self, news_id: str) -> Optional[dict]:
        if not self.available:
            return None
        async with self._db.execute("SELECT * FROM news WHERE id = ?", [news_id]) as cur:
            row = await cur.fetchone()
            return self._doc(row) if row else None

    def _to_event(self, doc: dict, now_utc: datetime) -> Event:
        return news_doc_to_event(doc, now_utc)

    async def info(self) -> dict:
        out = {"latest_timestamp": None, "record_count": 0, "unique_keys": 0}
        if not self.available:
            return out
        async with self._db.execute("SELECT MAX(published_utc), COUNT(*) FROM news") as cur:
            latest, n = await cur.fetchone()
        async with self._db.execute("SELECT COUNT(DISTINCT ticker) FROM news_tickers") as cur:
            (k,) = await cur.fetchone()
        out.update(latest_timestamp=latest, record_count=n, unique_keys=k)
        return out

    async def stats(self, since: datetime) -> dict:
        s = self._iso(since)

        async def rows(sql: str, args=(s,)):
            async with self._db.execute(sql, list(args)) as cur:
                return await cur.fetchall()

        (total, first, last), = await rows(
            "SELECT COUNT(*), MIN(published_utc), MAX(published_utc) FROM news WHERE published_utc >= ?")
        daily = await rows("SELECT substr(published_utc, 1, 10) d, COUNT(*) FROM news "
                           "WHERE published_utc >= ? GROUP BY d ORDER BY d")
        tickers = await rows("SELECT t.ticker, COUNT(*) c FROM news_tickers t JOIN news n ON n.id = t.news_id "
                             "WHERE n.published_utc >= ? GROUP BY t.ticker ORDER BY c DESC LIMIT 20")
        pubs = await rows("SELECT publisher, COUNT(*) c FROM news WHERE published_utc >= ? "
                          "GROUP BY publisher ORDER BY c DESC LIMIT 10")
        (u_url,), = await rows("SELECT COUNT(DISTINCT article_url) FROM news WHERE published_utc >= ?")
        (u_title,), = await rows("SELECT COUNT(DISTINCT title) FROM news WHERE published_utc >= ?")
        return {
            "total_count": total,
            "date_range": {"earliest": first, "latest": last},
            "daily_counts": [{"date": d, "count": c} for d, c in daily],
            "top_tickers": [{"ticker": t, "count": c} for t, c in tickers],
            "top_publishers": [{"publisher": p, "count": c} for p, c in pubs],
            "duplicate_stats": {"by_url": _rate(total, u_url), "by_title": _rate(total, u_title)},
        }

    async def count(self, start: datetime, end: datetime, tickers: Optional[list[str]]) -> int:
        where, args = self._where(start, end, tickers)
        async with self._db.execute("SELECT COUNT(*)" + where, args) as cur:
            return (await cur.fetchone())[0]

    async def daily_counts(self, start: datetime, end: datetime, tickers: list[str]) -> list[dict]:
        """Articles per (ticker, US/Eastern date) in ``[start, end)``."""
        ph = ",".join("?" for _ in tickers)
        sql = (f"SELECT t.ticker, n.published_utc FROM news n JOIN news_tickers t ON t.news_id = n.id "
               f"WHERE t.ticker IN ({ph}) AND n.published_utc >= ? AND n.published_utc < ?")
        counts: dict[tuple[str, str], int] = {}
        async with self._db.execute(sql, [*tickers, self._iso(start), self._iso(end)]) as cur:
            async for t, pub in cur:
                key = (t, _parse_utc(pub).astimezone(EST).date().isoformat())
                counts[key] = counts.get(key, 0) + 1
        return [{"ticker": t, "date": d, "count": n} for (t, d), n in sorted(counts.items())]

    async def iter_docs(self, start: datetime, end: datetime, tickers: Optional[list[str]], limit: int):
        where, args = self._where(start, end, tickers)
        async with self._db.execute("SELECT *" + where + " ORDER BY published_utc, id LIMIT ?",
                                    args + [limit]) as cur:
            async for row in cur:
                yield self._doc(row)


# =====================================================================
# SQLiteEarningsSource
# =====================================================================

class SQLiteEarningsSource:
    def __init__(self, db_path: str):
        self._path = db_path
        self._db: Optional[Any] = None

    async def connect(self):
        import aiosqlite
        if not os.path.isfile(self._path):
            logger.warning("Earnings DB %s missing; source unavailable", self._path)
            return
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        logger.info("Earnings DB connected: %s", self._path)

    async def close(self):
        if self._db:
            await self._db.close()

    @property
    def available(self) -> bool:
        return self._db is not None

    async def get_freshness(self) -> Optional[str]:
        if not self.available:
            return None
        async with self._db.execute("SELECT MAX(last_updated) FROM earnings") as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def query_window(
        self,
        start_utc: datetime,
        end_utc: datetime,
        tickers: Optional[list[str]],
        limit: int,
        cursor: Optional[tuple[str, str]],
        now_utc: Optional[datetime] = None,
    ) -> list[Event]:
        if not self.available:
            return []
        # Convert UTC window to EST date range for the query
        start_est = start_utc.astimezone(EST)
        end_est = end_utc.astimezone(EST)
        start_date = start_est.strftime("%Y-%m-%d")
        # Widen by 1 day to catch edge cases around midnight
        end_date = (end_est + timedelta(days=1)).strftime("%Y-%m-%d")

        sql = "SELECT * FROM earnings WHERE date >= ? AND date <= ?"
        params: list[Any] = [start_date, end_date]

        if tickers:
            placeholders = ",".join("?" for _ in tickers)
            sql += f" AND ticker IN ({placeholders})"
            params.extend([t.upper() for t in tickers])

        sql += " ORDER BY date ASC, time ASC, benzinga_id ASC"
        sql += " LIMIT ?"
        params.append(limit)

        events = []
        async with self._db.execute(sql, params) as cur:
            async for row in cur:
                ev = self._to_event(dict(row), now_utc)
                if ev is None:
                    continue
                # Apply precise UTC filter
                ev_time = _parse_utc(ev.time_utc)
                if ev_time < start_utc or ev_time >= end_utc:
                    continue
                # Apply cursor filter
                if cursor:
                    if (ev.time_utc, ev.event_id) <= cursor:
                        continue
                events.append(ev)
        return events

    async def get_by_id(self, benzinga_id: str, now_utc: Optional[datetime] = None) -> Optional[Event]:
        if not self.available:
            return None
        sql = "SELECT * FROM earnings WHERE benzinga_id = ?"
        async with self._db.execute(sql, [benzinga_id]) as cur:
            row = await cur.fetchone()
            if row:
                return self._to_event(dict(row), now_utc)
        return None

    async def query_by_dates(
        self,
        start_date: str,
        end_date: str,
        tickers: Optional[list[str]],
        min_importance: int,
        limit: int,
        cursor: Optional[tuple[str, str]],
        now_utc: Optional[datetime] = None,
    ) -> list[Event]:
        if not self.available:
            return []
        sql = "SELECT * FROM earnings WHERE date >= ? AND date <= ? AND (importance >= ? OR importance IS NULL)"
        params: list[Any] = [start_date, end_date, min_importance]

        if tickers:
            placeholders = ",".join("?" for _ in tickers)
            sql += f" AND ticker IN ({placeholders})"
            params.extend([t.upper() for t in tickers])

        if cursor:
            # cursor is (time_utc_iso, event_id)
            sql += " AND (date > ? OR (date = ? AND benzinga_id > ?))"
            cursor_id = cursor[1].removeprefix("earn_")
            # Extract date from cursor time
            cursor_date = cursor[0][:10]
            params.extend([cursor_date, cursor_date, cursor_id])

        sql += " ORDER BY date ASC, time ASC, benzinga_id ASC LIMIT ?"
        params.append(limit)

        events = []
        async with self._db.execute(sql, params) as cur:
            async for row in cur:
                ev = self._to_event(dict(row), now_utc)
                if ev:
                    events.append(ev)
        return events

    def _to_event(self, row: dict, now_utc: Optional[datetime] = None) -> Optional[Event]:
        date_str = row.get("date")
        time_str = row.get("time")
        if not date_str:
            return None

        # Build UTC timestamp from EST date + time
        try:
            if time_str:
                dt_est = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            else:
                dt_est = datetime.strptime(date_str, "%Y-%m-%d")
            dt_est = dt_est.replace(tzinfo=EST)
            dt_utc = dt_est.astimezone(timezone.utc)
        except (ValueError, TypeError):
            dt_utc = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        # A report without a time is treated as known only after its ET day ends.
        known_from = dt_utc if time_str else dt_utc + timedelta(days=1)
        status_val = row.get("date_status")
        occurred = status_val == "confirmed" and _known_at(known_from, now_utc)
        status = EventStatus.OCCURRED if occurred else EventStatus.SCHEDULED

        ticker = row.get("ticker") or ""
        fp = row.get("fiscal_period") or ""
        fy = row.get("fiscal_year") or ""

        return Event(
            event_id=f"earn_{row['benzinga_id']}",
            event_type=EventType.EARNINGS,
            title=f"{ticker} {fp} FY{fy} Earnings".strip(),
            time_utc=dt_utc.isoformat(),
            importance=_earnings_importance(row.get("importance")),
            status=status,
            tickers=[ticker] if ticker else [],
            country="US",
            snippet=build_earnings_snippet(row, occurred=occurred),
            payload=build_earnings_payload(row, occurred=occurred),
            source="benzinga",
            source_id=row["benzinga_id"],
        )


# =====================================================================
# SQLiteEconEventsSource
# =====================================================================

class SQLiteEconEventsSource:
    def __init__(self, db_path: str):
        self._path = db_path
        self._db: Optional[Any] = None

    async def connect(self):
        import aiosqlite
        if not os.path.isfile(self._path):
            logger.warning("Econ Events DB %s missing; source unavailable", self._path)
            return
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        logger.info("Econ Events DB connected: %s", self._path)

    async def close(self):
        if self._db:
            await self._db.close()

    @property
    def available(self) -> bool:
        return self._db is not None

    async def get_freshness(self) -> Optional[str]:
        if not self.available:
            return None
        async with self._db.execute(
            "SELECT MAX(fetched_at) FROM econ_events WHERE country = 'United States'"
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def query_window(
        self,
        start_utc: datetime,
        end_utc: datetime,
        limit: int,
        cursor: Optional[tuple[str, str]],
        now_utc: Optional[datetime] = None,
    ) -> list[Event]:
        if not self.available:
            return []
        # gmt_time is already UTC. We query by date range (widen by 1 day for safety).
        start_date = start_utc.strftime("%Y-%m-%d")
        end_date = (end_utc + timedelta(days=1)).strftime("%Y-%m-%d")

        sql = (
            "SELECT * FROM econ_events "
            "WHERE country = 'United States' AND date >= ? AND date <= ? "
            "ORDER BY date ASC, gmt_time ASC, event_id ASC "
            "LIMIT ?"
        )
        params: list[Any] = [start_date, end_date, limit]

        events = []
        async with self._db.execute(sql, params) as cur:
            async for row in cur:
                ev = self._to_event(dict(row), now_utc)
                if ev is None:
                    continue
                ev_time = _parse_utc(ev.time_utc)
                if ev_time < start_utc or ev_time >= end_utc:
                    continue
                if cursor and (ev.time_utc, ev.event_id) <= cursor:
                    continue
                events.append(ev)
        return events

    async def get_by_id(self, event_id: str, now_utc: Optional[datetime] = None) -> Optional[Event]:
        if not self.available:
            return None
        sql = "SELECT * FROM econ_events WHERE event_id = ?"
        async with self._db.execute(sql, [event_id]) as cur:
            row = await cur.fetchone()
            if row:
                return self._to_event(dict(row), now_utc)
        return None

    async def query_by_dates(
        self,
        start_date: str,
        end_date: str,
        min_importance: Optional[Importance],
        limit: int,
        cursor: Optional[tuple[str, str]],
        now_utc: Optional[datetime] = None,
    ) -> list[Event]:
        if not self.available:
            return []
        sql = (
            "SELECT * FROM econ_events "
            "WHERE country = 'United States' AND date >= ? AND date <= ?"
        )
        params: list[Any] = [start_date, end_date]

        if cursor:
            cursor_id = cursor[1].removeprefix("econ_")
            cursor_date = cursor[0][:10]
            sql += " AND (date > ? OR (date = ? AND event_id > ?))"
            params.extend([cursor_date, cursor_date, cursor_id])

        sql += " ORDER BY date ASC, gmt_time ASC, event_id ASC LIMIT ?"
        params.append(limit)

        events = []
        async with self._db.execute(sql, params) as cur:
            async for row in cur:
                ev = self._to_event(dict(row), now_utc)
                if ev is None:
                    continue
                if min_importance:
                    imp_order = {Importance.LOW: 0, Importance.MEDIUM: 1, Importance.HIGH: 2}
                    if imp_order.get(ev.importance, 0) < imp_order.get(min_importance, 0):
                        continue
                events.append(ev)
        return events

    def _to_event(self, row: dict, now_utc: Optional[datetime] = None) -> Optional[Event]:
        date_str = row.get("date")
        if not date_str:
            return None

        gmt_time = row.get("gmt_time") or "00:00"
        try:
            dt_utc = datetime.strptime(f"{date_str} {gmt_time}", "%Y-%m-%d %H:%M")
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            dt_utc = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        # Collectors store blanks as "&nbsp;" or " " before the release.
        has_actual = bool(_clean_html(row.get("actual") or ""))
        occurred = has_actual and _known_at(dt_utc, now_utc)
        status = EventStatus.OCCURRED if occurred else EventStatus.SCHEDULED

        return Event(
            event_id=f"econ_{row['event_id']}",
            event_type=EventType.MACRO_CALENDAR,
            title=row.get("event_name") or "Unknown Event",
            time_utc=dt_utc.isoformat(),
            importance=_infer_econ_importance(row.get("event_name") or ""),
            status=status,
            tickers=[],
            country="US",
            snippet=build_econ_snippet(row, occurred=occurred),
            payload=build_econ_payload(row, occurred=occurred),
            source="nasdaq_econ",
            source_id=row["event_id"],
        )


# =====================================================================
# DataSourceManager
# =====================================================================

class DataSourceManager:
    def __init__(
        self,
        mongo_uri: str,
        mongo_db: str,
        mongo_collection: str,
        earnings_db: str,
        econ_events_db: str,
        news_backend: str = "auto",
        news_db: Optional[str] = None,
        news_collections: Optional[list[tuple[str, str]]] = None,
        news_prefixes: Optional[dict[str, str]] = None,
    ):
        """``news_backend``: ``mongo``, ``sqlite`` or ``auto`` (SQLite when
        ``news_db`` exists, MongoDB otherwise)."""
        use_sqlite = news_backend == "sqlite" or (
            news_backend == "auto" and news_db is not None and os.path.isfile(news_db))
        if use_sqlite:
            if not news_db:
                raise ValueError("news_backend=sqlite needs news_db")
            self.news = SQLiteNewsSource(news_db)
        elif news_collections and len(news_collections) > 1:
            self.news = MultiMongoNewsSource(mongo_uri, mongo_db, news_collections, news_prefixes)
        else:
            coll = news_collections[0][1] if news_collections else mongo_collection
            self.news = MongoNewsSource(mongo_uri, mongo_db, coll)
        self.earnings = SQLiteEarningsSource(earnings_db)
        self.econ = SQLiteEconEventsSource(econ_events_db)

    async def connect(self):
        await self.news.connect()
        await self.earnings.connect()
        await self.econ.connect()

    async def close(self):
        await self.news.close()
        await self.earnings.close()
        await self.econ.close()

    async def keep_connected(self, interval: float = 30.0):
        """Reconnect sources that were down at start or dropped (e.g. MongoDB
        restarted). Runs until cancelled."""
        import asyncio
        while True:
            await asyncio.sleep(interval)
            for src in (self.news, self.earnings, self.econ):
                if not src.available:
                    try:
                        await src.connect()
                    except Exception as e:  # noqa: BLE001
                        logger.debug("reconnect failed for %s: %s", type(src).__name__, e)

    async def get_freshness(self) -> dict:
        return {
            "news": await self.news.get_freshness(),
            "earnings": await self.earnings.get_freshness(),
            "econ_events": await self.econ.get_freshness(),
        }
