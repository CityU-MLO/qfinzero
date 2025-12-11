"""
Calendar spread strategies (same strike, different expiry).
- CalendarCall: long back-month call, short front-month call
- CalendarPut : long back-month put,  short front-month put

Strategy-level fields:
- net_cost   : price_B - price_F (debit > 0, credit < 0)
- net_debit  : max(net_cost, 0)
- net_credit : max(-net_cost, 0)
- time_gap   : dte_B - dte_F
- net_* greeks (Back +1, Front -1)

We do not try to estimate exact max_profit / max_loss because calendar
payoff depends on path and term structure; leave them as NaN for now.
"""

import pandas as pd
from parsing.ast import QueryAST
from executor.filters import apply_where
from strategy.base import Strategy


class _CalendarBase(Strategy):
    def __init__(self, opt_type: str):
        self.opt_type = opt_type  # 'C' or 'P'

    def build(self, df: pd.DataFrame, ast: QueryAST) -> pd.DataFrame:
        sub = df[df["type"] == self.opt_type].copy()
        df_F = apply_where(sub, "F", ast.where)  # Front - short
        df_B = apply_where(sub, "B", ast.where)  # Back  - long

        if df_F.empty or df_B.empty:
            return pd.DataFrame()

        combo = pd.merge(df_F, df_B, on="strike", suffixes=("_F", "_B"))
        if combo.empty:
            return combo

        # Constraint: back-month DTE > front-month DTE
        if "dte_B" in combo.columns and "dte_F" in combo.columns:
            combo = combo[combo["dte_B"] > combo["dte_F"]]
        if combo.empty:
            return combo

        # Net cost: long back, short front
        combo["net_cost"] = combo["price_B"] - combo["price_F"]
        combo["net_debit"] = combo["net_cost"].clip(lower=0.0)
        combo["net_credit"] = (-combo["net_cost"]).clip(lower=0.0)

        # Time gap between expiries
        if "dte_B" in combo.columns and "dte_F" in combo.columns:
            combo["time_gap"] = combo["dte_B"] - combo["dte_F"]
        else:
            combo["time_gap"] = pd.NA

        # Max profit / loss are non-trivial for calendars; keep NaN
        combo["max_profit"] = pd.NA
        combo["max_loss"] = pd.NA
        combo["rr_ratio"] = pd.NA

        # Net greeks (Back +1, Front -1)
        self.calc_net_greeks(combo, [("_B", +1.0), ("_F", -1.0)])
        return combo


class CalendarCall(_CalendarBase):
    def __init__(self):
        super().__init__(opt_type="C")


class CalendarPut(_CalendarBase):
    def __init__(self):
        super().__init__(opt_type="P")
