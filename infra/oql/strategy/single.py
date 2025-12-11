import pandas as pd
from parsing.ast import QueryAST
from executor.filters import apply_where
from strategy.base import Strategy


class SingleOption(Strategy):
    """
    Generic single-leg option strategy.

    opt_type : 'C' or 'P'
    position : 'long' or 'short'

    We expose:
    - net_cost   : price * sign (long > 0, short < 0)
    - net_debit  : max(net_cost, 0)
    - net_credit : max(-net_cost, 0)
    - max_loss   : for long positions, approx = net_debit; for short, left as NaN (theoretically unbounded)
    - net_* greeks via calc_net_greeks with suffix '_O'
    """

    def __init__(self, opt_type: str, position: str):
        self.opt_type = opt_type  # 'C' or 'P'
        self.sign = 1.0 if position.lower() == "long" else -1.0  # +1 long, -1 short

    def build(self, df: pd.DataFrame, ast: QueryAST) -> pd.DataFrame:
        sub = df[df["type"] == self.opt_type].copy()

        # Single-leg role: 'O'
        combo = apply_where(sub, "O", ast.where)
        if combo.empty:
            return combo

        # Cost fields
        combo["net_cost"] = combo["price"] * self.sign
        combo["net_debit"] = combo["net_cost"].clip(lower=0.0)
        combo["net_credit"] = (-combo["net_cost"]).clip(lower=0.0)

        # Approximate max loss:
        # - For long options: max loss ~= net_debit
        # - For short options: theoretically unbounded -> NaN
        if self.sign > 0:
            combo["max_loss"] = combo["net_debit"]
        else:
            combo["max_loss"] = pd.NA

        combo["max_profit"] = pd.NA
        combo["rr_ratio"] = pd.NA

        # Prepare suffixed greek columns for calc_net_greeks
        for greek in ["delta", "gamma", "theta", "vega", "rho"]:
            if greek in combo.columns:
                combo[f"{greek}_O"] = combo[greek]

        # Net greeks (weight = sign)
        self.calc_net_greeks(combo, [("_O", self.sign)])
        return combo


# Concrete single-leg strategies
class LongCall(SingleOption):
    def __init__(self):
        super().__init__("C", "long")


class ShortPut(SingleOption):  # used for Cash-Secured Put
    def __init__(self):
        super().__init__("P", "short")
