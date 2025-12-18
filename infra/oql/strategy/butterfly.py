import pandas as pd
from parsing.ast import QueryAST
from executor.filters import apply_where
from strategy.base import Strategy


class ButterflyCall(Strategy):
    """
    Call butterfly: long call (lower strike), short 2x call (body), long call (upper strike).

    OQL roles (as per spec):
      - L1 : lower-strike long call
      - S  : body short call (usually 2x)
      - L2 : higher-strike long call

    Typical OQL:
        SELECT BUTTERFLY_CALL
        FROM   META
        WHERE  L1.Dte ~ 30 AND L2.Dte ~ 30 AND S.Dte ~ 30
           AND S.Moneyness = ATM
        HAVING net_debit <= 200
           AND rr_ratio >= 1.5
        ORDER BY max_profit DESC
    """

    def build(self, df: pd.DataFrame, ast: QueryAST) -> pd.DataFrame:
        # Only calls are used for ButterflyCall
        sub_calls = df[df["type"] == "C"]

        # Role-aware WHERE filters
        df_L1 = apply_where(sub_calls, "L1", ast.where)  # lower-strike long call
        df_S = apply_where(sub_calls, "S", ast.where)    # body short call
        df_L2 = apply_where(sub_calls, "L2", ast.where)  # upper-strike long call

        if df_L1.empty or df_S.empty or df_L2.empty:
            return pd.DataFrame()

        # Rename L2 columns to avoid collisions in the second merge
        df_L2_renamed = df_L2.add_suffix("_L2")
        df_L2_renamed = df_L2_renamed.rename(columns={"expiry_date_L2": "expiry_date"})

        # First join L1 and S on expiry_date
        combo = pd.merge(df_L1, df_S, on="expiry_date", suffixes=("_L1", "_S"))

        # Then join L2 (already suffixed) on expiry_date
        combo = pd.merge(combo, df_L2_renamed, on="expiry_date")

        # Now we expect:
        #   strike_L1, strike_S, strike_L2
        #   price_L1, price_S, price_L2
        # plus greeks with the same suffix pattern.

        # Structural constraint: Strike_L1 < Strike_S < Strike_L2
        combo = combo[
            (combo["strike_L1"] < combo["strike_S"]) &
            (combo["strike_S"] < combo["strike_L2"])
        ]

        if combo.empty:
            return combo

        # Symmetry constraint: (Strike_S - Strike_L1) ~= (Strike_L2 - Strike_S)
        combo["wing_width_1"] = combo["strike_S"] - combo["strike_L1"]
        combo["wing_width_2"] = combo["strike_L2"] - combo["strike_S"]
        combo = combo[(combo["wing_width_1"] - combo["wing_width_2"]).abs() <= 0.01]

        if combo.empty:
            return combo

        # Use one width as spread_width (for HAVING / ORDER BY)
        combo["spread_width"] = combo["wing_width_1"]

        # Net debit: pay for L1 + L2, receive from selling 2x S
        combo["net_debit"] = combo["price_L1"] + combo["price_L2"] - 2.0 * combo["price_S"]
        combo["net_cost"] = combo["net_debit"]  # alias for consistency

        # Payoff profile (standard debit butterfly):
        #   Max profit  = spread_width - net_debit
        #   Max loss    = net_debit
        combo["max_profit"] = (combo["spread_width"] - combo["net_debit"]).clip(lower=0.0)
        combo["max_loss"] = combo["net_debit"].clip(lower=0.0)

        # Reward-to-risk ratio: max_profit / max_loss
        combo["rr_ratio"] = combo["max_profit"] / combo["max_loss"].replace(0, pd.NA)
        # Breakevens (two-point payoff "tent")
        combo["breakeven_low"] = combo["strike_L1"] + combo["net_debit"]
        combo["breakeven_high"] = combo["strike_L2"] - combo["net_debit"]
        
        # Greeks:
        #   +1 * L1,  -2 * S,  +1 * L2
        self.calc_net_greeks(
            combo,
            [
                ("_L1", 1.0),
                ("_S", -2.0),
                ("_L2", 1.0),
            ],
        )

        return combo
