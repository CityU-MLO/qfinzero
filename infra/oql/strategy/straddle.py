"""
Straddle strategy (same strike and expiry): long call + long put.

Strategy-level fields:
- net_cost  : total debit
- net_debit : same as net_cost (if positive)
- max_loss  : net_debit
- net_* greeks
"""

import pandas as pd
from parsing.ast import QueryAST
from executor.filters import apply_where
from strategy.base import Strategy


class Straddle(Strategy):
    def build(self, df: pd.DataFrame, ast: QueryAST) -> pd.DataFrame:
        df_C = apply_where(df[df["type"] == "C"], "C", ast.where)
        df_P = apply_where(df[df["type"] == "P"], "P", ast.where)

        if df_C.empty or df_P.empty:
            return pd.DataFrame()

        combo = pd.merge(
            df_C, df_P, on=["expiry_date", "strike"], suffixes=("_C", "_P")
        )
        if combo.empty:
            return combo

        # Net debit: pay for both legs
        combo["net_cost"] = combo["price_C"] + combo["price_P"]
        combo["net_debit"] = combo["net_cost"].clip(lower=0.0)
        combo["net_credit"] = 0.0

        # For a long straddle, worst-case loss is the net debit
        combo["max_loss"] = combo["net_debit"]
        # Theoretical max profit is unbounded -> keep as NaN
        combo["max_profit"] = pd.NA
        combo["rr_ratio"] = pd.NA
        # Breakevens (two-point payoff)
        combo["breakeven_low"] = combo["strike"] - combo["net_debit"]
        combo["breakeven_high"] = combo["strike"] + combo["net_debit"]
        # Net greeks (both legs long)
        self.calc_net_greeks(combo, [("_C", +1.0), ("_P", +1.0)])
        return combo
