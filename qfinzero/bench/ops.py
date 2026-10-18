"""Question types of the benchmark.

Each op has two implementations that must agree:

* ``gold(store, args)`` reads the sample files directly (DuckDB / SQLite) and
  defines the reference answer;
* ``solve(api, args, as_of)`` answers the same question through the public
  QFinZero services, the way an agent would.

The oracle agent runs every ``solve``; a full score shows that each question is
answerable through the platform and that the services serve the stored data
faithfully. Times in ``args`` are US/Eastern ``HH:MM``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import duckdb

ET = ZoneInfo("America/New_York")
NS = 1_000_000_000


def et_dt(d: str, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(date.fromisoformat(d), datetime.min.time(), ET).replace(hour=h, minute=m)


def et_ns(d: str, hhmm: str) -> int:
    return int(et_dt(d, hhmm).timestamp()) * NS


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def et_utc(d: str, hhmm: str) -> str:
    return utc_iso(et_dt(d, hhmm))


def prev_day(d: str) -> str:
    return (date.fromisoformat(d) - timedelta(days=1)).isoformat()


def parse_number(s: Any) -> Optional[float]:
    """``"256K"`` / ``"2.9%"`` / ``1.5`` -> float."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else None


# ── direct access to the sample files ─────────────────────────────────────

