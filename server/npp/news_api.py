from flask import Blueprint, request, jsonify
import sqlite3
import json
import os
import math
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from dateutil import parser as date_parser

from config.settings import DATABASE_CONFIG

news_bp = Blueprint("news_api", __name__)


def _get_conn(path: str):
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _parse_timestamp(ts_in) -> Optional[datetime]:
    """Robust timestamp parsing: accept int/float (unix), ISO strings, or dateutil-parsable strings."""
    if ts_in is None:
        return datetime.utcnow()
    try:
        if isinstance(ts_in, (int, float)):
            return datetime.utcfromtimestamp(int(ts_in))
        if isinstance(ts_in, str) and ts_in.isdigit():
            return datetime.utcfromtimestamp(int(ts_in))
        # dateutil handles many formats including ISO with timezone
        dt = date_parser.parse(ts_in)
        # convert to naive UTC for comparisons
        if dt.tzinfo is not None:
            try:
                return dt.astimezone(tz=None).replace(tzinfo=None)
            except Exception:
                return dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _keyword_score(text: str, ticker: str) -> float:
    """Simple keyword-based score: higher if ticker appears in title/content (word boundary), bonus if in uppercase title."""
    if not text:
        return 0.0
    t = text
    # word boundary match for ticker (case-insensitive)
    try:
        if re.search(rf"\b{re.escape(ticker)}\b", t, flags=re.IGNORECASE):
            return 1.0
    except re.error:
        pass
    return 0.0


def _score_article(article: Dict[str, Any], target_ts: datetime, ticker: str) -> float:
    """Combine time-distance and keyword match into a single relevance score.
    - time component: exponential decay of seconds distance
    - keyword component: binary bonus
    """
    time_score = 0.0
    try:
        ts_str = article.get("timestamp")
        if ts_str:
            # try convert timestamp string to datetime
            ts = _parse_timestamp(ts_str)
            if ts:
                sec = abs((ts - target_ts).total_seconds())
                # decay factor: closer in time -> score closer to 1; use half-life ~ 6 hours
                half_life = 6 * 3600
                time_score = math.exp(-sec / half_life)
    except Exception:
        time_score = 0.0

    title = article.get("title") or ""
    content = article.get("content") or ""
    kw = max(_keyword_score(title, ticker) * 1.5, _keyword_score(content, ticker))

    # combine: weighted sum
    return float(0.7 * time_score + 0.3 * kw)


@news_bp.route("/health", methods=["GET"])
def health():
    """Return database status: tickers covered and total news records."""
    raw_db = DATABASE_CONFIG.get("raw_news_db")
    trading_db = DATABASE_CONFIG.get("trading_day_db")

    result = {"raw_news_db": raw_db, "trading_day_db": trading_db}

    # raw news stats
    try:
        conn = _get_conn(raw_db)
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as c FROM raw_news")
            total = cur.fetchone()[0]
            cur.execute("SELECT DISTINCT company_symbol FROM raw_news WHERE company_symbol IS NOT NULL")
            tickers = [r[0] for r in cur.fetchall() if r[0]]
            conn.close()
        else:
            total = 0
            tickers = []
    except Exception:
        total = 0
        tickers = []

    result.update({"total_news": int(total), "tickers": tickers})

    # trading day stats
    try:
        conn2 = _get_conn(trading_db)
        if conn2:
            cur2 = conn2.cursor()
            cur2.execute("SELECT COUNT(*) as c FROM trading_days")
            bundles = cur2.fetchone()[0]
            conn2.close()
        else:
            bundles = 0
    except Exception:
        bundles = 0

    result.update({"trading_day_bundles": int(bundles)})

    return jsonify({"success": True, "status": result})


