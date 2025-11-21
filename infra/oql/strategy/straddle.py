"""
Straddle strategy (same strike and expiry): long call + long put.
"""
import pandas as pd
from parsing.ast import QueryAST
from executor.filters import apply_where
from strategy.base import Strategy

class Straddle(Strategy):
    def build(self, df: pd.DataFrame, ast: QueryAST) -> pd.DataFrame:
        df_C = apply_where(df[df["type"] == "C"], "C", ast.where)
        df_P = apply_where(df[df["type"] == "P"], "P", ast.where)

        combo = pd.merge(df_C, df_P, on=["expiry_date", "strike"], suffixes=("_C", "_P"))
        if combo.empty:
            return combo

        combo["net_cost"] = combo["price_C"] + combo["price_P"]

        # Net greeks (both legs long)
        self.calc_net_greeks(combo, [("_C", +1), ("_P", +1)])
        return combo
