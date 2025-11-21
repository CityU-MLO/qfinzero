"""
Calendar spread strategies (same strike, different expiry).
- CalendarCall: long back-month call, short front-month call
- CalendarPut : long back-month put,  short front-month put
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

        combo = pd.merge(df_F, df_B, on="strike", suffixes=("_F", "_B"))
        if combo.empty:
            return combo

        # Constraint: back-month DTE > front-month DTE
        if "dte_B" in combo.columns and "dte_F" in combo.columns:
            combo = combo[combo["dte_B"] > combo["dte_F"]]

        combo["net_cost"] = combo["price_B"] - combo["price_F"]
        combo["time_gap"] = combo["dte_B"] - combo["dte_F"]

        # Net greeks (Back +1, Front -1)
        self.calc_net_greeks(combo, [("_B", +1), ("_F", -1)])
        return combo

class CalendarCall(_CalendarBase):
    def __init__(self):
        super().__init__(opt_type="C")

class CalendarPut(_CalendarBase):
    def __init__(self):
        super().__init__(opt_type="P")
