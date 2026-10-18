"""Generate the benchmark task set from a sample root.

    tasks = build_tasks("/path/to/qfz-sample")      # list[Task]

Instances are drawn with a fixed seed from :mod:`qfinzero.sample.universe`;
answers come from :mod:`qfinzero.bench.ops` gold functions over the files.
The same sample version therefore always yields the same tasks, and the task
file shipped in ``qfinzero/bench/data`` is checked against a fresh build in
the test suite.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np

from qfinzero.sample import universe as U
from qfinzero.sample.market import _expiries

from .ops import OPS, Store, et_utc

BENCH_VERSION = "1.0"
SEED = 7

# What a numeric answer may differ by and still count as correct.
PRICE_TOL = 0.005
PCT_TOL = 0.02


@dataclass
class Task:
    id: str
    category: str
    question: str
    op: str
    args: dict
    kind: str                         # number | integer | text | date | bool | none
    answer: Any = None
    tolerance: float = 0.0            # absolute, for number answers
    as_of: Optional[str] = None       # ISO UTC; the agent is time-locked here
    difficulty: int = 1               # 1 lookup, 2 computation, 3 multi-step
    episode: Optional[dict] = None    # trading tasks (see episodes.py)
    meta: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, default=str)


def _d(x: date) -> str:
    return x.isoformat()


def _fmt_time(hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    suffix = "a.m." if h < 12 else "p.m."
    return f"{(h - 1) % 12 + 1}:{m:02d} {suffix} ET"


class _Builder:
    def __init__(self, root):
        self.s = Store(root)
        self.rng = np.random.default_rng(SEED)
        self.tasks: list[Task] = []
        self.days = U.DAYS
        self.mdays = U.MINUTE_WINDOW
        self.names = {s.ticker: s.name for s in U.STOCKS}

    def pick(self, seq, k=None):
        seq = list(seq)
        if k is None:
            return seq[int(self.rng.integers(len(seq)))]
        idx = self.rng.choice(len(seq), size=k, replace=False)
        return [seq[i] for i in sorted(idx)]

    def add(self, category, question, op, args, kind, *, tol=0.0, as_of=None, difficulty=1, **meta):
        answer = OPS[op][0](self.s, args)
        if isinstance(answer, (np.integer,)):
            answer = int(answer)
        if isinstance(answer, (np.floating,)):
            answer = float(answer)
        n = sum(1 for t in self.tasks if t.category == category) + 1
        self.tasks.append(Task(f"{category}-{n:03d}", category, question, op, args, kind, answer,
                               tol, as_of, difficulty, meta=meta))

    def ticker(self, exclude=()):
        return self.pick([s.ticker for s in U.STOCKS if s.ticker not in exclude])

    # ── categories ────────────────────────────────────────────────────

    def daily(self):
        for _ in range(10):
            t, d = self.ticker(), self.pick(self.days)
            self.add("daily", f"What was the closing price of {t} on {_d(d)}? (as traded, not adjusted)",
                     "daily_close", {"ticker": t, "date": _d(d)}, "number", tol=PRICE_TOL)
        for _ in range(5):
            t, d = self.ticker(), self.pick(self.days)
            self.add("daily", f"How many shares of {t} traded on {_d(d)} (full-day volume)?",
                     "daily_volume", {"ticker": t, "date": _d(d)}, "integer")
        for _ in range(6):
            t = self.ticker()
            a, b = sorted(self.pick(range(len(self.days)), 2))
            self.add("daily", f"What was the split-adjusted price return of {t} from the close of "
                     f"{_d(self.days[a])} to the close of {_d(self.days[b])}, in percent? "
                     "Ignore dividends.", "period_return",
                     {"ticker": t, "start": _d(self.days[a]), "end": _d(self.days[b])},
                     "number", tol=PCT_TOL, difficulty=2)
        # NOVA across its split is the case that needs adjust=split
        self.add("daily", "What was the split-adjusted price return of NOVA from the close of "
                 f"{_d(self.days[30])} to the close of {_d(self.days[50])}, in percent? Ignore dividends.",
                 "period_return", {"ticker": "NOVA", "start": _d(self.days[30]), "end": _d(self.days[50])},
                 "number", tol=PCT_TOL, difficulty=3)
        for month, (start, end) in {"January": ("2025-01-01", "2025-01-31"),
                                    "February": ("2025-02-01", "2025-02-28"),
                                    "March": ("2025-03-01", "2025-03-31")}.items():
            t = self.ticker(exclude=("NOVA",))
            self.add("daily", f"On which date in {month} 2025 did {t} have its highest closing price?",
                     "highest_close_date", {"ticker": t, "start": start, "end": end}, "date", difficulty=2)

    def intraday(self):
        for _ in range(8):
            t, d = self.ticker(), self.pick(self.mdays)
            hhmm = f"{self.pick(range(9, 16)):02d}:{self.pick(range(0, 60, 5)):02d}"
            if hhmm < "09:30":
                hhmm = "09:45"
            self.add("intraday", f"What was the close of the one-minute bar of {t} that starts at "
                     f"{_fmt_time(hhmm)} on {_d(d)}?", "minute_close",
                     {"ticker": t, "date": _d(d), "time": hhmm}, "number", tol=PRICE_TOL)
        for _ in range(5):
            t, d = self.ticker(), self.pick(self.mdays)
            self.add("intraday", f"What was the volume-weighted average of {t}'s one-minute closing prices "
                     f"during regular hours (9:30 a.m. to 4:00 p.m. ET) on {_d(d)}?", "rth_vwap",
                     {"ticker": t, "date": _d(d)}, "number", tol=0.01, difficulty=2)
        for _ in range(4):
            t, d = self.ticker(), self.pick(self.mdays)
            self.add("intraday", f"How many shares of {t} traded in the pre-market session "
                     f"(4:00 to 9:30 a.m. ET) on {_d(d)}?", "premarket_volume",
                     {"ticker": t, "date": _d(d)}, "integer", difficulty=2)
        nights = [d for i, d in enumerate(self.mdays) if i and (d - self.mdays[i - 1]).days == 1]
        for _ in range(4):
            t, d = self.pick(U.OVERNIGHT_TICKERS), self.pick(nights)
            prev = self.days[self.days.index(d) - 1]
            self.add("intraday", f"What was the highest price of {t} on the overnight venue between 8:00 p.m. ET "
                     f"on {_d(prev)} and 4:00 a.m. ET on {_d(d)}?", "overnight_high",
                     {"ticker": t, "date": _d(d), "prev": _d(prev)}, "number", tol=PRICE_TOL, difficulty=2)

    def quotes(self):
        for _ in range(5):
            t, d = self.ticker(), self.pick(self.mdays)
            hhmm = f"{self.pick(range(10, 16)):02d}:{self.pick(range(0, 60)):02d}"
            self.add("quotes", f"What was the bid-ask spread of {t} at the end of the minute starting "
                     f"{_fmt_time(hhmm)} on {_d(d)}?", "stock_spread",
                     {"ticker": t, "date": _d(d), "time": hhmm}, "number", tol=0.0005, difficulty=2)

    def options(self):
        exps = _expiries(U.Universe())
        for _ in range(5):
            und, d = self.pick(U.OPTION_UNDERLYINGS), self.pick(self.mdays)
            row = self.s.one("SELECT DISTINCT contract FROM option_quote_minute WHERE underlying = ? "
                             "AND trade_date = ? ORDER BY contract LIMIT 1 OFFSET ?",
                             und, d, int(self.rng.integers(40)))
            hhmm = f"{self.pick(range(10, 16)):02d}:{self.pick(range(0, 60)):02d}"
            self.add("options", f"What was the mid price (average of bid and ask) of option {row} at the end "
                     f"of the minute starting {_fmt_time(hhmm)} on {_d(d)}?", "option_mid",
                     {"contract": row, "date": _d(d), "time": hhmm}, "number", tol=0.0005, difficulty=2)
        for _ in range(4):
            und, d = self.pick(U.OPTION_UNDERLYINGS), self.pick(self.days)
            self.add("options", f"Which {und} option contract had the highest trading volume on {_d(d)}? "
                     "Answer with the contract symbol, e.g. O:XYZ250321C00100000.", "most_active_contract",
                     {"underlying": und, "date": _d(d)}, "text", difficulty=2)
        for _ in range(4):
            und, d = self.pick(U.OPTION_UNDERLYINGS), self.pick(self.days)
            exp = self.pick([e for e in exps if d < e <= d + timedelta(days=40)])
            self.add("options", f"How many {und} option contracts expiring {_d(exp)} (calls and puts) "
                     f"traded at least once on {_d(d)}?", "traded_contracts",
                     {"underlying": und, "date": _d(d), "expiry": _d(exp)}, "integer", difficulty=2)

    def events(self):
        for e in self.pick(U.EARNINGS, 6):
            self.add("events", f"By how much did {self.names[e.ticker]} ({e.ticker})'s reported EPS for the "
                     f"report on {_d(e.day)} differ from the consensus estimate? (actual minus estimate)",
                     "eps_surprise", {"ticker": e.ticker, "date": _d(e.day)}, "number", tol=0.005)
        for e in self.pick(U.EARNINGS, 4):
            self.add("events", f"Did {e.ticker} beat the EPS estimate in its earnings report on {_d(e.day)}?",
                     "earnings_beat", {"ticker": e.ticker, "date": _d(e.day)}, "bool")
        for m in self.pick(U.MACRO, 4):
            utc_date = et_utc(_d(m.day), m.time_et)[:10]
            self.add("events", f"What was the actual value of the US {m.event} release on {_d(m.day)}?"
                     + (f" (in {m.unit})" if m.unit else ""), "macro_actual",
                     {"event": m.event, "utc_date": utc_date}, "number", tol=0.001)
        for e in self.pick([e for e in U.EARNINGS if self.days.index(e.day) + 1 < len(self.days)], 4):
            i = self.days.index(e.day)
            before, after = (e.day, self.days[i + 1]) if e.timing == "AMC" else (self.days[i - 1], e.day)
            self.add("events", f"How much did {e.ticker} move, in percent, from the last close before its "
                     f"earnings report of {_d(e.day)} to the first close after it?", "earnings_reaction",
                     {"ticker": e.ticker, "date": _d(e.day), "before": _d(before), "after": _d(after)},
                     "number", tol=PCT_TOL, difficulty=3)
        for t in self.pick([s.ticker for s in U.STOCKS], 3):
            self.add("events", f"How many news articles mention {t} in February 2025 (US/Eastern dates)?",
                     "news_count", {"ticker": t, "start": "2025-02-01", "end": "2025-02-28"}, "integer",
                     difficulty=2)

    def corporate(self):
        payers = [s for s in U.STOCKS if s.dividend > 0]
        for s in self.pick(payers, 3):
            self.add("corporate", f"What cash dividend per share did {s.ticker} pay in Q1 2025?",
                     "dividend_amount", {"ticker": s.ticker, "start": "2025-01-01", "end": "2025-03-31"},
                     "number", tol=0.0005)
        self.add("corporate", "NOVA split its shares in Q1 2025. On which date did it begin trading "
                 "split-adjusted (the ex-date)?", "split_ex_date",
                 {"ticker": "NOVA", "start": "2025-01-02", "end": "2025-03-31"}, "date", difficulty=3)

    def time_lock(self):
        acme = next(e for e in U.EARNINGS if e.ticker == "ACME")
        bolt = next(e for e in U.EARNINGS if e.ticker == "BOLT")
        for e, hhmm in ((acme, "15:00"), (bolt, "06:30")):
            when = et_utc(_d(e.day), hhmm)
            self.add("time_lock", f"What EPS did {e.ticker} report in its earnings release of {_d(e.day)}? "
                     "If it is not known yet, answer null.", "reported_eps",
                     {"ticker": e.ticker, "date": _d(e.day), "before_release": True}, "none",
                     as_of=when, difficulty=2)
        for e, hhmm in ((acme, "16:30"), (bolt, "09:45")):
            day = e.day
            self.add("time_lock", f"What EPS did {e.ticker} report in its earnings release of {_d(day)}? "
                     "If it is not known yet, answer null.", "reported_eps",
                     {"ticker": e.ticker, "date": _d(day)}, "number", tol=0.005,
                     as_of=et_utc(_d(day), hhmm), difficulty=2)
        fomc = next(m for m in U.MACRO if m.event == "FOMC Rate Decision" and m.day in self.mdays)
        self.add("time_lock", f"What rate did the FOMC announce on {_d(fomc.day)}? If it is not known yet, "
                 "answer null.", "macro_actual",
                 {"event": fomc.event, "utc_date": et_utc(_d(fomc.day), fomc.time_et)[:10], "before_release": True},
                 "none", as_of=et_utc(_d(fomc.day), "13:30"), difficulty=2)
        for d in self.pick(self.mdays, 3):
            t = self.ticker()
            self.add("time_lock", f"What is the most recent daily closing price of {t} available right now?",
                     "last_daily_close", {"ticker": t, "date": _d(d)}, "number", tol=PRICE_TOL,
                     as_of=et_utc(_d(d), "11:00"), difficulty=2)
        for d in self.pick(self.days[5:-15], 3):
            # 16:00 on a day without minute data, so a daily session can hold the lock
            now = et_utc(_d(d), "16:00")
            self.add("time_lock", "Which company is the next to report earnings? Answer with its ticker.",
                     "next_earnings", {"now": now}, "text", as_of=now, difficulty=2)


def build_tasks(root) -> list[Task]:
    b = _Builder(root)
    for part in (b.daily, b.intraday, b.quotes, b.options, b.events, b.corporate, b.time_lock):
        part()
    from .episodes import build_episodes
    b.tasks += build_episodes(b.s)
    return b.tasks


def write_tasks(tasks: list[Task], path) -> None:
    Path(path).write_text("".join(t.to_json() + "\n" for t in tasks))


def load_tasks(path=None) -> list[Task]:
    """Tasks from ``path`` (default: the task file shipped with the package)."""
    path = Path(path) if path else Path(__file__).with_name("data") / f"tasks-v{BENCH_VERSION}.jsonl"
    return [Task(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]
