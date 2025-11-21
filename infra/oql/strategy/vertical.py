"""
Vertical spread strategies.
- BullCallSpread: long call at lower strike + short call at higher strike (same expiry)
- BearPutSpread : long put  at higher strike + short put  at lower  strike (same expiry)
"""
import pandas as pd
from parsing.ast import QueryAST
from executor.filters import apply_where
from strategy.base import Strategy

class _VerticalBase(Strategy):
    def __init__(self, opt_type: str, is_bull: bool):
        self.opt_type = opt_type  # 'C' or 'P'
        self.is_bull = is_bull

    def build(self, df: pd.DataFrame, ast: QueryAST) -> pd.DataFrame:
        sub = df[df["type"] == self.opt_type].copy()
        df_L = apply_where(sub, "L", ast.where)
        df_S = apply_where(sub, "S", ast.where)

        combo = pd.merge(df_L, df_S, on="expiry_date", suffixes=("_L", "_S"))
        if combo.empty:
            return combo

        # Structure constraints
        if self.opt_type == "C" and self.is_bull:
            combo = combo[combo["strike_L"] < combo["strike_S"]]
        elif self.opt_type == "P" and not self.is_bull:
            combo = combo[combo["strike_L"] > combo["strike_S"]]
        else:
            # Allow other combinations; no extra constraint
            pass

        # Derived metrics
        combo["net_cost"] = combo["price_L"] - combo["price_S"]
        combo["width"] = (combo["strike_L"] - combo["strike_S"]).abs()

        # Net greeks (L:+1, S:-1)
        self.calc_net_greeks(combo, [("_L", +1), ("_S", -1)])
        return combo

class BullCallSpread(_VerticalBase):
    def __init__(self):
        super().__init__(opt_type="C", is_bull=True)

class BearPutSpread(_VerticalBase):
    def __init__(self):
        super().__init__(opt_type="P", is_bull=False)