class Store:
    """Read-only SQL over a sample root (``upq/`` + ``esp/``)."""

    def __init__(self, root):
        self.root = Path(root)
        self.db = duckdb.connect()
        u = self.root / "upq"
        for name in ("stock_daily", "stock_minute", "option_day", "stock_quote_minute",
                     "option_quote_minute"):
            self.db.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet("
                            f"'{u}/{name}/trade_date=*/*.parquet', hive_partitioning=false)")
        for name in ("corporate_actions", "dividends"):
            self.db.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{u}/{name}/*.parquet')")

    def one(self, sql: str, *args):
        row = self.db.execute(sql, list(args)).fetchone()
        return None if row is None else (row[0] if len(row) == 1 else row)

    def all(self, sql: str, *args):
        return self.db.execute(sql, list(args)).fetchall()

    def sqlite(self, name: str) -> sqlite3.Connection:
        return sqlite3.connect(self.root / "esp" / name)

    def split_factor(self, ticker: str, d: str) -> float:
        """Divide a raw price on ``d`` by this to split-adjust it."""
        f = 1.0
        for (ratio,) in self.all("SELECT split_ratio FROM corporate_actions WHERE symbol = ? "
                                 "AND ex_date > ? AND split_ratio <> 1", ticker, d):
            f *= ratio
        return f


# ── API access ────────────────────────────────────────────────────────────

@dataclass
class Api:
    upq: Any
    esp: Any


def _rows(x) -> list:
    if isinstance(x, dict):
        for k in ("data", "rows", "results", "bars"):
            if isinstance(x.get(k), list):
                return x[k]
    return list(x or [])


def _bar_ns(row: dict) -> int:
    return int(row["window_start"])


def _minute_bars(api: Api, ticker: str, start: str, end: str, as_of) -> list[dict]:
    return _rows(api.upq.stock_minute([ticker], start, end, limit=100000, as_of=as_of))


def _daily(api: Api, ticker: str, start: str, end: str, as_of, adjust=None) -> list[dict]:
    return _rows(api.upq.stock_daily([ticker], start, end, as_of=as_of, adjust=adjust))


def _day_of(row: dict) -> str:
    return str(row.get("date") or row.get("trade_date"))[:10]


# ── ops ───────────────────────────────────────────────────────────────────

OPS: dict[str, tuple[Callable, Callable]] = {}


def op(name: str):
    def wrap(cls):
        OPS[name] = (cls.gold, cls.solve)
        return cls
    return wrap


@op("daily_close")
class DailyClose:
    def gold(s: Store, a):
        return s.one("SELECT close FROM stock_daily WHERE ticker = ? AND trade_date = ?", a["ticker"], a["date"])

    def solve(api: Api, a, as_of):
        (row,) = _daily(api, a["ticker"], a["date"], a["date"], as_of)
        return row["close"]


@op("daily_volume")
class DailyVolume:
    def gold(s, a):
        return s.one("SELECT volume FROM stock_daily WHERE ticker = ? AND trade_date = ?", a["ticker"], a["date"])

    def solve(api, a, as_of):
        (row,) = _daily(api, a["ticker"], a["date"], a["date"], as_of)
        return int(row["volume"])


@op("period_return")
class PeriodReturn:
    """Split-adjusted close-to-close price return in percent (dividends ignored)."""

    def gold(s, a):
        p0 = s.one("SELECT close FROM stock_daily WHERE ticker = ? AND trade_date = ?", a["ticker"], a["start"])
        p1 = s.one("SELECT close FROM stock_daily WHERE ticker = ? AND trade_date = ?", a["ticker"], a["end"])
        p0 /= s.split_factor(a["ticker"], a["start"])
        p1 /= s.split_factor(a["ticker"], a["end"])
        return round((p1 / p0 - 1) * 100, 2)

    def solve(api, a, as_of):
        rows = _daily(api, a["ticker"], a["start"], a["end"], as_of, adjust="split")
        by = {_day_of(r): r["close"] for r in rows}
        return round((by[a["end"]] / by[a["start"]] - 1) * 100, 2)


@op("highest_close_date")
class HighestCloseDate:
    def gold(s, a):
        return str(s.one("SELECT trade_date FROM stock_daily WHERE ticker = ? AND trade_date BETWEEN ? AND ? "
                         "ORDER BY close DESC, trade_date LIMIT 1", a["ticker"], a["start"], a["end"]))

    def solve(api, a, as_of):
        rows = _daily(api, a["ticker"], a["start"], a["end"], as_of)
        best = max(rows, key=lambda r: (r["close"], [-ord(c) for c in _day_of(r)]))
        return _day_of(best)


@op("minute_close")
class MinuteClose:
    def gold(s, a):
        return s.one("SELECT close FROM stock_minute WHERE ticker = ? AND window_start = ?",
                     a["ticker"], et_ns(a["date"], a["time"]))

    def solve(api, a, as_of):
        t = et_dt(a["date"], a["time"])
        rows = _minute_bars(api, a["ticker"], utc_iso(t), utc_iso(t + timedelta(minutes=1)), as_of)
        (row,) = [r for r in rows if _bar_ns(r) == int(t.timestamp()) * NS]
        return row["close"]


@op("rth_vwap")
class RthVwap:
    """Volume-weighted average of 1-minute closes, 09:30-16:00 ET."""

    def gold(s, a):
        v = s.one("SELECT sum(close * volume) / sum(volume) FROM stock_minute WHERE ticker = ? "
                  "AND window_start >= ? AND window_start < ?", a["ticker"],
                  et_ns(a["date"], "09:30"), et_ns(a["date"], "16:00"))
        return round(v, 4)

    def solve(api, a, as_of):
        rows = _minute_bars(api, a["ticker"], et_utc(a["date"], "09:30"), et_utc(a["date"], "16:00"), as_of)
        lo, hi = et_ns(a["date"], "09:30"), et_ns(a["date"], "16:00")
        rows = [r for r in rows if lo <= _bar_ns(r) < hi]
        return round(sum(r["close"] * r["volume"] for r in rows) / sum(r["volume"] for r in rows), 4)


@op("premarket_volume")
class PremarketVolume:
    def gold(s, a):
        return s.one("SELECT sum(volume)::BIGINT FROM stock_minute WHERE ticker = ? AND window_start >= ? "
                     "AND window_start < ?", a["ticker"], et_ns(a["date"], "04:00"), et_ns(a["date"], "09:30"))

    def solve(api, a, as_of):
        rows = _minute_bars(api, a["ticker"], et_utc(a["date"], "04:00"), et_utc(a["date"], "09:30"), as_of)
        lo, hi = et_ns(a["date"], "04:00"), et_ns(a["date"], "09:30")
        return int(sum(r["volume"] for r in rows if lo <= _bar_ns(r) < hi))


@op("overnight_high")
class OvernightHigh:
    """Highest price on the overnight venue, 20:00 the evening before to 04:00."""

    def gold(s, a):
        return s.one("SELECT max(high) FROM stock_minute WHERE ticker = ? AND window_start >= ? "
                     "AND window_start < ?", a["ticker"], et_ns(a["prev"], "20:00"), et_ns(a["date"], "04:00"))

    def solve(api, a, as_of):
        rows = _minute_bars(api, a["ticker"], et_utc(a["prev"], "20:00"), et_utc(a["date"], "04:00"), as_of)
        lo, hi = et_ns(a["prev"], "20:00"), et_ns(a["date"], "04:00")
        return max(r["high"] for r in rows if lo <= _bar_ns(r) < hi)


def _last_quote(rows: list[dict], at_ns: int) -> dict:
    rows = [r for r in rows if _bar_ns(r) <= at_ns]
    return max(rows, key=_bar_ns)


@op("stock_spread")
class StockSpread:
    """Bid-ask spread at the end of the minute starting at ``time``."""

    def gold(s, a):
        bid, ask = s.one("SELECT bid_price, ask_price FROM stock_quote_minute WHERE ticker = ? "
                         "AND window_start <= ? AND trade_date = ? ORDER BY window_start DESC LIMIT 1",
                         a["ticker"], et_ns(a["date"], a["time"]), date.fromisoformat(a["date"]))
        return round(ask - bid, 4)

    def solve(api, a, as_of):
        t = et_dt(a["date"], a["time"])
        rows = _rows(api.upq.stock_quote([a["ticker"]], et_utc(a["date"], "04:00"),
                                         utc_iso(t + timedelta(minutes=1)), limit=100000, as_of=as_of))
        q = _last_quote(rows, int(t.timestamp()) * NS)
        return round(q["ask_price"] - q["bid_price"], 4)


@op("option_mid")
class OptionMid:
    def gold(s, a):
        bid, ask = s.one("SELECT bid_price, ask_price FROM option_quote_minute WHERE contract = ? "
                         "AND window_start <= ? AND trade_date = ? ORDER BY window_start DESC LIMIT 1",
                         a["contract"], et_ns(a["date"], a["time"]), date.fromisoformat(a["date"]))
        return round((bid + ask) / 2, 4)

    def solve(api, a, as_of):
        t = et_dt(a["date"], a["time"])
        rows = _rows(api.upq.option_quote(a["contract"], et_utc(a["date"], "09:30"),
                                          utc_iso(t + timedelta(minutes=1)), limit=100000, as_of=as_of))
        q = _last_quote(rows, int(t.timestamp()) * NS)
        return round((q["bid_price"] + q["ask_price"]) / 2, 4)


@op("most_active_contract")
class MostActiveContract:
    def gold(s, a):
        return s.one("SELECT contract FROM option_day WHERE underlying = ? AND trade_date = ? "
                     "ORDER BY volume DESC, contract LIMIT 1", a["underlying"], date.fromisoformat(a["date"]))

    def solve(api, a, as_of):
        rows = _rows(api.upq.option_chain(a["underlying"], a["date"], as_of=as_of))
        best = min(rows, key=lambda r: (-r["volume"], r.get("contract") or r["ticker"]))
        return best.get("contract") or best["ticker"]


@op("traded_contracts")
class TradedContracts:
    def gold(s, a):
        return s.one("SELECT count(*) FROM option_day WHERE underlying = ? AND trade_date = ? AND expiry = ? "
                     "AND volume > 0", a["underlying"], date.fromisoformat(a["date"]),
                     date.fromisoformat(a["expiry"]))

    def solve(api, a, as_of):
        rows = _rows(api.upq.option_chain(a["underlying"], a["date"], expiry_min=a["expiry"],
                                          expiry_max=a["expiry"], as_of=as_of))
        return sum(1 for r in rows if str(r["expiry"])[:10] == a["expiry"] and r["volume"] > 0)


def _earnings_event(api: Api, ticker: str, day: str, now_utc) -> dict:
    r = api.esp.earnings_calendar(start_date=day, end_date=day, tickers=[ticker], now_utc=now_utc)
    (ev,) = r["events"]
    return ev


@op("eps_surprise")
class EpsSurprise:
    def gold(s, a):
        act, est = s.sqlite("benzinga_earnings.sqlite3").execute(
            "SELECT actual_eps, estimated_eps FROM earnings WHERE ticker = ? AND date = ?",
            [a["ticker"], a["date"]]).fetchone()
        return round(act - est, 2)

    def solve(api, a, as_of):
        p = _earnings_event(api, a["ticker"], a["date"], as_of)["payload"]
        if p["actual_eps"] is None:
            return None
        return round(p["actual_eps"] - p["estimated_eps"], 2)


@op("earnings_beat")
class EarningsBeat:
    def gold(s, a):
        act, est = s.sqlite("benzinga_earnings.sqlite3").execute(
            "SELECT actual_eps, estimated_eps FROM earnings WHERE ticker = ? AND date = ?",
            [a["ticker"], a["date"]]).fetchone()
        return act > est

    def solve(api, a, as_of):
        p = _earnings_event(api, a["ticker"], a["date"], as_of)["payload"]
        return None if p["actual_eps"] is None else p["actual_eps"] > p["estimated_eps"]


@op("reported_eps")
class ReportedEps:
    """Reported EPS; ``None`` when asked before the release (time-lock tasks)."""

    def gold(s, a):
        if a.get("before_release"):
            return None
        return s.sqlite("benzinga_earnings.sqlite3").execute(
            "SELECT actual_eps FROM earnings WHERE ticker = ? AND date = ?", [a["ticker"], a["date"]]).fetchone()[0]

    def solve(api, a, as_of):
        return _earnings_event(api, a["ticker"], a["date"], as_of)["payload"]["actual_eps"]


@op("macro_actual")
class MacroActual:
    def gold(s, a):
        if a.get("before_release"):
            return None
        (v,) = s.sqlite("nasdaq_econ_events.sqlite3").execute(
            "SELECT actual FROM econ_events WHERE event_name = ? AND date = ?", [a["event"], a["utc_date"]]).fetchone()
        return parse_number(v)

    def solve(api, a, as_of):
        r = api.esp.econ_calendar(start_date=a["utc_date"], end_date=a["utc_date"], now_utc=as_of)
        (ev,) = [e for e in r["events"] if e["title"] == a["event"]]
        return parse_number(ev["payload"]["actual"])


@op("next_earnings")
class NextEarnings:
    """The first company to report after ``as_of``."""

    def gold(s, a):
        rows = s.sqlite("benzinga_earnings.sqlite3").execute(
            "SELECT ticker, date, time FROM earnings").fetchall()
        after = [(et_dt(d, t[:5]), tk) for tk, d, t in rows if et_dt(d, t[:5]) > datetime.fromisoformat(
            a["now"].replace("Z", "+00:00"))]
        return min(after)[1]

    def solve(api, a, as_of):
        now = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        end = (now + timedelta(days=60)).date().isoformat()
        r = api.esp.earnings_calendar(start_date=now.astimezone(ET).date().isoformat(), end_date=end,
                                      now_utc=as_of, limit=500)
        evs = [(datetime.fromisoformat(e["time_utc"]), e["tickers"][0]) for e in r["events"]]
        return min(x for x in evs if x[0] > now)[1]


@op("dividend_amount")
class DividendAmount:
    def gold(s, a):
        return s.one("SELECT dividend_cash FROM corporate_actions WHERE symbol = ? AND dividend_cash > 0",
                     a["ticker"])

    def solve(api, a, as_of):
        rows = _rows(api.upq.dividends([a["ticker"]], a["start"], a["end"], as_of=as_of))
        (row,) = rows
        return row.get("amount", row.get("cash_amount"))


@op("split_ex_date")
class SplitExDate:
    """Found through prices alone: the first day raw and split-adjusted closes agree."""

    def gold(s, a):
        return str(s.one("SELECT ex_date FROM corporate_actions WHERE symbol = ? AND split_ratio <> 1",
                         a["ticker"]))

    def solve(api, a, as_of):
        raw = {_day_of(r): r["close"] for r in _daily(api, a["ticker"], a["start"], a["end"], as_of)}
        adj = {_day_of(r): r["close"] for r in _daily(api, a["ticker"], a["start"], a["end"], as_of, "split")}
        return min(d for d in raw if abs(raw[d] - adj[d]) < 1e-9)


@op("last_daily_close")
class LastDailyClose:
    """The most recent daily close available at ``as_of`` (time-lock task)."""

    def gold(s, a):
        return s.one("SELECT close FROM stock_daily WHERE ticker = ? AND trade_date < ? "
                     "ORDER BY trade_date DESC LIMIT 1", a["ticker"], date.fromisoformat(a["date"]))

    def solve(api, a, as_of):
        start = (date.fromisoformat(a["date"]) - timedelta(days=10)).isoformat()
        rows = _daily(api, a["ticker"], start, a["date"], as_of)
        return max(rows, key=_day_of)["close"]


@op("news_count")
class NewsCount:
    def gold(s, a):
        lo = et_dt(a["start"], "00:00").astimezone(timezone.utc).isoformat()
        hi = (et_dt(a["end"], "00:00") + timedelta(days=1)).astimezone(timezone.utc).isoformat()
        (n,) = s.sqlite("news.sqlite3").execute(
            "SELECT count(*) FROM news n JOIN news_tickers t ON t.news_id = n.id WHERE t.ticker = ? "
            "AND n.published_utc >= ? AND n.published_utc < ?", [a["ticker"], lo, hi]).fetchone()
        return n

    def solve(api, a, as_of):
        lo = et_utc(a["start"], "00:00")
        hi = utc_iso(et_dt(a["end"], "00:00") + timedelta(days=1))
        n, cursor = 0, None
        while True:
            r = api.esp.search_news(tickers=[a["ticker"]], start_utc=lo, end_utc=hi, limit=500,
                                    cursor=cursor, now_utc=as_of)
            n += len(r["events"])
            cursor = r.get("next_cursor")
            if not cursor:
                return n


@op("earnings_reaction")
class EarningsReaction:
    """Close-to-close move (percent) across the first close after the report."""

    def gold(s, a):
        before = s.one("SELECT close FROM stock_daily WHERE ticker = ? AND trade_date = ?", a["ticker"], a["before"])
        after = s.one("SELECT close FROM stock_daily WHERE ticker = ? AND trade_date = ?", a["ticker"], a["after"])
        before /= s.split_factor(a["ticker"], a["before"])
        after /= s.split_factor(a["ticker"], a["after"])
        return round((after / before - 1) * 100, 2)

    def solve(api, a, as_of):
        ev = _earnings_event(api, a["ticker"], a["date"], as_of)
        release = datetime.fromisoformat(ev["time_utc"]).astimezone(ET)
        start = (release.date() - timedelta(days=7)).isoformat()
        end = (release.date() + timedelta(days=7)).isoformat()
        rows = sorted(_daily(api, a["ticker"], start, end, as_of, "split"), key=_day_of)
        days = [_day_of(r) for r in rows]
        # first close strictly after the release, and the close before it
        i = next(k for k, d in enumerate(days) if et_dt(d, "16:00") > release)
        return round((rows[i]["close"] / rows[i - 1]["close"] - 1) * 100, 2)


def dumps(x) -> str:
    return json.dumps(x, sort_keys=True, default=str)
