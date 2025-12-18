import pandas as pd
from parsing.ast import QueryAST
from executor.filters import apply_where
from strategy.base import Strategy


class Strangle(Strategy):
    """
    Long Strangle: long OTM call + long OTM put.

    OQL roles (as per spec):
      - C : call leg
      - P : put leg

    Typical OQL:
        SELECT STRANGLE
        FROM   SPY
        WHERE  C.Moneyness = OTM
           AND P.Moneyness = OTM
           AND C.Dte ~ 45
        HAVING net_delta BETWEEN -0.1 AND 0.1
    """

    def build(self, df: pd.DataFrame, ast: QueryAST) -> pd.DataFrame:
        # Role-aware WHERE filters
        df_C = apply_where(df[df["type"] == "C"], "C", ast.where)
        df_P = apply_where(df[df["type"] == "P"], "P", ast.where)

        if df_C.empty or df_P.empty:
            return pd.DataFrame()

        # Merge on expiry only (strikes differ)
        combo = pd.merge(df_C, df_P, on=["expiry_date"], suffixes=("_C", "_P"))

        if combo.empty:
            return combo

        # Structural constraint: Call strike > Put strike (OTM strangle)
        combo = combo[combo["strike_C"] > combo["strike_P"]]
        if combo.empty:
            return combo

        # Net debit: pay for call + put
        combo["net_debit"] = combo["price_C"] + combo["price_P"]
        combo["net_cost"] = combo["net_debit"]

        # For a long strangle, max loss (ignoring early exercise) is the net debit
        combo["max_loss"] = combo["net_debit"]
        # Max profit is theoretically unbounded, so we do not set max_profit / rr_ratio here
        # Breakevens (two-point payoff)
        combo["breakeven_low"] = combo["strike_P"] - combo["net_debit"]
        combo["breakeven_high"] = combo["strike_C"] + combo["net_debit"]

        # Greeks: both legs are long
        self.calc_net_greeks(combo, [("_C", 1.0), ("_P", 1.0)])

        return combo
