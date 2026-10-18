"""Data availability by ticker and day, for the console's coverage map.

For every UPQ store and trading day a small summary is kept: rows per ticker
(per underlying for options), distinct contracts, and for minute bars the
count per trading session. Summaries are computed on first use from the
partition's parquet files and cached in ``$STORAGE_ROOT/_state/coverage``;
a cache entry is rebuilt when its partition changes. A query then only reads
summaries, so a coverage map over months of full-market minute data stays
interactive.

    matrix(["SPY", "QQQ"], "2025-01-01", "2025-03-31")   # cells per ticker × day
    cell("SPY", "2025-03-24")                            # everything about one day
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

LEVELS = (
    # id, store, what a cell counts
    ("daily", "stock_daily"),
    ("minute", "stock_minute"),
    ("quotes", "stock_quote_minute"),
    ("options_eod", "option_day"),
    ("options_minute", "option_minute"),
    ("options_quotes", "option_quote_minute"),
)
OPTION_STORES = {"option_day", "option_minute", "option_quote_minute"}
SESSIONS = ("overnight", "pre", "regular", "post")
MAX_DAYS = 800
MAX_TICKERS = 60

# ET minute of day -> session (holiday early closes are not distinguished here)
_SESSION_SQL = """
CASE
  WHEN m >= 240 AND m < 570 THEN 'pre'
  WHEN m >= 570 AND m < 960 THEN 'regular'
  WHEN m >= 960 AND m < 1200 THEN 'post'
  ELSE 'overnight' END
