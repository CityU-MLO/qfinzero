"""Factor evaluation and a vectorised intraday backtest.

Timing (both functions): the factor at bar ``t`` uses data up to the close of
``t``. A trade on it enters at the open of ``t+1`` (the close of ``t`` when
``t+1`` did not trade) and the forward return over ``h`` bars runs to the close
of ``t+h``, inside the same trading day. Evaluation samples every ``h`` bars so
the forward windows do not overlap.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Optional, Sequence

from .data import PanelSpec, Research
from .expr import compile_expr


@dataclass
class EvalConfig:
    expression: str
    start: str
    end: str
    universe: object = 500
    horizons: Sequence[int] = (5, 15, 30)
    session: str = "regular"
    bar_minutes: int = 1
    quantiles: int = 5
    min_names: int = 20
    cross_day: bool = False
    quotes: Optional[bool] = None      # None: join quotes if the factor uses them
    as_of_ns: Optional[int] = None


def _t(mean: float | None, std: float | None, n: int) -> float | None:
    if mean is None or not std or n < 2:
        return None
    return mean / std * math.sqrt(n)


def _r(x, k=6):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), k)


def _factor_table(r: Research, compiled, spec: PanelSpec) -> dict:
    meta = r.build_panel(spec)
    r.con.execute("DROP TABLE IF EXISTS _factor")
    r.con.execute(f"""CREATE TEMP TABLE _factor AS
        SELECT ticker, trade_date, window_start, minute, open, close, has_bar,
               {'spread,' if spec.quotes else ''} factor,
               row_number() OVER (PARTITION BY ticker, trade_date ORDER BY window_start) - 1 AS bar_idx
        FROM ({compiled.sql('_panel')})""")
    return meta


def evaluate_factor(cfg: EvalConfig, storage=None, threads=None) -> dict:
    """IC, rank IC, quantile returns, long-short spread and turnover per horizon."""
    t0 = time.perf_counter()
    compiled = compile_expr(cfg.expression, cross_day=cfg.cross_day)
    quotes = compiled.needs_quotes if cfg.quotes is None else cfg.quotes
    horizons = sorted({int(h) for h in cfg.horizons if int(h) >= 1})
    if not horizons:
        raise ValueError("horizons must contain positive integers")
    q = max(2, min(int(cfg.quantiles), 20))
    spec = PanelSpec(cfg.start, cfg.end, cfg.universe, cfg.session, cfg.bar_minutes, quotes,
                     as_of_ns=cfg.as_of_ns)
    out: dict = {"expression": cfg.expression, "config": {**asdict(cfg), "quotes": quotes},
                 "horizons": {}}
    with Research(storage, threads) as r:
        meta = _factor_table(r, compiled, spec)
        out["panel"] = {k: v for k, v in meta.items() if k != "days"} | {
            "start": meta["days"][0], "end": meta["days"][-1]}
        cov = r.con.execute("SELECT avg((factor IS NOT NULL)::INT) FROM _factor WHERE has_bar").fetchone()[0]
        out["panel"]["factor_coverage"] = _r(cov, 4)
        for h in horizons:
            out["horizons"][str(h)] = _eval_horizon(r, h, q, int(cfg.min_names))
    out["seconds"] = round(time.perf_counter() - t0, 2)
    out["bar_minutes"] = cfg.bar_minutes
    return out


def _eval_horizon(r: Research, h: int, q: int, min_names: int) -> dict:
    con = r.con
    con.execute("DROP TABLE IF EXISTS _fx")
    con.execute(f"""CREATE TEMP TABLE _fx AS
        WITH f AS (
            SELECT *, coalesce(lead(open, 1) OVER w, close) AS entry,
                   lead(close, {h}) OVER w AS exit_px
            FROM _factor WINDOW w AS (PARTITION BY ticker, trade_date ORDER BY window_start)
        )
        SELECT ticker, trade_date, window_start, minute, factor,
               exit_px / nullif(entry, 0) - 1 AS fwd
        FROM f
        WHERE bar_idx % {h} = 0 AND factor IS NOT NULL AND exit_px IS NOT NULL
          AND entry IS NOT NULL AND isfinite(factor)""")
    con.execute("DROP TABLE IF EXISTS _ic")
    con.execute(f"""CREATE TEMP TABLE _ic AS
        WITH ranked AS (
            SELECT *, percent_rank() OVER (PARTITION BY window_start ORDER BY factor) AS rf,
                      percent_rank() OVER (PARTITION BY window_start ORDER BY fwd) AS rr,
                      ntile({q}) OVER (PARTITION BY window_start ORDER BY factor) AS qt,
                      count(*) OVER (PARTITION BY window_start) AS n
            FROM _fx
        )
        SELECT * FROM ranked WHERE n >= {min_names}""")
    per = con.execute("""
        SELECT window_start, any_value(minute) AS minute, corr(factor, fwd) AS ic,
               corr(rf, rr) AS ric, count(*) AS n,
               avg(fwd) FILTER (WHERE qt = (SELECT max(qt) FROM _ic)) -
               avg(fwd) FILTER (WHERE qt = 1) AS ls
        FROM _ic GROUP BY window_start ORDER BY window_start""").fetchall()
    per = [p for p in per if p[2] is not None and not math.isnan(p[2])]
    n = len(per)
    if n == 0:
        return {"n_periods": 0, "note": "no periods with enough names (see min_names)"}

    def stats(vals):
        vals = [v for v in vals if v is not None and not math.isnan(v)]
        if not vals:
            return None, None, 0
        m = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) if len(vals) > 1 else None
        return m, sd, len(vals)

    ic_m, ic_s, ic_n = stats([p[2] for p in per])
    ric_m, ric_s, ric_n = stats([p[3] for p in per])
    ls_m, ls_s, ls_n = stats([p[5] for p in per])
    quant = con.execute("SELECT qt, avg(fwd) FROM _ic GROUP BY qt ORDER BY qt").fetchall()
    by_hour = con.execute("""
        SELECT minute // 60 AS hour_from_open, avg(ic), count(*) FROM (
            SELECT window_start, any_value(minute) AS minute, corr(factor, fwd) AS ic
            FROM _ic GROUP BY window_start) WHERE ic IS NOT NULL AND isfinite(ic)
        GROUP BY 1 ORDER BY 1""").fetchall()
    top = con.execute(f"""
        WITH t AS (SELECT ticker, trade_date, window_start, (qt = {q})::INT AS top FROM _ic),
        l AS (SELECT *, lag(top) OVER (PARTITION BY ticker, trade_date ORDER BY window_start) AS prev
              FROM t)
        SELECT sum(CASE WHEN top = 1 AND prev = 0 THEN 1 ELSE 0 END)::DOUBLE /
               nullif(sum(CASE WHEN top = 1 AND prev IS NOT NULL THEN 1 ELSE 0 END), 0)
        FROM l""").fetchone()[0]
    return {
        "n_periods": n,
        "avg_names": _r(sum(p[4] for p in per) / n, 1),
        "ic_mean": _r(ic_m), "ic_std": _r(ic_s), "icir": _r(ic_m / ic_s if ic_s else None, 4),
        "ic_t": _r(_t(ic_m, ic_s, ic_n), 3),
        "rank_ic_mean": _r(ric_m), "rank_icir": _r(ric_m / ric_s if ric_s else None, 4),
        "rank_ic_t": _r(_t(ric_m, ric_s, ric_n), 3),
        "ic_positive_share": _r(sum(1 for p in per if p[2] > 0) / n, 4),
        "quantile_fwd_bps": {str(k): _r(v * 1e4, 3) for k, v in quant},
        "long_short_bps": _r(ls_m * 1e4 if ls_m is not None else None, 3),
        "long_short_t": _r(_t(ls_m, ls_s, ls_n), 3),
        "top_quantile_turnover": _r(top, 4),
        "ic_by_hour_from_open": {str(int(hh)): {"ic": _r(v), "periods": int(c)} for hh, v, c in by_hour},
    }


# ── backtest ─────────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    expression: str
    start: str
    end: str
    universe: object = 500
    rebalance: int = 15             # bars between rebalances
    fraction: float = 0.1           # top/bottom share of names held
    long_short: bool = True
    cost_bps: float = 0.5           # per unit traded, on top of the half-spread
    use_spread: bool = True         # half the quoted spread when quotes exist, else spread_bps
    spread_bps: float = 2.0         # assumed full spread when no quotes
    session: str = "regular"
    bar_minutes: int = 1
    cross_day: bool = False
    min_names: int = 20
    as_of_ns: Optional[int] = None


def backtest_factor(cfg: BacktestConfig, storage=None, threads=None) -> dict:
    """Rank the universe on the factor every ``rebalance`` bars, hold the top
    (and short the bottom) ``fraction`` equal-weighted, flat at the close."""
    t0 = time.perf_counter()
    compiled = compile_expr(cfg.expression, cross_day=cfg.cross_day)
    k = int(cfg.rebalance)
    if k < 1:
        raise ValueError("rebalance must be >= 1")
    frac = min(max(float(cfg.fraction), 0.01), 0.5)
    spec = PanelSpec(cfg.start, cfg.end, cfg.universe, cfg.session, cfg.bar_minutes,
                     quotes=cfg.use_spread, as_of_ns=cfg.as_of_ns)
    with Research(storage, threads) as r:
        meta = _factor_table(r, compiled, spec)
        con = r.con
        spread_sql = (f"coalesce(spread, {cfg.spread_bps / 1e4})" if cfg.use_spread
                      else f"{cfg.spread_bps / 1e4}")
        # one row per (period, name held): weight, period return, half-spread
        rows = con.execute(f"""
            WITH f AS (
                SELECT *, coalesce(lead(open, 1) OVER w, close) AS entry,
                       coalesce(lead(close, {k}) OVER w, last_value(close) OVER wd) AS exit_px,
                       {spread_sql} / 2 AS half_spread
                FROM _factor
                WINDOW w AS (PARTITION BY ticker, trade_date ORDER BY window_start),
                       wd AS (PARTITION BY ticker, trade_date ORDER BY window_start
                              ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)
            ),
            s AS (
                SELECT *, count(*) OVER (PARTITION BY window_start) AS n,
                       row_number() OVER (PARTITION BY window_start ORDER BY factor DESC) AS rk_top,
                       row_number() OVER (PARTITION BY window_start ORDER BY factor ASC) AS rk_bot
                FROM f
                WHERE bar_idx % {k} = 0 AND factor IS NOT NULL AND isfinite(factor)
                  AND entry IS NOT NULL AND exit_px IS NOT NULL
            )
            SELECT trade_date::VARCHAR, window_start, ticker,
                   CASE WHEN rk_top <= greatest(1, CAST(floor(n * {frac}) AS INT)) THEN 1
                        ELSE -1 END AS side,
                   exit_px / entry - 1 AS r, half_spread
            FROM s
            WHERE n >= {int(cfg.min_names)} AND (
                  rk_top <= greatest(1, CAST(floor(n * {frac}) AS INT))
                  {"OR rk_bot <= greatest(1, CAST(floor(n * " + str(frac) + ") AS INT))" if cfg.long_short else ""})
            ORDER BY window_start""").fetchall()
    # weights per period, turnover vs the previous period of the same day (flat at day end)
    periods: dict[int, dict] = {}
    for day, ws, tkr, side, ret, hs in rows:
        p = periods.setdefault(ws, {"day": day, "long": {}, "short": {}})
        p["long" if side == 1 else "short"][tkr] = (ret, hs)
    out_periods = []
    prev_day, prev_w = None, {}
    for ws in sorted(periods):
        p = periods[ws]
        w: dict[str, float] = {}
        if p["long"]:
            for t in p["long"]:
                w[t] = w.get(t, 0.0) + 1.0 / len(p["long"])
        if cfg.long_short and p["short"]:
            for t in p["short"]:
                w[t] = w.get(t, 0.0) - 1.0 / len(p["short"])
        if p["day"] != prev_day:
            if prev_day is not None and prev_w:        # close yesterday's book at its last exit
                out_periods[-1]["cost"] += _cost(prev_w, {}, last_spreads, cfg)
            prev_w = {}
        spreads = {t: hs for t, (_, hs) in {**p["long"], **p["short"]}.items()}
        cost = _cost(prev_w, w, spreads, cfg)
        gross = sum(wt * ({**p["short"], **p["long"]}[t][0]) for t, wt in w.items())
        out_periods.append({"ws": ws, "day": p["day"], "gross": gross, "cost": cost,
                            "turnover": sum(abs(w.get(t, 0) - prev_w.get(t, 0)) for t in set(w) | set(prev_w))})
        prev_day, prev_w, last_spreads = p["day"], w, spreads
    if out_periods and prev_w:
        out_periods[-1]["cost"] += _cost(prev_w, {}, last_spreads, cfg)
    return _summary(cfg, meta, out_periods, time.perf_counter() - t0)


def _cost(prev_w: dict, w: dict, spreads: dict, cfg: BacktestConfig) -> float:
    total = 0.0
    for t in set(prev_w) | set(w):
        traded = abs(w.get(t, 0.0) - prev_w.get(t, 0.0))
        total += traded * (cfg.cost_bps / 1e4 + (spreads.get(t, cfg.spread_bps / 2e4)))
    return total


def _summary(cfg: BacktestConfig, meta: dict, periods: list[dict], seconds: float) -> dict:
    gross_scale = 2.0 if cfg.long_short else 1.0      # returns per unit of capital
    days: dict[str, list[float]] = {}
    equity, curve, peak, mdd = 1.0, [], 1.0, 0.0
    for p in periods:
        net = (p["gross"] - p["cost"]) / gross_scale
        p["net"] = net
        days.setdefault(p["day"], []).append(net)
    for day in sorted(days):
        d_ret = math.prod(1 + x for x in days[day]) - 1
        equity *= 1 + d_ret
        peak = max(peak, equity)
        mdd = min(mdd, equity / peak - 1)
        curve.append({"date": day, "return": _r(d_ret, 6), "equity": _r(equity, 6)})
    dr = [c["return"] for c in curve]
    mean = sum(dr) / len(dr) if dr else 0.0
    sd = math.sqrt(sum((x - mean) ** 2 for x in dr) / (len(dr) - 1)) if len(dr) > 1 else None
    gross_total = sum(p["gross"] for p in periods) / gross_scale
    cost_total = sum(p["cost"] for p in periods) / gross_scale
    return {
        "expression": cfg.expression,
        "config": asdict(cfg),
        "panel": {k: v for k, v in meta.items() if k != "days"},
        "periods": len(periods),
        "days": len(curve),
        "total_return": _r(equity - 1, 6),
        "mean_daily_bps": _r(mean * 1e4, 3),
        "sharpe_annualized": _r(mean / sd * math.sqrt(252) if sd else None, 3),
        "max_drawdown": _r(mdd, 6),
        "hit_rate_days": _r(sum(1 for x in dr if x > 0) / len(dr), 4) if dr else None,
        "avg_turnover_per_rebalance": _r(
            sum(p["turnover"] for p in periods) / len(periods) / gross_scale, 4) if periods else None,
        "gross_return_sum": _r(gross_total, 6),
        "cost_sum": _r(cost_total, 6),
        "equity_curve": curve,
        "seconds": round(seconds, 2),
    }
