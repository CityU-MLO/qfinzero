"""ESP databases for the synthetic market: earnings, macro calendar and news.

The three SQLite files use the production schemas, so the ESP service reads
them unchanged (news through ``SQLiteNewsSource``). Every headline is tied to
an event in :mod:`universe` or to a price move in the simulated paths, so
benchmark answers can be checked against both the event store and UPQ.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..esp_schema import EARNINGS_SCHEMA, ECON_SCHEMA, NEWS_SCHEMA
from .market import ET, GRID_START, Paths, _dividend_days
from .universe import BY_TICKER, Universe

RTH_CLOSE = 16 * 60 - 1 - GRID_START          # index of the 15:59 bar
FETCHED_AT = "2025-04-01T00:00:00Z"
PUBLISHERS = ("QFZ Wire", "Synthetic Street Journal", "Sample Market News")
URL = "https://example.com/qfz-sample/news/{}"

def _id(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:24]


def _utc(d: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":")[:2])
    return datetime(d.year, d.month, d.day, h, m, tzinfo=ET).astimezone(timezone.utc)


def _fresh(path: Path, schema: str) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(schema)
    return con


def rth_close(p: Paths, ticker: str, d: date) -> float:
    """Split-adjusted (economic) 16:00 close."""
    return float(p.close[ticker][d][RTH_CLOSE] / p.split_factor[ticker][d])


def earnings_reaction(u: Universe, p: Paths, e) -> tuple[date, float]:
    """(reaction day, close-to-close return) of an earnings report."""
    i = u.days.index(e.day)
    if e.timing == "AMC":
        before, after = e.day, u.days[i + 1]
    else:
        before, after = u.days[i - 1], e.day
    return after, rth_close(p, e.ticker, after) / rth_close(p, e.ticker, before) - 1


def _fmt(x: float | None, unit: str) -> str:
    if x is None:
        return ""
    s = f"{x:g}"
    return s + unit if unit in ("%", "K") else s


def write_earnings(u: Universe, path: Path) -> int:
    con = _fresh(path, EARNINGS_SCHEMA)
    for e in u.earnings:
        s = BY_TICKER[e.ticker]
        row = {
            "benzinga_id": _id("earn", e.ticker, e.day),
            "ticker": e.ticker, "company_name": s.name, "currency": "USD",
            "fiscal_year": 2024, "fiscal_period": "Q4",
            "date": e.day.isoformat(), "time": "16:05:00" if e.timing == "AMC" else "07:00:00",
            "date_status": "confirmed", "last_updated": f"{e.day.isoformat()}T21:00:00Z",
            "actual_eps": e.eps_actual, "estimated_eps": e.eps_estimate,
            "previous_eps": round(e.eps_estimate * 0.9, 2),
            "eps_surprise": round(e.surprise, 4),
            "eps_surprise_percent": round(e.surprise / abs(e.eps_estimate) * 100, 2),
            "actual_revenue": e.revenue_actual, "estimated_revenue": e.revenue_estimate,
            "revenue_surprise": e.revenue_actual - e.revenue_estimate,
            "revenue_surprise_percent": round((e.revenue_actual / e.revenue_estimate - 1) * 100, 2),
            "importance": 5 if s.options else 3,
        }
        row["raw_json"] = json.dumps(row)
        con.execute(f"INSERT INTO earnings ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                    list(row.values()))
    con.commit()
    con.close()
    return len(u.earnings)


def write_econ(u: Universe, path: Path) -> int:
    con = _fresh(path, ECON_SCHEMA)
    for m in u.macro:
        t = _utc(m.day, m.time_et)
        desc = f"Synthetic {m.event} release for the QFinZero sample market."
        raw = {"gmt": t.strftime("%H:%M"), "country": "United States", "eventName": m.event,
               "actual": _fmt(m.actual, m.unit), "consensus": _fmt(m.consensus, m.unit),
               "previous": _fmt(m.previous, m.unit), "description": desc}
        con.execute(
            "INSERT INTO econ_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [_id("econ", m.event, m.day), t.date().isoformat(), "United States", m.event,
             t.strftime("%H:%M"), t.strftime("%H:%M"), raw["actual"], raw["consensus"],
             raw["previous"], desc, desc, FETCHED_AT, json.dumps(raw)])
    con.commit()
    con.close()
    return len(u.macro)


def news_items(u: Universe, p: Paths) -> list[dict]:
    """All headlines, each with its ET publish time and the facts it states."""
    rng = np.random.default_rng(u.seed + 7)
    items: list[dict] = []

    def add(d: date, hhmm: str, title: str, tickers: list[str], desc: str, kind: str, **facts):
        t = _utc(d, hhmm)
        items.append({"id": _id("news", kind, d, hhmm, title), "published_utc": t.isoformat(),
                      "title": title, "description": desc, "tickers": tickers,
                      "keywords": [kind], "kind": kind, "facts": facts})

    for e in u.earnings:
        s = BY_TICKER[e.ticker]
        i = u.days.index(e.day)
        pre = u.days[max(0, i - 2)]
        add(pre, "12:00", f"{s.name} ({e.ticker}) to report fourth-quarter results on {e.day:%B} {e.day.day}",
            [e.ticker], f"Analysts expect EPS of ${e.eps_estimate:.2f} on revenue of "
            f"${e.revenue_estimate / 1e9:.2f}B. The report is scheduled "
            f"{'after the close' if e.timing == 'AMC' else 'before the open'}.",
            "earnings_preview", estimate=e.eps_estimate)
        verb = "beats" if e.surprise > 0 else "misses" if e.surprise < 0 else "matches"
        rel = "16:06" if e.timing == "AMC" else "07:01"
        add(e.day, rel, f"{s.name} Q4 EPS ${e.eps_actual:.2f} {verb} estimate of ${e.eps_estimate:.2f}",
            [e.ticker], f"Revenue was ${e.revenue_actual / 1e9:.2f}B against ${e.revenue_estimate / 1e9:.2f}B expected.",
            "earnings_result", eps=e.eps_actual, estimate=e.eps_estimate, beat=e.surprise > 0)
        day, ret = earnings_reaction(u, p, e)
        move = "rise" if ret > 0 else "fall"
        add(day, "16:10", f"{e.ticker} shares {move} {abs(ret) * 100:.1f}% after quarterly report",
            [e.ticker], f"{s.name} closed at ${rth_close(p, e.ticker, day):.2f}.",
            "earnings_reaction", ret=round(ret, 4))

    for m in u.macro:
        rel = (datetime.combine(m.day, datetime.min.time()) +
               timedelta(hours=int(m.time_et[:2]), minutes=int(m.time_et[3:]) + 1)).strftime("%H:%M")
        add(m.day, rel, f"US {m.event} {_fmt(m.actual, m.unit)} vs {_fmt(m.consensus, m.unit)} expected",
            [], f"Previous reading: {_fmt(m.previous, m.unit)}.", "macro",
            event=m.event, actual=m.actual, consensus=m.consensus)

    for s in u.stocks:
        if s.split:
            ex = date.fromisoformat(s.split[0])
            ann = u.days[u.days.index(ex) - 10]
            add(ann, "08:00", f"{s.name} announces {s.split[1]:g}-for-1 stock split",
                [s.ticker], f"Shares begin trading split-adjusted on {ex.isoformat()}.",
                "split", ratio=s.split[1], ex_date=ex.isoformat())
    for t, ex in sorted(_dividend_days(u)):
        s = BY_TICKER[t]
        decl = u.days[u.days.index(ex) - 7]
        add(decl, "08:30", f"{s.name} declares quarterly dividend of ${s.dividend:.2f} per share",
            [t], f"Ex-dividend date {ex.isoformat()}.", "dividend",
            amount=s.dividend, ex_date=ex.isoformat())

    # Noise: one large close-to-close move per stock per week gets a headline.
    for s in u.stocks:
        for w in range(0, len(u.days) - 1, 5):
            week = u.days[max(w, 1):w + 5]
            rets = [(rth_close(p, s.ticker, d) / rth_close(p, s.ticker, u.days[u.days.index(d) - 1]) - 1, d)
                    for d in week]
            r, d = max(rets, key=lambda x: abs(x[0]))
            if abs(r) < 0.025:
                continue
            word = ["gains", "climbs", "advances"][rng.integers(3)] if r > 0 else \
                ["slides", "drops", "declines"][rng.integers(3)]
            add(d, "16:20", f"{s.name} {word} {abs(r) * 100:.1f}% in heavy trading",
                [s.ticker], f"{s.ticker} closed at ${rth_close(p, s.ticker, d):.2f}.",
                "price_move", ret=round(r, 4))
    items.sort(key=lambda x: (x["published_utc"], x["id"]))
    for k, it in enumerate(items):
        it["publisher"] = PUBLISHERS[k % len(PUBLISHERS)]
    return items


def write_news(items: list[dict], path: Path) -> int:
    con = _fresh(path, NEWS_SCHEMA)
    for it in items:
        con.execute(
            "INSERT INTO news (id, published_utc, title, description, article_url, author, publisher, "
            "tickers, keywords, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [it["id"], it["published_utc"], it["title"], it["description"], URL.format(it["id"]),
             "QFinZero Sample Desk", it["publisher"], json.dumps(it["tickers"]),
             json.dumps(it["keywords"]), "qfz_sample"])
        con.executemany("INSERT INTO news_tickers VALUES (?, ?)", [(it["id"], t) for t in it["tickers"]])
    con.commit()
    con.close()
    return len(items)


def write_esp(u: Universe, p: Paths, root: Path) -> dict:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    return {
        "earnings": write_earnings(u, root / "benzinga_earnings.sqlite3"),
        "econ_events": write_econ(u, root / "nasdaq_econ_events.sqlite3"),
        "news": write_news(news_items(u, p), root / "news.sqlite3"),
    }