"""

_lock = threading.Lock()


def _storage() -> Path:
    from .explore import _paths
    return _paths().storage


def _lit(p: Path | str) -> str:
    return str(p).replace("'", "''")


def _partition(store: str, d: str, root: Optional[Path] = None) -> Path:
    return (root or _storage()) / store / f"trade_date={d}"


def _cache_file(store: str, d: str, root: Path) -> Path:
    return root / "_state" / "coverage" / store / f"{d}.json"


def _summarize(store: str, files: list[Path]) -> dict[str, dict]:
    """``{ticker: {rows, contracts?, sessions?}}`` for one partition."""
    from qfinzero.pipeline.engine import connect
    src = "read_parquet([" + ",".join(f"'{_lit(f)}'" for f in files) + "], union_by_name=true)"
    con = connect()
    try:
        if store in OPTION_STORES:
            rows = con.execute(f"SELECT underlying, count(*), count(DISTINCT contract), "
                               f"{'sum(volume)' if store != 'option_quote_minute' else 'NULL'} "
                               f"FROM {src} GROUP BY 1").fetchall()
            return {u: {"rows": int(n), "contracts": int(c), **({"volume": int(v)} if v is not None else {})}
                    for u, n, c, v in rows if u}
        if store == "stock_minute":
            et = "timezone('America/New_York', to_timestamp(window_start / 1e9))"
            rows = con.execute(
                f"SELECT ticker, {_SESSION_SQL} AS s, count(*), sum(volume) FROM ("
                f"SELECT ticker, volume, hour({et}) * 60 + minute({et}) AS m FROM {src}) GROUP BY 1, 2").fetchall()
            out: dict[str, dict] = {}
            for t, s, n, v in rows:
                e = out.setdefault(t, {"rows": 0, "volume": 0, "sessions": {}})
                e["rows"] += int(n)
                e["volume"] += int(v or 0)
                e["sessions"][s] = int(n)
            return out
        vol = "sum(volume)" if store == "stock_daily" else "NULL"
        rows = con.execute(f"SELECT ticker, count(*), {vol} FROM {src} GROUP BY 1").fetchall()
        return {t: {"rows": int(n), **({"volume": int(v)} if v is not None else {})} for t, n, v in rows}
    finally:
        con.close()


def day_summary(store: str, d: str, root: Optional[Path] = None) -> dict[str, dict]:
    """Cached summary of ``store`` on date ``d`` ({} when the partition is absent)."""
    root = root or _storage()
    part = _partition(store, d, root)
    files = sorted(part.glob("*.parquet")) if part.is_dir() else []
    if not files:
        return {}
    stats = [f.stat() for f in files]
    fingerprint = [max(s.st_mtime_ns for s in stats), sum(s.st_size for s in stats), len(stats)]
    cache = _cache_file(store, d, root)
    try:
        cached = json.loads(cache.read_text())
        if cached.get("fingerprint") == fingerprint:
            return cached["summary"]
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    summary = _summarize(store, files)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"fingerprint": fingerprint, "summary": summary}, separators=(",", ":")))
        tmp.replace(cache)
    except OSError:
        pass  # read-only storage: serve uncached
    return summary


def _dates(store: str, start: str, end: str, root: Path) -> list[str]:
    base = root / store
    if not base.is_dir():
        return []
    out = []
    for p in base.glob("trade_date=*"):
        d = p.name[len("trade_date="):]
        if start <= d <= end and p.is_dir():
            out.append(d)
    return sorted(out)


def extent(root: Optional[Path] = None) -> dict[str, Any]:
    """First and last date of each store; the default range of the map."""
    root = root or _storage()
    out = {}
    for level, store in LEVELS:
        ds = _dates(store, "0000", "9999", root)
        out[level] = {"start": ds[0], "end": ds[-1], "days": len(ds)} if ds else None
    return out


def matrix(tickers: list[str], start: str, end: str, root: Optional[Path] = None) -> dict[str, Any]:
    """Availability per ticker and day.

    ``cells[ticker][date] = {level: rows}``; minute cells also carry
    ``sessions``. Only days where some store has a partition are listed.
    """
    root = root or _storage()
    tickers = [t.strip().upper() for t in tickers if t.strip()][:MAX_TICKERS]
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    if d1 < d0:
        raise ValueError("end before start")
    if (d1 - d0).days > MAX_DAYS:
        raise ValueError(f"range longer than {MAX_DAYS} days")
    jobs = [(level, store, d) for level, store in LEVELS for d in _dates(store, start, end, root)]
    want = set(tickers)

    def run(job):
        level, store, d = job
        s = day_summary(store, d, root)
        return level, d, {t: s[t] for t in want if t in s}

    with _lock, ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, jobs))
    days = sorted({d for _, _, d in jobs})
    cells: dict[str, dict[str, dict]] = {t: {} for t in tickers}
    for level, d, found in results:
        for t, info in found.items():
            c = cells[t].setdefault(d, {})
            c[level] = info["rows"]
            if level == "minute" and "sessions" in info:
                c["sessions"] = info["sessions"]
            if level == "options_eod":
                c["contracts"] = info.get("contracts", 0)
    return {"tickers": tickers, "days": days, "levels": [lv for lv, _ in LEVELS], "cells": cells}


def suggest(prefix: str = "", limit: int = 20, root: Optional[Path] = None) -> list[dict]:
    """Most-traded tickers on the latest daily partition, optionally by prefix."""
    root = root or _storage()
    ds = _dates("stock_daily", "0000", "9999", root)
    if not ds:
        return []
    s = day_summary("stock_daily", ds[-1], root)
    p = prefix.strip().upper()
    rows = sorted(((t, v.get("volume", 0)) for t, v in s.items() if t.startswith(p)), key=lambda x: -x[1])
    return [{"ticker": t, "volume": v} for t, v in rows[:limit]]


def cell(ticker: str, d: str, root: Optional[Path] = None) -> dict[str, Any]:
    """Everything stored for one ticker on one day."""
    root = root or _storage()
    t = ticker.strip().upper()
    out: dict[str, Any] = {"ticker": t, "date": d, "levels": {}}
    for level, store in LEVELS:
        info = day_summary(store, d, root).get(t)
        out["levels"][level] = info
    out["daily_bar"] = _daily_bar(t, d, root)
    out["minute_span"] = _span("stock_minute", "ticker", t, d, root)
    out["quote_span"] = _span("stock_quote_minute", "ticker", t, d, root)
    out["option_expiries"] = _expiries(t, d, root)
    out["corporate_actions"] = _corporate_actions(t, d, root)
    return out


def _query(sql: str, params: list) -> list[tuple]:
    from qfinzero.pipeline.engine import connect
    con = connect()
    try:
        return con.execute(sql, params).fetchall()
    except Exception:  # noqa: BLE001 — missing or empty store
        return []
    finally:
        con.close()


def _files(store: str, d: str, root: Path) -> Optional[str]:
    part = _partition(store, d, root)
    files = sorted(part.glob("*.parquet")) if part.is_dir() else []
    if not files:
        return None
    return "read_parquet([" + ",".join(f"'{_lit(f)}'" for f in files) + "], union_by_name=true)"


def _daily_bar(t: str, d: str, root: Path) -> Optional[dict]:
    src = _files("stock_daily", d, root)
    rows = _query(f"SELECT open, high, low, close, volume FROM {src} WHERE ticker = ?", [t]) if src else []
    if not rows:
        return None
    o, h, lo, c, v = rows[0]
    return {"open": o, "high": h, "low": lo, "close": c, "volume": int(v)}


def _span(store: str, col: str, t: str, d: str, root: Path) -> Optional[dict]:
    src = _files(store, d, root)
    rows = _query(f"SELECT min(window_start), max(window_start) FROM {src} WHERE {col} = ?", [t]) if src else []
    if not rows or rows[0][0] is None:
        return None
    return {"first_ns": int(rows[0][0]), "last_ns": int(rows[0][1])}


def _expiries(t: str, d: str, root: Path) -> list[dict]:
    src = _files("option_day", d, root)
    if not src:
        return []
    rows = _query(f"SELECT expiry, count(*), sum(volume) FROM {src} WHERE underlying = ? GROUP BY 1 ORDER BY 1", [t])
    return [{"expiry": str(e), "contracts": int(n), "volume": int(v or 0)} for e, n, v in rows]


def _corporate_actions(t: str, d: str, root: Path) -> list[dict]:
    path = root / "corporate_actions"
    files = sorted(path.glob("*.parquet")) if path.is_dir() else []
    if not files:
        return []
    src = "read_parquet([" + ",".join(f"'{_lit(f)}'" for f in files) + "], union_by_name=true)"
    rows = _query(f"SELECT split_ratio, dividend_cash FROM {src} WHERE symbol = ? AND ex_date = ?", [t, date.fromisoformat(d)])
    out = []
    for split, cash in rows:
        if split and split != 1:
            out.append({"type": "split", "ratio": split})
        if cash:
            out.append({"type": "dividend", "cash": cash})
    return out


def default_range(root: Optional[Path] = None, days: int = 90) -> tuple[str, str]:
    """The last ``days`` calendar days that have daily bars."""
    e = (extent(root).get("daily") or {}).get("end")
    end = date.fromisoformat(e) if e else date.today()
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


# ── events, through the ESP service (it knows the MongoDB / SQLite backends) ──

def _esp():
    from qfinzero.clients.esp.client import ESPClient
    from qfinzero.config import ESP_URL
    return ESPClient(ESP_URL, timeout=30)


def _paged(fetch, limit: int = 2000) -> list[dict]:
    out, cursor = [], None
    while len(out) < limit:
        r = fetch(cursor)
        out += r.get("events", [])
        cursor = r.get("next_cursor")
        if not cursor:
            break
    return out


def _et_date(iso: str) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date().isoformat()


def events(tickers: list[str], start: str, end: str) -> dict[str, Any]:
    """News counts per ticker and day, earnings per ticker and US macro releases.

    Each part degrades to empty (with a note) when ESP or that store is unavailable.
    """
    tickers = [t.strip().upper() for t in tickers if t.strip()][:MAX_TICKERS]
    out: dict[str, Any] = {"news": {t: {} for t in tickers}, "earnings": {t: [] for t in tickers},
                           "macro": [], "notes": []}
    try:
        esp = _esp()
    except Exception as e:  # noqa: BLE001
        out["notes"].append(f"ESP client unavailable: {e}")
        return out
    with esp:
        try:
            r = esp._get("/esp/news/counts", {"tickers": ",".join(tickers), "start": start, "end": end})
            for row in r.get("counts", []):
                out["news"].setdefault(row["ticker"], {})[row["date"]] = row["count"]
        except Exception as e:  # noqa: BLE001
            out["notes"].append(f"news: {e}")
        try:
            evs = _paged(lambda c: esp.earnings_calendar(start_date=start, end_date=end, tickers=tickers,
                                                         limit=500, cursor=c))
            for ev in evs:
                p = ev.get("payload") or {}
                for t in ev.get("tickers", []):
                    if t in out["earnings"]:
                        out["earnings"][t].append({
                            "date": _et_date(ev["time_utc"]), "time_utc": ev["time_utc"], "title": ev["title"],
                            "status": ev.get("status"), "actual_eps": p.get("actual_eps"),
                            "estimated_eps": p.get("estimated_eps")})
        except Exception as e:  # noqa: BLE001
            out["notes"].append(f"earnings: {e}")
        try:
            evs = _paged(lambda c: esp.econ_calendar(start_date=start, end_date=end, limit=500, cursor=c))
            out["macro"] = [{"date": _et_date(ev["time_utc"]), "time_utc": ev["time_utc"], "title": ev["title"],
                             "importance": ev.get("importance"), "actual": (ev.get("payload") or {}).get("actual"),
                             "consensus": (ev.get("payload") or {}).get("consensus")}
                            for ev in evs if ev.get("importance") in ("high", "medium")]
        except Exception as e:  # noqa: BLE001
            out["notes"].append(f"macro: {e}")
    return out


def day_events(ticker: str, d: str) -> dict[str, Any]:
    """Earnings, news and macro releases of one ticker on one US/Eastern day."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    t = ticker.strip().upper()
    et = ZoneInfo("America/New_York")
    lo = datetime.fromisoformat(d).replace(tzinfo=et)
    hi = lo + timedelta(days=1)
    ev = events([t], d, d)
    out: dict[str, Any] = {"earnings": ev["earnings"].get(t, []), "macro": ev["macro"], "news": [],
                           "notes": ev["notes"]}
    try:
        with _esp() as esp:
            r = esp.search_news(tickers=[t], start_utc=lo.astimezone(timezone.utc).isoformat(),
                                end_utc=hi.astimezone(timezone.utc).isoformat(), limit=100)
            out["news"] = [{"id": n["event_id"], "time_utc": n["time_utc"], "title": n["title"],
                            "publisher": (n.get("payload") or {}).get("publisher"),
                            "url": (n.get("payload") or {}).get("article_url")} for n in r.get("events", [])]
    except Exception as e:  # noqa: BLE001
        out["notes"].append(f"news: {e}")
    return out
