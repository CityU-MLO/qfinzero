"""Research layer: intraday factor mining and vectorised backtests over UPQ storage.

    from qfinzero.research import EvalConfig, evaluate_factor
    evaluate_factor(EvalConfig("cs_rank(-pct(close, 15))", "2026-08-03", "2026-08-21"))

CLI: ``qfz-research eval|backtest|fields``. MCP: ``research_eval_factor``,
``research_backtest``. Factor language: :mod:`qfinzero.research.expr`.
"""

from .evaluate import BacktestConfig, EvalConfig, backtest_factor, evaluate_factor
from .expr import BAR_FIELDS, FUNCTIONS, QUOTE_FIELDS, ExprError, compile_expr

__all__ = ["EvalConfig", "BacktestConfig", "evaluate_factor", "backtest_factor",
           "compile_expr", "ExprError", "FUNCTIONS", "BAR_FIELDS", "QUOTE_FIELDS"]
