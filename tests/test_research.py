"""Research layer: factor language safety, point-in-time panel, IC and backtest
on synthetic data with a planted signal."""

from __future__ import annotations

import os
import sys

import pytest

duckdb = pytest.importorskip("duckdb")
np = pytest.importorskip("numpy")
pa = pytest.importorskip("pyarrow")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero.research import (BacktestConfig, EvalConfig, ExprError,  # noqa: E402
                               backtest_factor, compile_expr, evaluate_factor)
from qfinzero.research.data import PanelSpec, Research  # noqa: E402

S = 1_000_000_000
DAYS = {"2025-01-02": 1735828200, "2025-01-03": 1735914600}   # 09:30 EST in UTC seconds
N_TICKERS = 40


@pytest.fixture(scope="module")
def storage(tmp_path_factory):
    """40 tickers x 2 days x 390 minutes. Next-minute return = 0.002 * z(log volume)
    across tickers + noise, so cs_rank(volume) predicts returns."""
    root = tmp_path_factory.mktemp("upq")
    rng = np.random.default_rng(7)
    con = duckdb.connect()
    tickers = [f"T{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(N_TICKERS)]
    for day, t0 in DAYS.items():
        logv = rng.normal(8, 1, size=(390, N_TICKERS))
        z = (logv - logv.mean(axis=1, keepdims=True)) / logv.std(axis=1, keepdims=True)
        ret = np.zeros((390, N_TICKERS))
        ret[1:] = 0.002 * z[:-1] + rng.normal(0, 0.001, size=(389, N_TICKERS))
        close = 100 * np.cumprod(1 + ret, axis=0)
        open_ = np.vstack([close[:1], close[:-1]])
        rows = {"ticker": [], "window_start": [], "open": [], "high": [], "low": [], "close": [],
                "volume": [], "transactions": []}
        for m in range(390):
            for j, t in enumerate(tickers):
                o, c = open_[m, j], close[m, j]
                rows["ticker"].append(t)
                rows["window_start"].append((t0 + 60 * m) * S)
                rows["open"].append(o); rows["close"].append(c)
                rows["high"].append(max(o, c)); rows["low"].append(min(o, c))
                rows["volume"].append(int(np.exp(logv[m, j])))
                rows["transactions"].append(10)
        tbl = pa.table(rows)
        d = root / "stock_minute" / f"trade_date={day}"
        d.mkdir(parents=True)
        con.register("t", tbl)
        con.execute(f"COPY (SELECT *, DATE '{day}' AS trade_date FROM t) TO '{d / 'part-0000.parquet'}' (FORMAT PARQUET)")
        con.unregister("t")
    # daily bars: the previous day ranks the universe (ticker index = dollar volume rank)
    for day in ("2024-12-31", "2025-01-02", "2025-01-03"):
        d = root / "stock_daily" / f"trade_date={day}"
        d.mkdir(parents=True)
        vals = ", ".join(f"('{t}', DATE '{day}', 100.0, 101.0, 99.0, 100.0, {1_000_000 * (N_TICKERS - i)}, 10)"
                         for i, t in enumerate(tickers))
        con.execute(f"COPY (SELECT * FROM (VALUES {vals}) v(ticker, trade_date, open, high, low, close, "
                    f"volume, transactions)) TO '{d / 'part-0000.parquet'}' (FORMAT PARQUET)")
    return root


# ── language ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    "delay(close, -1)", "delay(close, 0)", "ts_mean(close, 0)", "close.__class__",
    "__import__('os')", "foo + 1", "ts_mean(close, n)", "close ** 2", "lambda: 1",
    "ts_mean(close, window=5)", "open if close else high",
])
def test_rejects_lookahead_and_unsafe_syntax(bad):
    with pytest.raises(ExprError):
        compile_expr(bad)