@news_bp.route("/news/company", methods=["GET", "POST"])
def news_company():
    """Return news articles relevant to a company ticker.

    Accepts JSON body (POST) or query params (GET):
      - ticker (required)
      - timestamp (optional, ISO or unix seconds)
      - limit (optional, default 20)
      - offset (optional, default 0)

    Returns ranked articles with a simple relevance `score`.
    """
    if request.method == "POST":
        payload = request.get_json(force=True) or {}
        ticker = payload.get("ticker")
        ts_in = payload.get("timestamp")
        limit = int(payload.get("limit", 20))
        offset = int(payload.get("offset", 0))
    else:
        ticker = request.args.get("ticker")
        ts_in = request.args.get("timestamp")
        limit = int(request.args.get("limit", 20))
        offset = int(request.args.get("offset", 0))

    if not ticker:
        return jsonify({"success": False, "message": "ticker required"}), 400

    target_ts = _parse_timestamp(ts_in)
    if target_ts is None:
        return jsonify({"success": False, "message": "invalid timestamp format"}), 400

    raw_db = DATABASE_CONFIG.get("raw_news_db")
    try:
        conn = _get_conn(raw_db)
        if not conn:
            return jsonify({"success": False, "message": "raw database not available"}), 500
        cur = conn.cursor()

        # Fetch candidate articles near the timestamp (use a wider limit to allow re-ranking)
        candidate_limit = max(limit * 5, 50)
        query = (
            "SELECT id, source, title, content, timestamp, company_symbol, url, raw_data, "
            "ABS(strftime('%s', timestamp) - ?) as distance "
            "FROM raw_news WHERE LOWER(company_symbol) = LOWER(?) "
            "ORDER BY distance ASC LIMIT ?"
        )
        cur.execute(query, (int(target_ts.timestamp()), ticker, candidate_limit))
        rows = cur.fetchall()

        articles: List[Dict[str, Any]] = []
        for r in rows:
            try:
                rawd = json.loads(r[7]) if r[7] else {}
            except Exception:
                rawd = {}
            art = {
                "id": r[0],
                "source": r[1],
                "title": r[2],
                "content": r[3],
                "timestamp": r[4],
                "company_symbol": r[5],
                "url": r[6],
                "raw_data": rawd,
            }
            art["_distance"] = r[8]
            art["score"] = _score_article(art, target_ts, ticker)
            articles.append(art)

        conn.close()

        # sort by score desc, then by distance asc
        articles.sort(key=lambda x: (-x.get("score", 0.0), x.get("_distance", 1e12)))

        # pagination
        sliced = articles[offset : offset + limit]
        # remove internal distance field from response
        for a in sliced:
            a.pop("_distance", None)

        return jsonify({
            "success": True,
            "ticker": ticker,
            "target_timestamp": target_ts.isoformat(),
            "limit": limit,
            "offset": offset,
            "total_candidates": len(articles),
            "articles": sliced,
        })

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@news_bp.route("/news/overall", methods=["GET"])
def news_overall():
    """Return a summary of current market situation using trading_day bundles.
    Query params: days (int, optional)
    """
    days = int(request.args.get("days", 7))
    trading_db = DATABASE_CONFIG.get("trading_day_db")
    try:
        conn = _get_conn(trading_db)
        cur = conn.cursor()
        cur.execute("SELECT trading_date, global_events, has_major_events FROM trading_days ORDER BY trading_date DESC LIMIT ?", (days,))
        rows = cur.fetchall()
        conn.close()

        summaries = []
        for r in rows:
            date = r[0]
            try:
                ge = json.loads(r[1]) if r[1] else []
            except Exception:
                ge = []
            summaries.append({"trading_date": date, "has_major_events": bool(r[2]), "global_events": ge})

        return jsonify({"success": True, "summary": summaries})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# Earnings/calendar endpoints (stubs until earnings parser implemented)
@news_bp.route("/calendar/next_earnings", methods=["GET", "POST"])
def next_earnings():
    data = request.get_json(silent=True) or {}
    date = data.get("date") or request.args.get("date")
    ticker = data.get("ticker") or request.args.get("ticker")
    if not date:
        # default to today
        date = datetime.utcnow().date().isoformat()

    try:
        from data_sources.nasdaq_earnings import get_next_earnings

        res = get_next_earnings(date, ticker=ticker, limit=1)
        if res:
            return jsonify({"success": True, "next": res[0]})
        else:
            return jsonify({"success": True, "next": None})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@news_bp.route("/calendar/history_earnings", methods=["GET", "POST"])
def history_earnings():
    data = request.get_json(silent=True) or {}
    date = data.get("date") or request.args.get("date")
    n = int(data.get("n", request.args.get("n", 10)))
    if not date:
        date = datetime.utcnow().date().isoformat()

    try:
        from data_sources.nasdaq_earnings import get_history

        res = get_history(date, n=n)
        return jsonify({"success": True, "history": res})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@news_bp.route("/calendar/market", methods=["GET", "POST"])
def calendar_market():
    data = request.get_json(silent=True) or {}
    date = data.get("date") or request.args.get("date")
    n = int(data.get("n", request.args.get("n", 7)))
    if not date:
        date = datetime.utcnow().date().isoformat()

    try:
        from data_sources.nasdaq_earnings import get_market_between

        # compute end date as date + n days
        try:
            base = datetime.fromisoformat(date).date()
        except Exception:
            base = datetime.utcnow().date()
        end_date = (base + timedelta(days=n)).isoformat()
        res = get_market_between(base.isoformat(), end_date)
        # return simplified list of dicts
        simplified = [{"symbol": r["symbol"], "company": r["company"], "report_date": r["report_date"]} for r in res]
        return jsonify({"success": True, "market": simplified})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
