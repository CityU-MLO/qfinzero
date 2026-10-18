"""Trading episodes: the agent acts in a PMB session and is scored on what
the broker recorded.

The runner creates the account and the session, tells the agent their ids and
the instructions, lets it act, then evaluates ``checks`` against the session's
fills and the account's positions. ``script`` is the oracle's solution.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from qfinzero.sample import universe as U
from qfinzero.sample.market import _expiries, occ

from .ops import ET, Store, et_dt, et_utc, utc_iso

INITIAL_CASH = 100_000.0


def _task(n: int, question: str, episode: dict, difficulty: int = 2):
    from .tasks import Task
    return Task(f"trading-{n:03d}", "trading", question, "episode", {}, "episode",
                difficulty=difficulty, episode=episode)


def build_episodes(s: Store) -> list:
    out = []
    mdays = U.MINUTE_WINDOW

    # 1. market order at the open, hold
    d = mdays[2].isoformat()
    out.append(_task(1, (
        "Buy 50 shares of ACME with a market order at the start of the session and hold them "
        "until the session ends."), {
        "frequency": "1m", "start_ts": et_utc(d, "09:30"), "end_ts": et_utc(d, "16:00"),
        "stocks": ["ACME"], "options": [], "initial_cash": INITIAL_CASH,
        "script": [{"do": "buy", "symbol": "ACME", "qty": 50}, {"do": "run_to_end"}],
        "checks": [{"type": "position", "symbol": "ACME", "qty": 50},
                   {"type": "filled", "symbol": "ACME", "side": "BUY", "qty": 50}],
    }, difficulty=1))

    # 2. flat before a pre-market earnings release
    bolt = next(e for e in U.EARNINGS if e.ticker == "BOLT")
    prev = U.DAYS[U.DAYS.index(bolt.day) - 1].isoformat()
    release = et_utc(bolt.day.isoformat(), "07:00")
    out.append(_task(2, (
        f"BOLT reports earnings at 7:00 a.m. ET on {bolt.day.isoformat()}. Buy 100 shares of BOLT now, "
        "then make sure you hold no BOLT shares when the report comes out. Market orders only fill "
        "in regular hours (9:30 a.m. to 4:00 p.m. ET)."), {
        "frequency": "1m", "start_ts": et_utc(prev, "15:00"), "end_ts": et_utc(bolt.day.isoformat(), "09:00"),
        "stocks": ["BOLT"], "options": [], "initial_cash": INITIAL_CASH,
        "script": [{"do": "buy", "symbol": "BOLT", "qty": 100},
                   {"do": "step", "n": 5},
                   {"do": "sell", "symbol": "BOLT", "qty": 100},
                   {"do": "run_to_end"}],
        "checks": [{"type": "filled", "symbol": "BOLT", "side": "BUY", "qty": 100},
                   {"type": "flat_by", "symbol": "BOLT", "ts": release}],
    }, difficulty=3))

    # 3. option market order at a set time
    d = mdays[4]
    spot = s.one("SELECT close FROM stock_daily WHERE ticker = 'ACME' AND trade_date = ?",
                 mdays[3])
    exp = min(e for e in _expiries(U.Universe()) if e >= d + timedelta(days=5))
    strike = round(spot / 5) * 5
    contract = occ("ACME", exp, "C", strike)
    t0 = et_utc(d.isoformat(), "10:00")
    out.append(_task(3, (
        f"At 10:00 a.m. ET, buy 2 contracts of the ACME call {contract} with a market order and hold them."), {
        "frequency": "1m", "start_ts": et_utc(d.isoformat(), "09:30"), "end_ts": et_utc(d.isoformat(), "11:00"),
        "stocks": ["ACME"], "options": [contract], "initial_cash": INITIAL_CASH,
        "script": [{"do": "step_until", "ts": t0},
                   {"do": "buy_option", "contract": contract, "qty": 2},
                   {"do": "run_to_end"}],
        "checks": [{"type": "position", "symbol": contract, "qty": 2},
                   {"type": "filled", "symbol": contract, "side": "BUY", "qty": 2, "not_before": t0}],
    }))

    # 4. limit order on the overnight venue
    i = next(k for k in range(len(mdays) - 1, 0, -1) if (mdays[k] - mdays[k - 1]).days == 1)
    night, morning = mdays[i - 1].isoformat(), mdays[i].isoformat()
    hi = s.one("SELECT max(high) FROM stock_minute WHERE ticker = 'NOVA' AND window_start >= ? AND "
               "window_start < ?", int(et_dt(night, "21:00").timestamp() * 1e9),
               int(et_dt(morning, "04:00").timestamp() * 1e9))
    limit = round(hi * 1.01, 2)
    out.append(_task(4, (
        f"It is the evening of {night}. Buy 10 shares of NOVA on the overnight venue with a limit order "
        f"at ${limit:.2f}, so that it fills before the pre-market opens at 4:00 a.m. ET."), {
        "frequency": "1m", "start_ts": et_utc(night, "21:00"), "end_ts": et_utc(morning, "04:30"),
        "stocks": ["NOVA"], "options": [], "initial_cash": INITIAL_CASH,
        "script": [{"do": "buy", "symbol": "NOVA", "qty": 10, "order_type": "LIMIT",
                    "limit_price": limit, "trading_hours": "OVERNIGHT", "time_in_force": "GTC"},
                   {"do": "run_to_end"}],
        "checks": [{"type": "position", "symbol": "NOVA", "qty": 10},
                   {"type": "filled", "symbol": "NOVA", "side": "BUY", "qty": 10,
                    "not_before": et_utc(night, "21:00"), "before": et_utc(morning, "04:00")}],
    }, difficulty=3))
    return out


# ── evaluation ────────────────────────────────────────────────────────────

def _ts(x: str) -> datetime:
    dt = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _symbol(instrument_id: str) -> str:
    """``STOCK:ACME`` / ``OPTION:O:ACME…`` -> ``ACME`` / ``O:ACME…``."""
    kind, _, rest = instrument_id.partition(":")
    return rest if kind in ("STOCK", "OPTION") and rest else instrument_id


def evaluate(checks: list[dict], trades: list[dict], positions: list[dict]) -> list[dict]:
    """Each check with ``ok`` and a short ``detail``."""
    pos: dict[str, int] = {}
    for p in positions:
        pos[_symbol(p["instrument_id"])] = pos.get(_symbol(p["instrument_id"]), 0) + p["qty"]
    out = []
    for c in checks:
        sym = c["symbol"]
        mine = [t for t in trades if _symbol(t["instrument_id"]) == sym]
        if c["type"] == "position":
            got = pos.get(sym, 0)
            ok, detail = got == c["qty"], f"position {got}"
        elif c["type"] == "filled":
            rel = [t for t in mine if t["side"] == c["side"]
                   and ("not_before" not in c or _ts(t["ts"]) >= _ts(c["not_before"]))
                   and ("before" not in c or _ts(t["ts"]) < _ts(c["before"]))]
            got = sum(t["qty"] for t in rel)
            ok, detail = got == c["qty"], f"{c['side']} filled {got} in window"
        elif c["type"] == "flat_by":
            net = sum(t["qty"] if t["side"] == "BUY" else -t["qty"]
                      for t in mine if _ts(t["ts"]) < _ts(c["ts"]))
            ok, detail = net == 0, f"net {net} before {c['ts']}"
        else:
            ok, detail = False, f"unknown check {c['type']}"
        out.append({**c, "ok": ok, "detail": detail})
    return out


def setup(pmb, ep: dict) -> tuple[str, str]:
    """Create the account and session of an episode: (account_id, session_id)."""
    start_day = _ts(ep["start_ts"]).astimezone(ET).date().isoformat()
    acct = pmb.create_account(initial_cash=ep["initial_cash"], open_date=start_day)
    account_id = acct["account_id"]
    sess = pmb.create_session(account_id=account_id, frequency=ep["frequency"],
                              start_ts=ep["start_ts"], end_ts=ep["end_ts"],
                              universe={"stocks": ep["stocks"], "options": ep["options"]})
    return account_id, sess["session_id"]


def run_script(pmb, ep: dict, account_id: str, session_id: str) -> None:
    """The oracle's solution: place the scripted orders at the scripted times."""
    def advance(**kw):
        pmb.step_until(session_id, stop_on_fill=False, max_steps=100000, **kw)

    pmb.step(session_id, 1)
    for st in ep["script"]:
        do = st["do"]
        if do == "buy":
            pmb.buy(session_id, account_id, st["symbol"], st["qty"],
                    order_type=st.get("order_type", "MARKET"), limit_price=st.get("limit_price"),
                    trading_hours=st.get("trading_hours", "REGULAR"),
                    time_in_force=st.get("time_in_force", "DAY"))
        elif do == "sell":
            pmb.sell(session_id, account_id, st["symbol"], st["qty"])
        elif do == "buy_option":
            pmb.buy_option(session_id, account_id, st["contract"], st["qty"])
        elif do == "step":
            pmb.step(session_id, st["n"])
        elif do == "step_until":
            # the bar before ``ts``: the order then fills on the bar at ``ts``
            advance(until_ts=utc_iso(_ts(st["ts"]) - timedelta(minutes=1)))
        elif do == "run_to_end":
            advance()
        else:
            raise ValueError(f"unknown script step {do}")


def score_episode(pmb, ep: dict, account_id: str, session_id: str) -> dict[str, Any]:
    trades = pmb.get_trades(account_id, session_id)
    positions = pmb.get_positions(account_id)
    checks = evaluate(ep["checks"], trades, positions)
    return {"correct": all(c["ok"] for c in checks), "checks": checks,
            "trades": len(trades)}
