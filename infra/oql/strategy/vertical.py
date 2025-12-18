"""
Vertical spread strategies.

Supported strategies (via subclasses of _VerticalBase):

- BullCallSpread: long call at lower strike + short call at higher strike (same expiry)
- BearCallSpread: long call at higher strike + short call at lower strike (same expiry)
- BullPutSpread : long put  at lower strike + short put  at higher strike (same expiry)
- BearPutSpread : long put  at higher strike + short put  at lower  strike (same expiry)

Conventions:
- Role 'L' is always the long leg.
- Role 'S' is always the short leg.
- For bull verticals   (is_bull=True):  strike_L < strike_S
- For bear verticals   (is_bull=False): strike_L > strike_S

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
        """
        Parameters
        ----------
        opt_type : {'C', 'P'}
            Option type: call or put.
        is_bull : bool
            True  -> bull vertical (benefits from underlying moving up for calls,
                     or up for bull put credit spread).
            False -> bear vertical.
        """
        self.opt_type = opt_type  # 'C' or 'P'
        self.is_bull = is_bull

    def build(self, df: pd.DataFrame, ast: QueryAST) -> pd.DataFrame:
        # Filter by option type for this vertical
        sub = df[df["type"] == self.opt_type].copy()

        # Apply role-specific WHERE filters
        df_L = apply_where(sub, "L", ast.where)  # long leg
        df_S = apply_where(sub, "S", ast.where)  # short leg

        if df_L.empty or df_S.empty:
            return pd.DataFrame()

        # Join on expiry only (strikes differ)
        combo = pd.merge(df_L, df_S, on="expiry_date", suffixes=("_L", "_S"))
        if combo.empty:
            return combo

        # Structural constraints:
        # - Bull vertical (is_bull=True) : strike_L < strike_S
        # - Bear vertical (is_bull=False): strike_L > strike_S
        if self.is_bull:
            combo = combo[combo["strike_L"] < combo["strike_S"]]
        else:
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

        combo.loc[credit_mask, "max_profit"] = (
            -combo.loc[credit_mask, "net_cost"]
        ).clip(lower=0.0)
        combo.loc[credit_mask, "max_loss"] = (
            combo.loc[credit_mask, "spread_width"] + combo.loc[credit_mask, "net_cost"]
        ).clip(lower=0.0)

        combo["rr_ratio"] = combo["max_profit"] / combo["max_loss"].replace(0, pd.NA)
        # Breakeven (single point at expiry)
        combo["breakeven"] = pd.NA

        if self.opt_type == "C":
            # Calls
            combo.loc[debit_mask, "breakeven"] = combo.loc[debit_mask, "strike_L"] + combo.loc[debit_mask, "net_debit"]
            combo.loc[credit_mask, "breakeven"] = combo.loc[credit_mask, "strike_S"] + combo.loc[credit_mask, "net_credit"]
        else:
            # Puts
            combo.loc[debit_mask, "breakeven"] = combo.loc[debit_mask, "strike_L"] - combo.loc[debit_mask, "net_debit"]
            combo.loc[credit_mask, "breakeven"] = combo.loc[credit_mask, "strike_S"] - combo.loc[credit_mask, "net_credit"]

        # Net greeks (L:+1, S:-1)
        self.calc_net_greeks(combo, [("_L", +1.0), ("_S", -1.0)])
        return combo


class BullCallSpread(_VerticalBase):
    """
    Bull Call Spread:
    - Call vertical
    - Long lower strike call (L)
    - Short higher strike call (S)
    - Usually a debit spread (net_cost > 0)
    """
    def __init__(self):
        super().__init__(opt_type="C", is_bull=True)


class BearCallSpread(_VerticalBase):
    """
    Bear Call Spread:
    - Call vertical
    - Long higher strike call (L)
    - Short lower strike call (S)
    - Usually a credit spread (net_cost < 0)
    """
    def __init__(self):
        super().__init__(opt_type="C", is_bull=False)


class BullPutSpread(_VerticalBase):
    """
    Bull Put Spread:
    - Put vertical
    - Long lower strike put (L)
    - Short higher strike put (S)
    - Usually a credit spread (net_cost < 0)
    """
    def __init__(self):
        super().__init__(opt_type="P", is_bull=True)


class BearPutSpread(_VerticalBase):
    """
    Bear Put Spread:
    - Put vertical
    - Long higher strike put (L)
    - Short lower strike put (S)
    - Usually a debit spread (net_cost > 0)
    """
    def __init__(self):
        super().__init__(opt_type="P", is_bull=False)
