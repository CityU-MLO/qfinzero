"""Simulate the synthetic market and write it in UPQ storage format.

Prices follow a one-minute factor model: a market factor (with macro-release
jumps), a sector factor, and an idiosyncratic part (with earnings jumps), on a
04:00-20:00 ET grid every trading day plus an overnight gap. Daily bars are
built from the minutes exactly as the vendor pipelines do (O/H/L/C from the
regular session, volume from the whole day), so minute and daily data agree.

Options are priced with Black-Scholes on a smile whose level carries an
earnings premium until the report and drops after it. Trades print sparsely;
quotes are the theoretical value plus a spread.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from ..pipeline import schema as S
from .universe import (BY_TICKER, OVERNIGHT_TICKERS, Universe, Stock)

ET = ZoneInfo("America/New_York")
NS = 1_000_000_000
GRID_START, GRID_END = 4 * 60, 20 * 60          # 04:00 .. 20:00 ET (minutes)
RTH_START, RTH_END = 9 * 60 + 30, 16 * 60
N_MIN = GRID_END - GRID_START                     # 960
MARKET_VOL = 0.16
SECTOR_VOL = 0.10
RATE = 0.043
TRADE_SIZE = 120                                  # avg shares per trade
OPTION_IV = {"QZSP": 0.15, "ACME": 0.34, "BOLT": 0.62}
STRIKE_STEP = {"QZSP": 5.0, "ACME": 5.0, "BOLT": 1.0}


def et_ns(d: date, minute: int) -> int:
    """UTC ns of ``minute`` minutes after 00:00 ET on ``d`` (DST-aware)."""
    base = datetime(d.year, d.month, d.day, tzinfo=ET) + timedelta(minutes=minute)
    return int(base.astimezone(timezone.utc).timestamp()) * NS


def norm_cdf(x):
    return 0.5 * (1.0 + np.vectorize(math.erf)(np.asarray(x) / math.sqrt(2.0)))


def bs_price(s, k, t, r, iv, call):
    s, k, t, iv = map(np.asarray, (s, k, t, iv))
    t = np.maximum(t, 1e-6)
    sd = iv * np.sqrt(t)
    d1 = (np.log(s / k) + (r + 0.5 * iv * iv) * t) / sd
    d2 = d1 - sd
    if call:
        return s * norm_cdf(d1) - k * np.exp(-r * t) * norm_cdf(d2)
    return k * np.exp(-r * t) * norm_cdf(-d2) - s * norm_cdf(-d1)


# ── price paths ──────────────────────────────────────────────────────────

@dataclass
class Paths:
    """Raw (as-traded) minute closes per stock and day on the 04:00-20:00 grid,
    plus per-minute volume and the overnight bars of the overnight venue."""
    close: dict[str, dict[date, np.ndarray]]
    volume: dict[str, dict[date, np.ndarray]]
    overnight: dict[str, dict[date, tuple[np.ndarray, np.ndarray, np.ndarray]]]  # (ts, close, vol)
    split_factor: dict[str, dict[date, float]]    # raw = economic * factor


def _profile() -> np.ndarray:
    m = np.arange(GRID_START, GRID_END)
    p = np.full(N_MIN, 0.015)
    rth = (m >= RTH_START) & (m < RTH_END)
    x = (m[rth] - RTH_START) / (RTH_END - RTH_START)
    p[rth] = 0.6 + 2.2 * (x - 0.5) ** 2 * 4 / 4 + 1.6 * np.exp(-x * 30) + 1.2 * np.exp(-(1 - x) * 25)
    return p / p[rth].sum()


def _vol_scale() -> np.ndarray:
    m = np.arange(GRID_START, GRID_END)
    v = np.full(N_MIN, 0.35)
    v[(m >= RTH_START) & (m < RTH_END)] = 1.0
    return v


def simulate(u: Universe) -> Paths:
    rng = np.random.default_rng(u.seed)
    per_min = 1.0 / math.sqrt(252 * 390)
    prof, vscale = _profile(), _vol_scale()
    sectors = sorted({s.sector for s in u.stocks})
    last_econ = {s.ticker: s.price for s in u.stocks}
    close: dict = {s.ticker: {} for s in u.stocks}
    volume: dict = {s.ticker: {} for s in u.stocks}
    overnight: dict = {t: {} for t in OVERNIGHT_TICKERS}
    split_factor: dict = {s.ticker: {} for s in u.stocks}
    minute_set = set(u.minute_days)
    earn = {(e.ticker, e.day): e for e in u.earnings}
    macro_by_day: dict[date, list] = {}
    for e in u.macro:
        macro_by_day.setdefault(e.day, []).append(e)
    dividends = _dividend_days(u)

    for di, day in enumerate(u.days):
        # overnight gap into today (weekends/holidays scale with calendar time)
        gap_days = (day - u.days[di - 1]).days if di else 1
        g_mkt = rng.normal(0, MARKET_VOL / math.sqrt(252) * 0.5 * math.sqrt(gap_days))
        g_sec = {sec: rng.normal(0, SECTOR_VOL / math.sqrt(252) * 0.4) for sec in sectors}
        mkt = rng.normal(0, MARKET_VOL * per_min, N_MIN) * vscale
        sec_r = {sec: rng.normal(0, SECTOR_VOL * per_min, N_MIN) * vscale for sec in sectors}
        for ev in macro_by_day.get(day, []):
            hh, mm = map(int, ev.time_et.split(":"))
            mkt[hh * 60 + mm - GRID_START] += ev.jump
        for s in u.stocks:
            beta = s.beta
            idio_vol = s.vol * per_min
            r = beta * mkt + (0 if s.sector == "Index" else 1) * sec_r[s.sector] \
                + rng.normal(0, idio_vol, N_MIN) * vscale
            gap = beta * g_mkt + (0 if s.sector == "Index" else g_sec[s.sector]) \
                + rng.normal(0, s.vol / math.sqrt(252) * 0.35)
            ev = earn.get((s.ticker, day))
            vmult = np.ones(N_MIN)
            if ev is not None:
                at = (16 * 60 + 5 if ev.timing == "AMC" else 7 * 60) - GRID_START
                r[at] += ev.jump
                vmult[at:at + 45] *= 6.0
                if ev.timing == "BMO":
                    vmult[RTH_START - GRID_START:RTH_START - GRID_START + 60] *= 3.0
            prev_after = earn.get((s.ticker, u.days[di - 1])) if di else None
            if prev_after is not None and prev_after.timing == "AMC":
                vmult[RTH_START - GRID_START:RTH_START - GRID_START + 90] *= 4.0
            econ_open = last_econ[s.ticker] * math.exp(gap)
            factor = 1.0
            if s.split and day < date.fromisoformat(s.split[0]):
                factor = s.split[1]
            # overnight venue bars for the night before (Mon-Thu nights only): a
            # Brownian bridge from yesterday's 20:00 price to today's 04:00 price
            if s.ticker in overnight and day in minute_set and di and gap_days == 1:
                ts = np.array([et_ns(u.days[di - 1], 20 * 60 + i) for i in range(240)]
                              + [et_ns(day, i) for i in range(240)], dtype=np.int64)
                w = np.cumsum(rng.normal(0, s.vol * per_min * 0.5 + 1e-5, 480))
                bridge = w - np.linspace(0, 1, 480) * w[-1]
                drift = np.linspace(0, math.log(econ_open / last_econ[s.ticker]), 480)
                path = np.round(last_econ[s.ticker] * np.exp(drift + bridge) * factor, 2)
                ovol = np.maximum(1, rng.lognormal(math.log(s.adv * 0.0015 / 480), 0.8, 480)).astype(np.int64)
                overnight[s.ticker][day] = (ts, path, ovol)
            # dividend: raw price drops by the cash amount at today's start
            if (s.ticker, day) in dividends:
                econ_open -= s.dividend
            path = econ_open * np.exp(np.cumsum(r))
            last_econ[s.ticker] = float(path[-1])
            split_factor[s.ticker][day] = factor
            close[s.ticker][day] = np.round(path * factor, 2)   # stocks trade in cents
            base = s.adv * prof * np.exp(rng.normal(0, 0.45, N_MIN)) * vmult
            volume[s.ticker][day] = np.maximum(1, base / factor).astype(np.int64)
    return Paths(close, volume, overnight, split_factor)


def _dividend_days(u: Universe) -> set[tuple[str, date]]:
    out = set()
    payers = [s for s in u.stocks if s.dividend > 0]
    for i, s in enumerate(payers):
        out.add((s.ticker, u.days[14 + 4 * i]))
    return out


# ── writing UPQ storage ──────────────────────────────────────────────────

def _write(table, out: Path) -> int:
    import pyarrow.parquet as pq
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="zstd")
    return table.num_rows


def _table(cols: dict, schema: dict):
    import pyarrow as pa
    types = {"VARCHAR": pa.string(), "DATE": pa.date32(), "DOUBLE": pa.float64(),
             "BIGINT": pa.int64()}
    return pa.table({c: pa.array(cols[c], type=types[t]) for c, t in schema.items()})


def _bars_from_closes(c: np.ndarray, rng, prev: float):
    o = np.concatenate([[prev], c[:-1]])
    wig = np.abs(rng.normal(0, 0.0004, len(c)))
    h = np.maximum(o, c) * (1 + wig)
    lo = np.minimum(o, c) * (1 - wig)
    return o, h, lo


def write_stocks(u: Universe, p: Paths, root: Path) -> dict:
    rng = np.random.default_rng(u.seed + 1)
    counts = {"stock_daily": 0, "stock_minute": 0}
    rth = slice(RTH_START - GRID_START, RTH_END - GRID_START)
    minute_set = set(u.minute_days)
    prev_close = {s.ticker: s.price for s in u.stocks}
    for di, day in enumerate(u.days):
        daily = {c: [] for c in S.STOCK_DAILY}
        minute = {c: [] for c in S.STOCK_MINUTE}
        for s in u.stocks:
            c = p.close[s.ticker][day]
            v = p.volume[s.ticker][day]
            o, h, lo = _bars_from_closes(c, rng, c[0] / (1 + 1e-4))
            n = np.maximum(1, v // TRADE_SIZE)
            daily["ticker"].append(s.ticker)
            daily["trade_date"].append(day)
            daily["open"].append(round(float(o[rth][0]), 2))
            daily["high"].append(round(float(h[rth].max()), 2))
            daily["low"].append(round(float(lo[rth].min()), 2))
            daily["close"].append(round(float(c[rth][-1]), 2))
            daily["volume"].append(int(v.sum()))
            daily["transactions"].append(int(n.sum()))
            prev_close[s.ticker] = float(c[rth][-1])
            if day in minute_set:
                ts = np.array([et_ns(day, GRID_START + i) for i in range(N_MIN)], dtype=np.int64)
                rows = [(int(t), round(float(a), 2), round(float(b), 2), round(float(d), 2),
                         round(float(e), 2), int(f), int(g))
                        for t, a, b, d, e, f, g in zip(ts, o, h, lo, c, v, n)]
                if s.ticker in p.overnight and day in p.overnight[s.ticker]:
                    ots, oc, ov = p.overnight[s.ticker][day]
                    oo, oh, ol = _bars_from_closes(oc, rng, oc[0])
                    rows += [(int(t), round(float(a), 2), round(float(b), 2), round(float(d), 2),
                              round(float(e), 2), int(f), max(1, int(f) // 50))
                             for t, a, b, d, e, f in zip(ots, oo, oh, ol, oc, ov)]
                for t, a, b, d, e, f, g in rows:
                    minute["ticker"].append(s.ticker)
                    minute["window_start"].append(t)
                    minute["open"].append(a)
                    minute["high"].append(b)
                    minute["low"].append(d)
                    minute["close"].append(e)
                    minute["volume"].append(f)
                    minute["transactions"].append(g)
                    minute["trade_date"].append(_et_date(t))
        counts["stock_daily"] += _write(_table(daily, S.STOCK_DAILY),
                                        root / "stock_daily" / f"trade_date={day}" / "part-0000.parquet")
        if minute["ticker"]:
            counts["stock_minute"] += _write_partitioned(minute, S.STOCK_MINUTE, root / "stock_minute")
    return counts


def _et_date(ns: int) -> date:
    return datetime.fromtimestamp(ns / NS, tz=timezone.utc).astimezone(ET).date()


def _write_partitioned(cols: dict, schema: dict, store: Path) -> int:
    """Split rows by their trade_date column and append one part per date."""
    by: dict[date, list[int]] = {}
    for i, d in enumerate(cols["trade_date"]):
        by.setdefault(d, []).append(i)
    n = 0
    for d, idx in by.items():
        sub = {c: [cols[c][i] for i in idx] for c in schema}
        part = store / f"trade_date={d}"
        k = len(list(part.glob("part-*.parquet"))) if part.is_dir() else 0
        n += _write(_table(sub, schema), part / f"part-{k:04d}.parquet")
    return n


def _expiries(u: Universe) -> list[date]:
    fridays = []
    d = u.days[0]
    while d <= date(2025, 6, 20):
        if d.weekday() == 4:
            fridays.append(d)
        d += timedelta(days=1)
    weekly = [f for f in fridays if f <= u.days[-1] + timedelta(days=14)]
    monthly = [f for f in fridays if f > u.days[-1] + timedelta(days=14) and 15 <= f.day <= 21]
    from .universe import HOLIDAYS
    out = []
    for f in weekly + monthly:
        out.append(f - timedelta(days=1) if f in HOLIDAYS else f)
    return out


def occ(underlying: str, expiry: date, right: str, strike: float) -> str:
    return f"O:{underlying}{expiry:%y%m%d}{right}{int(round(strike * 1000)):08d}"


def _iv(u: Universe, und: str, day: date, expiry: date, k: float, s: float) -> float:
    """Smile plus, while an earnings report covered by the expiry is still
    pending on ``day``, the event's variance spread over the time to expiry.
    A BMO report is out before the open (premium gone that day); an AMC
    report is pending all day."""
    base = OPTION_IV[und]
    m = math.log(k / s)
    smile = base * (1 - 0.9 * m + 1.6 * m * m)
    for e in u.earnings:
        pending = e.day > day or (e.day == day and e.timing == "AMC")
        if e.ticker == und and pending and e.day <= expiry:
            t = max((expiry - day).days, 1) / 365
            ev_var = (abs(e.jump) * 1.1) ** 2          # ~ the size of the move
            return math.sqrt(smile ** 2 + ev_var / t)
    return smile


def write_options(u: Universe, p: Paths, root: Path) -> dict:
    """Daily bars for every listed contract that traded, minute trades and
    minute quotes in the minute window."""
    rng = np.random.default_rng(u.seed + 2)
    expiries = _expiries(u)
    counts = {"option_day": 0, "option_minute": 0, "option_quote_minute": 0}
    rth_idx = np.arange(RTH_START - GRID_START, RTH_END - GRID_START)
    minute_set = set(u.minute_days)
    for und in OPTION_IV:
        s0 = BY_TICKER[und].price
        step = STRIKE_STEP[und]
        lo, hi = s0 * 0.7, s0 * 1.35
        strikes = np.arange(math.floor(lo / step) * step, hi + step, step)
        for day in u.days:
            spot_close = float(p.close[und][day][RTH_END - GRID_START - 1])
            live = [e for e in expiries if e >= day]
            day_cols = {c: [] for c in S.OPTION_DAY}
            min_cols = {c: [] for c in S.OPTION_MINUTE}
            q_cols = {c: [] for c in S.OPTION_QUOTE_MINUTE}
            for ex in live:
                t_close = ((ex - day).days + 0.0) / 365
                for k in strikes:
                    if abs(math.log(k / spot_close)) > 0.30:
                        continue
                    for right in ("C", "P"):
                        iv = _iv(u, und, day, ex, k, spot_close)
                        theo = float(bs_price(spot_close, k, t_close + 1 / 365, RATE, iv, right == "C"))
                        if theo < 0.05:
                            continue
                        mny = abs(math.log(k / spot_close))
                        lam = 400 * math.exp(-mny * 18) * (1.6 if (ex - day).days <= 7 else 1.0)
                        vol = int(rng.poisson(lam))
                        contract = occ(und, ex, right, float(k))
                        if vol > 0:
                            jitter = rng.normal(0, 0.03, 3)
                            o_ = max(0.01, theo * (1 + jitter[0]))
                            c_ = max(0.01, theo * (1 + jitter[1] * 0.3))
                            for col, val in (("ticker", contract), ("contract", contract),
                                             ("underlying", und), ("expiry", ex),
                                             ("strike", float(k)), ("right", right),
                                             ("window_start", et_ns(day, 0)),
                                             ("open", round(o_, 2)),
                                             ("high", round(max(o_, c_) * (1 + abs(jitter[2])), 2)),
                                             ("low", round(min(o_, c_) * (1 - abs(jitter[2])), 2)),
                                             ("close", round(c_, 2)), ("volume", vol),
                                             ("transactions", max(1, vol // 4)),
                                             ("trade_date", day)):
                                day_cols[col].append(val)
                        if day not in minute_set or mny > 0.10 or ex not in live[:4]:
                            continue
                        # minute path: theo along the underlying's regular-session minutes
                        spots = p.close[und][day][rth_idx]
                        mins = RTH_START + np.arange(len(rth_idx))
                        tt = np.maximum(((ex - day).days * 1440 + 16 * 60 - mins) / (365 * 1440), 1 / (365 * 1440))
                        ivs = np.array([_iv(u, und, day, ex, k, float(sp)) for sp in spots[::30]])
                        ivs = np.repeat(ivs, 30)[:len(spots)]
                        theos = bs_price(spots, k, tt, RATE, ivs, right == "C")
                        half = np.maximum(0.01, np.round(theos * 0.025, 2)) + 0.01
                        tick = 0.01 if und != "QZSP" else 0.01
                        bid = np.maximum(0.0, np.round((theos - half) / tick) * tick)
                        ask = np.round((theos + half) / tick) * tick
                        bsz = rng.integers(5, 200, len(theos))
                        asz = rng.integers(5, 200, len(theos))
                        ts = np.array([et_ns(day, int(m)) for m in mins], dtype=np.int64)
                        for i in range(len(ts)):
                            q_cols["ticker"].append(contract)
                            q_cols["contract"].append(contract)
                            q_cols["underlying"].append(und)
                            q_cols["expiry"].append(ex)
                            q_cols["strike"].append(float(k))
                            q_cols["right"].append(right)
                            q_cols["window_start"].append(int(ts[i]))
                            q_cols["bid_price"].append(round(float(bid[i]), 2))
                            q_cols["ask_price"].append(round(float(ask[i]), 2))
                            q_cols["bid_size"].append(int(bsz[i]))
                            q_cols["ask_size"].append(int(asz[i]))
                            q_cols["trade_date"].append(day)
                        p_trade = min(0.6, lam / 390 * 1.5)
                        traded = np.nonzero(rng.random(len(ts)) < p_trade)[0]
                        for i in traded:
                            px = float(bid[i] if rng.random() < 0.5 else ask[i])
                            px = max(px, 0.01)
                            q = int(rng.integers(1, 20))
                            for col, val in (("ticker", contract), ("contract", contract),
                                             ("underlying", und), ("expiry", ex),
                                             ("strike", float(k)), ("right", right),
                                             ("window_start", int(ts[i])), ("open", px),
                                             ("high", px), ("low", px), ("close", px),
                                             ("volume", q), ("transactions", 1), ("trade_date", day)):
                                min_cols[col].append(val)
            if day_cols["ticker"]:
                counts["option_day"] += _write_partitioned(day_cols, S.OPTION_DAY, root / "option_day")
            if min_cols["ticker"]:
                counts["option_minute"] += _write_partitioned(min_cols, S.OPTION_MINUTE, root / "option_minute")
            if q_cols["ticker"]:
                counts["option_quote_minute"] += _write_partitioned(
                    q_cols, S.OPTION_QUOTE_MINUTE, root / "option_quote_minute")
    return counts


def write_stock_quotes(u: Universe, p: Paths, root: Path) -> int:
    """Regular-session minute NBBO for every stock in the minute window."""
    rng = np.random.default_rng(u.seed + 3)
    n = 0
    rth_idx = np.arange(RTH_START - GRID_START, RTH_END - GRID_START)
    for day in u.minute_days:
        cols = {c: [] for c in S.STOCK_QUOTE_MINUTE}
        for s in u.stocks:
            c = p.close[s.ticker][day][rth_idx]
            spread = np.maximum(0.01, np.round(c * rng.uniform(0.00005, 0.0004), 2))
            bid = np.round(c - spread / 2, 2)
            ask = np.maximum(bid + 0.01, np.round(c + spread / 2, 2))
            imb = rng.normal(0, 0.4, len(c))
            depth = (s.adv / 2000) * np.exp(rng.normal(0, 0.5, len(c)))
            bsz = np.maximum(1, depth * (1 + imb)).astype(np.int64)
            asz = np.maximum(1, depth * (1 - imb)).astype(np.int64)
            for i, m in enumerate(RTH_START + np.arange(len(rth_idx))):
                cols["ticker"].append(s.ticker)
                cols["window_start"].append(et_ns(day, int(m)))
                cols["bid_price"].append(float(bid[i]))
                cols["ask_price"].append(float(ask[i]))
                cols["bid_size"].append(int(bsz[i]))
                cols["ask_size"].append(int(asz[i]))
                cols["trade_date"].append(day)
        n += _write(_table(cols, S.STOCK_QUOTE_MINUTE),
                    root / "stock_quote_minute" / f"trade_date={day}" / "part-0000.parquet")
    return n


def write_reference(u: Universe, p: Paths, root: Path) -> dict:
    """Rates, the unified corporate-actions table and the dividends store."""
    rng = np.random.default_rng(u.seed + 4)
    tenors = [("yield_1_month", 4.33), ("yield_3_month", 4.31), ("yield_1_year", 4.17),
              ("yield_2_year", 4.25), ("yield_5_year", 4.38), ("yield_10_year", 4.57),
              ("yield_30_year", 4.79)]
    rates = {"date": list(u.days)}
    level = 0.0
    shifts = []
    for _ in u.days:
        level += rng.normal(0, 0.03)
        shifts.append(level)
    for name, base in tenors:
        rates[name] = [round(base + sh * (0.6 if "month" in name else 1.0), 3) for sh in shifts]
    n_rates = _write(_table(rates, S.RATES), root / "rates" / "rates.parquet")
    ca = {c: [] for c in S.CORPORATE_ACTIONS}
    divs = {c: [] for c in S.DIVIDENDS}
    rth_last = RTH_END - GRID_START - 1
    for (ticker, day) in sorted(_dividend_days(u), key=lambda x: x[1]):
        s = BY_TICKER[ticker]
        prev = u.days[u.days.index(day) - 1]
        prev_close = float(p.close[ticker][prev][rth_last])
        for col, val in (("symbol", ticker), ("ex_date", day), ("split_ratio", 1.0),
                         ("dividend_cash", s.dividend),
                         ("div_price_ratio", round(1 - s.dividend / prev_close, 8)),
                         ("currency", "USD"), ("source", "qfinzero-sample")):
            ca[col].append(val)
        divs["ticker"].append(ticker)
        divs["ex_dividend_date"].append(day)
        divs["amount"].append(s.dividend)
    for s in u.stocks:
        if s.split:
            for col, val in (("symbol", s.ticker), ("ex_date", date.fromisoformat(s.split[0])),
                             ("split_ratio", s.split[1]), ("dividend_cash", 0.0),
                             ("div_price_ratio", 1.0), ("currency", "USD"),
                             ("source", "qfinzero-sample")):
                ca[col].append(val)
    n_ca = _write(_table(ca, S.CORPORATE_ACTIONS), root / "corporate_actions" / "corporate_actions.parquet")
    n_div = _write(_table(divs, S.DIVIDENDS), root / "dividends" / "dividends.parquet")
    return {"rates": n_rates, "corporate_actions": n_ca, "dividends": n_div}
