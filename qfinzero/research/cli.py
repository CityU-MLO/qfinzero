"""``qfz-research`` — evaluate and backtest intraday factors from the shell.

    qfz-research fields
    qfz-research eval "cs_rank(-pct(close, 15))" --start 2026-08-03 --end 2026-08-21 --horizons 5,15,30
    qfz-research backtest "cs_rank(-pct(close, 15))" --start 2026-08-03 --end 2026-08-21 --rebalance 15
"""

from __future__ import annotations

import argparse
import json
import sys

from .evaluate import BacktestConfig, EvalConfig, backtest_factor, evaluate_factor
from .expr import BAR_FIELDS, FUNCTIONS, QUOTE_FIELDS, ExprError


def _universe(v: str):
    v = (v or "500").strip()
    return int(v) if v.isdigit() else [t.strip().upper() for t in v.split(",") if t.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qfz-research", description=__doc__.splitlines()[0])
    ap.add_argument("--storage", help="override STORAGE_ROOT")
    ap.add_argument("--threads", type=int)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fields", help="list fields and functions of the factor language")
    for name in ("eval", "backtest"):
        p = sub.add_parser(name)
        p.add_argument("expression")
        p.add_argument("--start", required=True)
        p.add_argument("--end", required=True)
        p.add_argument("--universe", default="500", help="top-N by prior-day $ volume, or AAPL,MSFT,...")
        p.add_argument("--session", default="regular", choices=["regular", "extended"])
        p.add_argument("--bar-minutes", type=int, default=1)
        p.add_argument("--cross-day", action="store_true", help="time-series windows span days")
        p.add_argument("--min-names", type=int, default=20)
    e = sub.choices["eval"]
    e.add_argument("--horizons", default="5,15,30")
    e.add_argument("--quantiles", type=int, default=5)
    b = sub.choices["backtest"]
    b.add_argument("--rebalance", type=int, default=15)
    b.add_argument("--fraction", type=float, default=0.1)
    b.add_argument("--long-only", action="store_true")
    b.add_argument("--cost-bps", type=float, default=0.5)
    b.add_argument("--spread-bps", type=float, default=2.0)
    b.add_argument("--no-quotes", action="store_true", help="ignore quoted spreads")
    args = ap.parse_args(argv)
    if args.cmd == "fields":
        print(json.dumps({"bar_fields": sorted(BAR_FIELDS), "quote_fields": sorted(QUOTE_FIELDS),
                          "functions": {k: v[1] for k, v in sorted(FUNCTIONS.items())}}, indent=2))
        return 0
    common = dict(expression=args.expression, start=args.start, end=args.end,
                  universe=_universe(args.universe), session=args.session,
                  bar_minutes=args.bar_minutes, cross_day=args.cross_day, min_names=args.min_names)
    try:
        if args.cmd == "eval":
            res = evaluate_factor(EvalConfig(
                **common, horizons=[int(h) for h in args.horizons.split(",")],
                quantiles=args.quantiles), args.storage, args.threads)
        else:
            res = backtest_factor(BacktestConfig(
                **common, rebalance=args.rebalance, fraction=args.fraction,
                long_short=not args.long_only, cost_bps=args.cost_bps,
                spread_bps=args.spread_bps, use_spread=not args.no_quotes),
                args.storage, args.threads)
    except (ExprError, ValueError) as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 2
    print(json.dumps(res, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
