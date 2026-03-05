"""
Data source connectors for NPP.

Three async connectors that normalise raw rows into the canonical Event schema:
  - MongoNewsSource  (motor / MongoDB)
  - SQLiteEarningsSource  (aiosqlite)
  - SQLiteEconEventsSource (aiosqlite)
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Optional

import html as html_mod

from models import Event, EventType, EventStatus, Importance

logger = logging.getLogger("npp.data_sources")

EST = ZoneInfo("America/New_York")

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

class MongoNewsSource:
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
    ) -> list[Event]:
        if not self.available:
            return []

        query: dict[str, Any] = {
            "published_utc": {"$gte": start_utc, "$lt": end_utc},
        }
        if tickers:
            query["tickers"] = {"$in": [t.upper() for t in tickers]}
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
    ) -> list[Event]:
        if not self.available:
            return []

        query: dict[str, Any] = {
            "published_utc": {"$gte": start_utc, "$lt": end_utc},
        }
        if tickers:
            query["tickers"] = {"$in": [t.upper() for t in tickers]}
        if keyword:
            query["title"] = {"$regex": re.escape(keyword), "$options": "i"}
        if publisher:
            query["publisher.name"] = {"$regex": re.escape(publisher), "$options": "i"}
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
        )
        events = []
        async for doc in docs:
            events.append(self._to_event(doc, now_utc))
        return events

    async def get_by_id(self, news_id: str) -> Optional[dict]:
        if not self.available:
            return None
        return await self._coll.find_one({"_id": news_id})

    def _to_event(self, doc: dict, now_utc: datetime) -> Event:
        pub_utc = doc.get("published_utc")
        if isinstance(pub_utc, datetime):
            if pub_utc.tzinfo is None:
                pub_utc = pub_utc.replace(tzinfo=timezone.utc)
        else:
            pub_utc = _parse_utc(str(pub_utc)) if pub_utc else _utc_now()

        age_hours = (now_utc - pub_utc).total_seconds() / 3600
        event_type = EventType.BREAKING_NEWS if age_hours < 4 else EventType.DAILY_NEWS

        publisher = doc.get("publisher")
        pub_name = None
        if isinstance(publisher, dict):
            pub_name = publisher.get("name")

        return Event(
            event_id=f"news_{doc['_id']}",
            event_type=event_type,
            title=doc.get("title") or "",
            time_utc=pub_utc.isoformat(),
            importance=Importance.MEDIUM,
            status=EventStatus.OCCURRED,
            tickers=doc.get("tickers") or [],
            country="US",
            snippet=(doc.get("description") or "")[:200],
            payload={
                "article_url": doc.get("article_url"),
                "author": doc.get("author"),
                "publisher": pub_name,
                "keywords": doc.get("keywords") or [],
            },
            source="polygon_news",
            source_id=str(doc["_id"]),
        )


# =====================================================================
# SQLiteEarningsSource
# =====================================================================

class SQLiteEarningsSource:
    def __init__(self, db_path: str):
        self._path = db_path
        self._db: Optional[Any] = None

    async def connect(self):
        import aiosqlite
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        logger.info("Earnings DB connected: %s", self._path)

    async def close(self):
        if self._db:
            await self._db.close()

    async def get_freshness(self) -> Optional[str]:
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
    ) -> list[Event]:
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
                ev = self._to_event(dict(row))
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

    async def get_by_id(self, benzinga_id: str) -> Optional[Event]:
        sql = "SELECT * FROM earnings WHERE benzinga_id = ?"
        async with self._db.execute(sql, [benzinga_id]) as cur:
            row = await cur.fetchone()
            if row:
                return self._to_event(dict(row))
        return None

    async def query_by_dates(
        self,
        start_date: str,
        end_date: str,
        tickers: Optional[list[str]],
        min_importance: int,
        limit: int,
        cursor: Optional[tuple[str, str]],
    ) -> list[Event]:
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
                ev = self._to_event(dict(row))
                if ev:
                    events.append(ev)
        return events

    def _to_event(self, row: dict) -> Optional[Event]:
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

        status_val = row.get("date_status")
        status = EventStatus.OCCURRED if status_val == "confirmed" else EventStatus.SCHEDULED
        occurred = status == EventStatus.OCCURRED

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
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        logger.info("Econ Events DB connected: %s", self._path)

    async def close(self):
        if self._db:
            await self._db.close()

    async def get_freshness(self) -> Optional[str]:
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
    ) -> list[Event]:
        # gmt_time is already UTC. We query by date range (widen by 1 day for safety).
        start_date = start_utc.strftime("%Y-%m-%d")
        from datetime import timedelta
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
                ev = self._to_event(dict(row))
                if ev is None:
                    continue
                ev_time = _parse_utc(ev.time_utc)
                if ev_time < start_utc or ev_time >= end_utc:
                    continue
                if cursor and (ev.time_utc, ev.event_id) <= cursor:
                    continue
                events.append(ev)
        return events

    async def get_by_id(self, event_id: str) -> Optional[Event]:
        sql = "SELECT * FROM econ_events WHERE event_id = ?"
        async with self._db.execute(sql, [event_id]) as cur:
            row = await cur.fetchone()
            if row:
                return self._to_event(dict(row))
        return None

    async def query_by_dates(
        self,
        start_date: str,
        end_date: str,
        min_importance: Optional[Importance],
        limit: int,
        cursor: Optional[tuple[str, str]],
    ) -> list[Event]:
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
                ev = self._to_event(dict(row))
                if ev is None:
                    continue
                if min_importance:
                    imp_order = {Importance.LOW: 0, Importance.MEDIUM: 1, Importance.HIGH: 2}
                    if imp_order.get(ev.importance, 0) < imp_order.get(min_importance, 0):
                        continue
                events.append(ev)
        return events

    def _to_event(self, row: dict) -> Optional[Event]:
        date_str = row.get("date")
        if not date_str:
            return None

        gmt_time = row.get("gmt_time") or "00:00"
        try:
            dt_utc = datetime.strptime(f"{date_str} {gmt_time}", "%Y-%m-%d %H:%M")
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            dt_utc = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        has_actual = bool(row.get("actual") and str(row["actual"]).strip())
        status = EventStatus.OCCURRED if has_actual else EventStatus.SCHEDULED
        occurred = status == EventStatus.OCCURRED

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
    ):
        self.news = MongoNewsSource(mongo_uri, mongo_db, mongo_collection)
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

    async def get_freshness(self) -> dict:
        return {
            "news": await self.news.get_freshness(),
            "earnings": await self.earnings.get_freshness(),
            "econ_events": await self.econ.get_freshness(),
        }
