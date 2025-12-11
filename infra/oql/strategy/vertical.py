"""
Vertical spread strategies.
- BullCallSpread: long call at lower strike + short call at higher strike (same expiry)
- BearPutSpread : long put  at higher strike + short put  at lower  strike (same expiry)

Strategy-level fields exposed:
- spread_width : |strike_L - strike_S|
- net_cost     : price_L - price_S (debit > 0, credit < 0)
- net_debit    : max(net_cost, 0)
- net_credit   : max(-net_cost, 0)
- max_profit / max_loss / rr_ratio (handle both debit and credit cases)
- net_* greeks (via calc_net_greeks)
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
        df_L = apply_where(sub, "L", ast.where)  # long leg
        df_S = apply_where(sub, "S", ast.where)  # short leg

        if df_L.empty or df_S.empty:
            return pd.DataFrame()

        combo = pd.merge(df_L, df_S, on="expiry_date", suffixes=("_L", "_S"))
        if combo.empty:
            return combo

        # Structural constraints:
        # - Bull Call: strike_L < strike_S
        # - Bear Put : strike_L > strike_S
        if self.opt_type == "C" and self.is_bull:
            combo = combo[combo["strike_L"] < combo["strike_S"]]
        elif self.opt_type == "P" and not self.is_bull:
            combo = combo[combo["strike_L"] > combo["strike_S"]]

        if combo.empty:
            return combo

        # Spread width
        combo["spread_width"] = (combo["strike_L"] - combo["strike_S"]).abs()

        # Net cost: pay for long, receive from short
        combo["net_cost"] = combo["price_L"] - combo["price_S"]
        combo["net_debit"] = combo["net_cost"].clip(lower=0.0)
        combo["net_credit"] = (-combo["net_cost"]).clip(lower=0.0)

        # Payoff:
        # - If net_cost >= 0: debit vertical (long vertical)
        #   max_profit = spread_width - net_cost
        #   max_loss   = net_cost
        # - If net_cost < 0: credit vertical (short vertical)
        #   max_profit = -net_cost
        #   max_loss   = spread_width + net_cost  (width - credit)
        debit_mask = combo["net_cost"] >= 0
        credit_mask = ~debit_mask

        combo.loc[debit_mask, "max_loss"] = combo.loc[debit_mask, "net_cost"]
        combo.loc[debit_mask, "max_profit"] = (
            combo.loc[debit_mask, "spread_width"] - combo.loc[debit_mask, "net_cost"]
        ).clip(lower=0.0)

        combo.loc[credit_mask, "max_profit"] = (-combo.loc[credit_mask, "net_cost"]).clip(
            lower=0.0
        )
        combo.loc[credit_mask, "max_loss"] = (
            combo.loc[credit_mask, "spread_width"] + combo.loc[credit_mask, "net_cost"]
        ).clip(lower=0.0)

        combo["rr_ratio"] = combo["max_profit"] / combo["max_loss"].replace(0, pd.NA)

        # Net greeks (L:+1, S:-1)
        self.calc_net_greeks(combo, [("_L", +1.0), ("_S", -1.0)])
        return combo


class BullCallSpread(_VerticalBase):
    def __init__(self):
        super().__init__(opt_type="C", is_bull=True)


class BearPutSpread(_VerticalBase):
    def __init__(self):
        super().__init__(opt_type="P", is_bull=False)
