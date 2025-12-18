import pandas as pd
from parsing.ast import QueryAST, Condition
from executor.filters import apply_where
from strategy.base import Strategy


class IronCondor(Strategy):
    """
    Iron Condor: short call spread + short put spread.

    OQL roles (as per spec):
      - SC : short call (inner, closer to spot)
      - LC : long call  (outer)
      - SP : short put  (inner, closer to spot)
      - LP : long put   (outer)

    Typical OQL:
        SELECT IRON_CONDOR
        FROM   QQQ
        WHERE  SC.Dte ~ 30 AND LC.Dte ~ 30
           AND SP.Dte ~ 30 AND LP.Dte ~ 30
        HAVING net_credit >= 50
           AND call_width BETWEEN 5 AND 20
           AND put_width  BETWEEN 5 AND 20
        ORDER BY rr_ratio DESC
    """

    # ------------ helper: extract width bounds from HAVING -----------------
    @staticmethod
    def _extract_width_bounds(ast: QueryAST, field_name: str):
        """
        Parse HAVING conditions to get (min_width, max_width) for a given field,
        e.g. 'put_width' or 'call_width'.

        Supports:
          - field BETWEEN v1 AND v2
          - field >= v, field > v
          - field <= v, field < v
          - field ~ v   (approx, we treat as [0.8v, 1.2v])
        """
        low = None
        high = None
        fname = field_name.lower()

        for c in ast.having:
            if c.field.lower() != fname:
                continue

            op = c.op.upper()

            if op == "BETWEEN":
                try:
                    v1 = float(c.val)
                    v2 = float(c.val2) if c.val2 is not None else None
                except Exception:
                    continue
                if v2 is None:
                    continue
                l = min(v1, v2)
                h = max(v1, v2)
                low = l if low is None else max(low, l)
                high = h if high is None else min(high, h)
                continue

            try:
                v = float(c.val)
            except Exception:
                continue

            if op in (">", ">="):
                low = v if low is None else max(low, v)
            elif op in ("<", "<="):
                high = v if high is None else min(high, v)
            elif op == "~":
                l = v * 0.8
                h = v * 1.2
                low = l if low is None else max(low, l)
                high = h if high is None else min(high, h)

        return low, high

    # ------------ helper: estimate spot & pruning window -------------------
    @staticmethod
    def _estimate_spot_and_window(df: pd.DataFrame,
                                  put_w_high,
                                  call_w_high):
        """
        Estimate underlying spot from strike * moneyness_ratio median,
        and decide a reasonable strike window around spot to keep legs.

        If width hints exist in HAVING, we scale the window from them,
        otherwise we fall back to a generic window.
        """
        spot_series = df.get("strike", pd.Series(dtype=float)) * df.get(
            "moneyness_ratio", pd.Series(dtype=float)
        )
        spot = spot_series.replace([pd.NA, float("inf"), float("-inf")]).median()

        if pd.isna(spot):
            return None, None  # cannot estimate, skip pruning

        # choose a max width hint if available
        widths = [w for w in (put_w_high, call_w_high) if w is not None]
        if widths:
            base = max(widths)
            # keep strikes roughly within ±4 * max_width around spot
            window = max(base * 4.0, base + 10.0)
        else:
            # fallback window if no width hint: generic "near ATM"
            window = spot * 0.3  # 30% up/down

        return float(spot), float(window)

    # ----------------------------------------------------------------------
    def build(self, df: pd.DataFrame, ast: QueryAST) -> pd.DataFrame:
        # Pre-extract width bounds from HAVING so we can prune early
        put_w_low, put_w_high = self._extract_width_bounds(ast, "put_width")
        call_w_low, call_w_high = self._extract_width_bounds(ast, "call_width")

        # Estimate spot + a strike window for pruning far OTM legs
        spot, strike_window = self._estimate_spot_and_window(df, put_w_high, call_w_high)

        # 1. Put side (Bull Put Spread): Long LP < Short SP
        sub_puts = df[df["type"] == "P"].copy()
        if spot is not None and strike_window is not None:
            # prune far OTM puts first (before WHERE)
            sub_puts = sub_puts[
                (sub_puts["strike"] >= spot - strike_window)
                & (sub_puts["strike"] <= spot + strike_window)
            ]

        # Cut-tree
        if "moneyness_ratio" in sub_puts.columns:
            ratio = sub_puts["moneyness_ratio"]
            sub_puts = sub_puts[(ratio > 0.5) & (ratio < 1.5)] 
    
        df_SP = apply_where(sub_puts, "SP", ast.where)  # short put (inner)
        df_LP = apply_where(sub_puts, "LP", ast.where)  # long put (outer)

        if df_SP.empty or df_LP.empty:
            return pd.DataFrame()

        puts = pd.merge(df_SP, df_LP, on="expiry_date", suffixes=("_SP", "_LP"))
        if puts.empty:
            return puts

        # Structural constraint: outer < inner (LP strike < SP strike)
        puts = puts[puts["strike_LP"] < puts["strike_SP"]]
        if puts.empty:
            return puts

        # Compute put_width here so we can prune with HAVING-like bounds
        puts["put_width"] = puts["strike_SP"] - puts["strike_LP"]

        if put_w_low is not None:
            puts = puts[puts["put_width"] >= put_w_low]
        if put_w_high is not None:
            puts = puts[puts["put_width"] <= put_w_high]
        if puts.empty:
            return puts

        # 2. Call side (Bear Call Spread): Short SC < Long LC
        sub_calls = df[df["type"] == "C"].copy()
        if spot is not None and strike_window is not None:
            # prune far OTM calls first
            sub_calls = sub_calls[
                (sub_calls["strike"] >= spot - strike_window)
                & (sub_calls["strike"] <= spot + strike_window)
            ]

        # Cut-tree
        if "moneyness_ratio" in sub_calls.columns:
            ratio = sub_calls["moneyness_ratio"]
            sub_calls = sub_calls[(ratio > 0.5) & (ratio < 1.5)] 
            
        df_SC = apply_where(sub_calls, "SC", ast.where)  # short call (inner)
        df_LC = apply_where(sub_calls, "LC", ast.where)  # long call (outer)

        if df_SC.empty or df_LC.empty:
            return pd.DataFrame()

        calls = pd.merge(df_SC, df_LC, on="expiry_date", suffixes=("_SC", "_LC"))
        if calls.empty:
            return calls

        # Structural constraint: inner < outer (SC strike < LC strike)
        calls = calls[calls["strike_SC"] < calls["strike_LC"]]
        if calls.empty:
            return calls

        # Compute call_width here so we can prune with HAVING-like bounds
        calls["call_width"] = calls["strike_LC"] - calls["strike_SC"]

        if call_w_low is not None:
            calls = calls[calls["call_width"] >= call_w_low]
        if call_w_high is not None:
            calls = calls[calls["call_width"] <= call_w_high]
        if calls.empty:
            return calls

        # 3. Join put side and call side on expiry (cross join within same expiry)
        combo = pd.merge(puts, calls, on="expiry_date")
        if combo.empty:
            return combo

        # 4. Core structural constraint: Put short strike < Call short strike
        combo = combo[combo["strike_SP"] < combo["strike_SC"]]
        if combo.empty:
            return combo

        # Widths for whole condor
        combo["spread_width"] = combo[["put_width", "call_width"]].max(axis=1)

        # Net credit:
        #   Receive from short legs (SP, SC), pay for long legs (LP, LC)
        combo["net_credit"] = (combo["price_SP"] + combo["price_SC"]) - (
            combo["price_LP"] + combo["price_LC"]
        )
        combo["net_cost"] = -combo["net_credit"]  # alias, negative for credit

        # Payoff (short both spreads):
        #   Max profit = net_credit
        #   Max loss   = spread_width - net_credit
        combo["max_profit"] = combo["net_credit"]
        combo["max_loss"] = combo["spread_width"] - combo["net_credit"]
        combo["rr_ratio"] = combo["max_profit"] / combo["max_loss"].replace(0, pd.NA)
        
        # Breakevens (two-point payoff shape)
        # Lower BE: SP strike - credit received
        # Upper BE: SC strike + credit received
        combo["breakeven_low"] = combo["strike_SP"] - combo["net_credit"]
        combo["breakeven_high"] = combo["strike_SC"] + combo["net_credit"]
        # Greeks:
        #   Short SP, Short SC, Long LP, Long LC
        self.calc_net_greeks(
            combo,
            [
                ("_SP", -1.0),
                ("_SC", -1.0),
                ("_LP", 1.0),
                ("_LC", 1.0),
            ],
        )

        return combo