def test_compiles_nested_windows():
    c = compile_expr("cs_rank(ts_mean(pct(close, 5), 10)) * -ts_corr(ret, delta(volume, 1), 30)")
    assert c.max_window == 30 and not c.needs_quotes and "factor" in c.layers[-1]
    assert compile_expr("spread * imbalance").needs_quotes


def test_time_series_windows_are_backward_and_full(storage):
    with Research(storage) as r:
        r.build_panel(PanelSpec("2025-01-02", "2025-01-02", ["TAA"]))
        rows = r.con.execute(compile_expr("ts_mean(close, 3)").sql("_panel") +
                             " ORDER BY window_start LIMIT 4").fetchall()
        cols = [d[0] for d in r.con.description]
    f = [row[cols.index("factor")] for row in rows]
    c = [row[cols.index("close")] for row in rows]
    assert f[0] is None and f[1] is None                 # window not full yet
    assert f[2] == pytest.approx(sum(c[:3]) / 3)         # only bars up to t
    assert f[3] == pytest.approx(sum(c[1:4]) / 3)


def test_universe_is_ranked_on_the_previous_day(storage):
    with Research(storage) as r:
        meta = r.build_panel(PanelSpec("2025-01-02", "2025-01-03", 10))
        got = {t for (t,) in r.con.execute("SELECT DISTINCT ticker FROM _panel").fetchall()}
    assert meta["tickers"] == 10 and meta["n_days"] == 2
    assert got == {f"TA{chr(65 + i)}" for i in range(10)}


def test_as_of_truncates_the_panel(storage):
    cap = (DAYS["2025-01-02"] + 60 * 30) * S             # 10:00 ET
    with Research(storage) as r:
        r.build_panel(PanelSpec("2025-01-02", "2025-01-03", 5, as_of_ns=cap))
        last_real = r.con.execute("SELECT max(window_start) FROM _panel WHERE has_bar").fetchone()[0]
    assert last_real == cap - 60 * S


# ── evaluation + backtest ───────────────────────────────────────────────

def test_planted_signal_has_positive_ic_and_its_negation_negative(storage):
    res = evaluate_factor(EvalConfig("cs_rank(log(volume))", "2025-01-02", "2025-01-03",
                                     universe=N_TICKERS, horizons=[1, 5], min_names=10), storage)
    h1 = res["horizons"]["1"]
    assert h1["ic_mean"] > 0.3 and h1["rank_ic_t"] > 10
    q = h1["quantile_fwd_bps"]
    assert q["5"] > q["1"] and h1["long_short_bps"] > 0
    neg = evaluate_factor(EvalConfig("-cs_rank(log(volume))", "2025-01-02", "2025-01-03",
                                     universe=N_TICKERS, horizons=[1], min_names=10), storage)
    assert neg["horizons"]["1"]["ic_mean"] < -0.3
    noise = evaluate_factor(EvalConfig("cs_rank(transactions)", "2025-01-02", "2025-01-03",
                                       universe=N_TICKERS, horizons=[1], min_names=10), storage)
    assert noise["horizons"]["1"].get("n_periods", 0) == 0 or \
        abs(noise["horizons"]["1"]["ic_mean"] or 0) < 0.05


def test_backtest_profits_from_the_planted_signal_and_costs_bite(storage):
    cfg = dict(expression="log(volume)", start="2025-01-02", end="2025-01-03", universe=N_TICKERS,
               rebalance=1, fraction=0.2, min_names=10, use_spread=False)
    free = backtest_factor(BacktestConfig(**cfg, cost_bps=0.0, spread_bps=0.0), storage)
    costly = backtest_factor(BacktestConfig(**cfg, cost_bps=5.0, spread_bps=2.0), storage)
    assert free["days"] == 2 and free["total_return"] > 0.1 and free["sharpe_annualized"] > 5
    assert costly["total_return"] < free["total_return"] and costly["cost_sum"] > 0
    assert len(free["equity_curve"]) == 2
