"""NASDAQ earnings fetcher and local cache.

This module provides functions to fetch NASDAQ earnings calendar for a given date,
parse the response and cache entries in a local sqlite DB (configured in settings).

Example API:
  fetch_and_cache_earnings(date_str: str) -> list[dict]
  get_earnings_on(date_str: str) -> list[dict]
  get_next_earnings(after_date: str, ticker: Optional[str]=None, limit=20) -> list[dict]
  get_history(before_date: str, n=20) -> list[dict]
  get_market_between(start_date: str, end_date: str) -> list[dict]

This implementation is defensive: it attempts to parse common JSON shapes from
`https://api.nasdaq.com/api/calendar/earnings?date={date}` and stores per-row raw data
so we can adapt later if the API shape changes.
"""
from __future__ import annotations

import sqlite3
import json
import requests
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from src.config.settings import DATABASE_CONFIG

NASDAQ_API = "https://api.nasdaq.com/api/calendar/earnings?date={date}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nasdaq.com/",
    "Origin": "https://www.nasdaq.com",
}

EARNINGS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS earnings (
    id TEXT PRIMARY KEY,
    symbol TEXT,
    company TEXT,
    report_date TEXT,
    time_of_day TEXT,
    raw_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def _get_conn():
    path = DATABASE_CONFIG.get("earnings_db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_db():
    conn = _get_conn()
    cur = conn.cursor()
    cur.executescript(EARNINGS_TABLE_SCHEMA)
    conn.commit()
    conn.close()


def _normalize_date(d: str) -> Optional[str]:
    if not d:
        return None
    try:
        # Try parse flexible date/time and return ISO date
        dt = datetime.fromisoformat(d)
        return dt.date().isoformat()
    except Exception:
        try:
            # Common format: '11/12/2025' or '2025-11-12'
            dt = datetime.strptime(d.split(" ")[0], "%m/%d/%Y")
            return dt.date().isoformat()
        except Exception:
            try:
                dt = datetime.strptime(d.split(" ")[0], "%Y-%m-%d")
                return dt.date().isoformat()
            except Exception:
                return None


def fetch_from_api(date_str: str) -> Optional[Dict[str, Any]]:
    url = NASDAQ_API.format(date=date_str)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        # Try normal JSON parse first
        try:
            return r.json()
        except Exception:
            # Some responses may include leading/trailing text; try to extract JSON object from body
            text = r.text
            import re

            m = re.search(r"(\{\s*\"data\"[\s\S]*\})", text)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    return None
            return None
    except Exception:
        return None


def parse_rows_from_response(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Defensive parsing: look for data.rows or data.calendarRows etc.
    if not resp:
        return []
    data = resp.get("data") or resp.get("payload") or resp
    rows = []
    if isinstance(data, dict):
        # Common shape: data -> rows
        if "rows" in data and isinstance(data["rows"], list):
            rows = data["rows"]
        elif "calendarRows" in data and isinstance(data["calendarRows"], list):
            rows = data["calendarRows"]
        elif "earnings" in data and isinstance(data["earnings"], list):
            rows = data["earnings"]
        else:
            # Try find first list value
            for v in data.values():
                if isinstance(v, list):
                    rows = v
                    break
    elif isinstance(data, list):
        rows = data

    # rows now is a list of row-like dicts; return as-is
    return rows


def _row_id(symbol: Optional[str], report_date: Optional[str], raw_row: Dict[str, Any]) -> str:
    key = f"{symbol or 'unknown'}|{report_date or 'unknown'}"
    # include a hash of raw_row to be safe
    try:
        h = abs(hash(json.dumps(raw_row, sort_keys=True))) % (10 ** 12)
        return f"{key}|{h}"
    except Exception:
        return key


def fetch_and_cache_earnings(date_str: str) -> List[Dict[str, Any]]:
    """Fetch NASDAQ earnings for date (YYYY-MM-DD or other formats) and cache them locally.

    Returns a list of parsed entries (may be empty).
    """
    ensure_db()
    resp = fetch_from_api(date_str)
    rows = parse_rows_from_response(resp)
    out: List[Dict[str, Any]] = []
    conn = _get_conn()
    cur = conn.cursor()

    for row in rows:
        # Attempt to extract symbol, company, report_date, time_of_day
        symbol = None
        company = None
        report_date = None
        time_of_day = None

        # Many responses have keys like 'symbol', 'company', 'time', 'reportDate'
        if isinstance(row, dict):
            symbol = row.get("symbol") or row.get("ticker") or row.get("Symbol")
            company = row.get("company") or row.get("Company") or row.get("companyName")
            report_date = row.get("reportDate") or row.get("date") or row.get("ReportDate") or row.get("report_date")
            time_of_day = row.get("time") or row.get("timeOfDay") or row.get("reportTime") or row.get("timeOfDayType")

        # Normalize date
        norm_date = _normalize_date(report_date) or _normalize_date(date_str)

        rid = _row_id(symbol, norm_date, row)
        raw_json = json.dumps(row, ensure_ascii=False)

        try:
            cur.execute(
                "INSERT OR REPLACE INTO earnings (id, symbol, company, report_date, time_of_day, raw_json) VALUES (?, ?, ?, ?, ?, ?)",
                (rid, symbol, company, norm_date, time_of_day, raw_json),
            )
            out.append({
                "id": rid,
                "symbol": symbol,
                "company": company,
                "report_date": norm_date,
                "time_of_day": time_of_day,
                "raw": row,
            })
        except Exception:
            # skip bad rows
            continue

    conn.commit()
    conn.close()
    return out


def get_earnings_on(date_str: str) -> List[Dict[str, Any]]:
    ensure_db()
    norm = _normalize_date(date_str)
    if not norm:
        return []
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, symbol, company, report_date, time_of_day, raw_json FROM earnings WHERE report_date = ? ORDER BY company ASC", (norm,))
    rows = cur.fetchall()
    out = []
    for r in rows:
        try:
            raw = json.loads(r[5]) if r[5] else {}
        except Exception:
            raw = {}
        out.append({"id": r[0], "symbol": r[1], "company": r[2], "report_date": r[3], "time_of_day": r[4], "raw": raw})
    conn.close()
    return out


def get_next_earnings(after_date: str, ticker: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    ensure_db()
    # after_date: ISO date or datetime string
    try:
        base = datetime.fromisoformat(after_date).date()
    except Exception:
        try:
            base = datetime.strptime(after_date.split(" ")[0], "%Y-%m-%d").date()
        except Exception:
            base = datetime.utcnow().date()

    conn = _get_conn()
    cur = conn.cursor()
    if ticker:
        cur.execute(
            "SELECT id, symbol, company, report_date, time_of_day, raw_json FROM earnings WHERE symbol = ? AND report_date > ? ORDER BY report_date ASC LIMIT ?",
            (ticker, base.isoformat(), limit),
        )
    else:
        cur.execute(
            "SELECT id, symbol, company, report_date, time_of_day, raw_json FROM earnings WHERE report_date > ? ORDER BY report_date ASC LIMIT ?",
            (base.isoformat(), limit),
        )
    rows = cur.fetchall()
    out = []
    for r in rows:
        try:
            raw = json.loads(r[5]) if r[5] else {}
        except Exception:
            raw = {}
        out.append({"id": r[0], "symbol": r[1], "company": r[2], "report_date": r[3], "time_of_day": r[4], "raw": raw})
    conn.close()
    return out


def get_history(before_date: str, n: int = 20) -> List[Dict[str, Any]]:
    ensure_db()
    try:
        base = datetime.fromisoformat(before_date).date()
    except Exception:
        try:
            base = datetime.strptime(before_date.split(" ")[0], "%Y-%m-%d").date()
        except Exception:
            base = datetime.utcnow().date()

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, symbol, company, report_date, time_of_day, raw_json FROM earnings WHERE report_date < ? ORDER BY report_date DESC LIMIT ?",
        (base.isoformat(), n),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        try:
            raw = json.loads(r[5]) if r[5] else {}
        except Exception:
            raw = {}
        out.append({"id": r[0], "symbol": r[1], "company": r[2], "report_date": r[3], "time_of_day": r[4], "raw": raw})
    conn.close()
    return out


def get_market_between(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    ensure_db()
    try:
        s = datetime.fromisoformat(start_date).date()
    except Exception:
        try:
            s = datetime.strptime(start_date.split(" ")[0], "%Y-%m-%d").date()
        except Exception:
            s = datetime.utcnow().date()
    try:
        e = datetime.fromisoformat(end_date).date()
    except Exception:
        try:
            e = datetime.strptime(end_date.split(" ")[0], "%Y-%m-%d").date()
        except Exception:
            e = s + timedelta(days=1)

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, symbol, company, report_date, time_of_day, raw_json FROM earnings WHERE report_date BETWEEN ? AND ? ORDER BY report_date ASC",
        (s.isoformat(), e.isoformat()),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        try:
            raw = json.loads(r[5]) if r[5] else {}
        except Exception:
            raw = {}
        out.append({"id": r[0], "symbol": r[1], "company": r[2], "report_date": r[3], "time_of_day": r[4], "raw": raw})
    conn.close()
    return out
