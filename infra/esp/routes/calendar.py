import logging
from datetime import datetime, timedelta, date, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from models import EconCalendarRequest, EarningsCalendarRequest

logger = logging.getLogger("esp.calendar")

router = APIRouter(tags=["calendar"])


@router.post("/esp/calendar/econ")
async def econ_calendar(req: EconCalendarRequest, request: Request):
    svc = request.app.state.event_service
    result = await svc.query_econ_calendar(req)
    return result.model_dump()


@router.post("/esp/calendar/earnings")
async def earnings_calendar(req: EarningsCalendarRequest, request: Request):
    svc = request.app.state.event_service
    result = await svc.query_earnings_calendar(req)
    return result.model_dump()


@router.get("/esp/calendar/coverage")
async def calendar_coverage(request: Request, days: int = Query(default=30, ge=1, le=365)):
    ds = request.app.state.data_sources

    # If both DBs are unavailable, return 503
    if ds.earnings._db is None and ds.econ._db is None:
        raise HTTPException(status_code=503, detail="Calendar databases unavailable")

    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")

    # Build set of weekdays in range for missing-date detection
    d_start = date.fromisoformat(start_date)
    d_end = date.fromisoformat(end_date)
    all_weekdays = set()
    d = d_start
    while d <= d_end:
        if d.weekday() < 5:  # Mon-Fri
            all_weekdays.add(d.isoformat())
        d += timedelta(days=1)

    result = {}

    # ── Earnings coverage ────────────────────────────────────────
    earnings_db = ds.earnings._db
    if earnings_db is not None:
        async with earnings_db.execute(
            "SELECT MIN(date) as min_date, MAX(date) as max_date, COUNT(*) as total FROM earnings WHERE date >= ? AND date <= ?",
            [start_date, end_date],
        ) as cur:
            row = await cur.fetchone()
            earn_min_date = row[0]
            earn_max_date = row[1]
            earn_total = row[2]

        # Daily counts
        earn_daily = []
        earn_daily_dates = set()
        async with earnings_db.execute(
            "SELECT date, COUNT(*) as cnt FROM earnings WHERE date >= ? AND date <= ? GROUP BY date ORDER BY date",
            [start_date, end_date],
        ) as cur:
            async for row in cur:
                earn_daily.append({"date": row[0], "count": row[1]})
                earn_daily_dates.add(row[0])

        earn_missing = sorted(all_weekdays - earn_daily_dates)

        # By importance
        earn_by_importance = {}
        async with earnings_db.execute(
            "SELECT CASE WHEN importance >= 4 THEN 'HIGH' WHEN importance >= 2 THEN 'MEDIUM' ELSE 'LOW' END AS level, COUNT(*) as cnt FROM earnings WHERE date >= ? AND date <= ? GROUP BY level ORDER BY cnt DESC",
            [start_date, end_date],
        ) as cur:
            async for row in cur:
                earn_by_importance[row[0]] = row[1]

        result["earnings"] = {
            "date_range": {"start": earn_min_date, "end": earn_max_date},
            "total_records": earn_total,
            "daily_counts": earn_daily,
            "missing_dates": earn_missing,
            "by_importance": earn_by_importance,
        }
    else:
        result["earnings"] = {"error": "Earnings database unavailable"}

    # ── Economic events coverage ─────────────────────────────────
    econ_db = ds.econ._db
    if econ_db is not None:
        async with econ_db.execute(
            "SELECT MIN(date) as min_date, MAX(date) as max_date, COUNT(*) as total FROM econ_events WHERE country = 'United States' AND date >= ? AND date <= ?",
            [start_date, end_date],
        ) as cur:
            row = await cur.fetchone()
            econ_min_date = row[0]
            econ_max_date = row[1]
            econ_total = row[2]

        # Daily counts
        econ_daily = []
        econ_daily_dates = set()
        async with econ_db.execute(
            "SELECT date, COUNT(*) as cnt FROM econ_events WHERE country = 'United States' AND date >= ? AND date <= ? GROUP BY date ORDER BY date",
            [start_date, end_date],
        ) as cur:
            async for row in cur:
                econ_daily.append({"date": row[0], "count": row[1]})
                econ_daily_dates.add(row[0])

        econ_missing = sorted(all_weekdays - econ_daily_dates)

        # By country (for US data)
        econ_by_country = {}
        async with econ_db.execute(
            "SELECT country, COUNT(*) as cnt FROM econ_events WHERE date >= ? AND date <= ? GROUP BY country ORDER BY cnt DESC",
            [start_date, end_date],
        ) as cur:
            async for row in cur:
                econ_by_country[row[0]] = row[1]

        # By event type (top 10)
        econ_by_type = []
        async with econ_db.execute(
            "SELECT event_name, COUNT(*) as cnt FROM econ_events WHERE country = 'United States' AND date >= ? AND date <= ? GROUP BY event_name ORDER BY cnt DESC LIMIT 10",
            [start_date, end_date],
        ) as cur:
            async for row in cur:
                econ_by_type.append({"event_type": row[0], "count": row[1]})

        result["econ_events"] = {
            "date_range": {"start": econ_min_date, "end": econ_max_date},
            "total_records": econ_total,
            "daily_counts": econ_daily,
            "missing_dates": econ_missing,
            "by_country": econ_by_country,
            "by_type_top10": econ_by_type,
        }
    else:
        result["econ_events"] = {"error": "Economic events database unavailable"}

    return result
