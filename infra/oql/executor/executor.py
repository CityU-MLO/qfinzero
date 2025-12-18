"""
OQLEngine orchestrates: parse -> fetch -> build strategy -> having -> order -> limit.
"""

from datetime import datetime
from typing import Dict, Any

import pandas as pd

from parsing.parser import OQLParser
from parsing.ast import QueryAST, Condition
from executor.data_client import OptionDataClient
from executor.filters import apply_having
from executor.sorter import sort_df

from strategy.vertical import (
    BullCallSpread,
    BearCallSpread,
    BullPutSpread,
    BearPutSpread,
)
from strategy.calendar import CalendarCall, CalendarPut
from strategy.straddle import Straddle
from strategy.butterfly import ButterflyCall
from strategy.iron_condor import IronCondor
from strategy.strangle import Strangle

STRATEGY_REGISTRY = {
            "BULL_CALL_SPREAD": BullCallSpread(),
            "BEAR_CALL_SPREAD": BearCallSpread(),
            "BULL_PUT_SPREAD": BullPutSpread(),
            "BEAR_PUT_SPREAD": BearPutSpread(),
            "CALENDAR_CALL": CalendarCall(),
            "CALENDAR_PUT": CalendarPut(),
            "STRADDLE": Straddle(),
            "STRANGLE": Strangle(),
            "IRON_CONDOR": IronCondor(),
            "BUTTERFLY_CALL": ButterflyCall(),
        }

class OQLEngine:
    def __init__(self, data_client: OptionDataClient):
        self.client = data_client or OptionDataClient()
        # Strategy registry: name -> instance
        self.registry = STRATEGY_REGISTRY

    def register_strategy(self, name: str, strategy_obj) -> None:
        self.registry[name.upper()] = strategy_obj

    def list_strategies(self) -> list[str]:
        return sorted(self.registry.keys())

    # ------------------------------------------------------------------
    # Hint builder: derive /query/chain parameters from AST + strategy
    # ------------------------------------------------------------------
    def _infer_opt_type_hint(self, strategy: str):
        """
        Return 'c', 'p', or None based on strategy name.

        None means: do not restrict option type (need both calls and puts).
        """
        s = strategy.upper()

        calls_only = {"BULL_CALL_SPREAD", "CALENDAR_CALL", "BUTTERFLY_CALL"}
        puts_only = {"BEAR_PUT_SPREAD", "CALENDAR_PUT"}

        if s in calls_only:
            return "c"
        if s in puts_only:
            return "p"
        # strategies that use both calls and puts (STRADDLE, STRANGLE, IRON_CONDOR)
        return None

    def _build_chain_hints(self, ast: QueryAST) -> Dict[str, Any]:
        """
        Build a dictionary of hint parameters for OptionDataClient.get_chain_data
        based on WHERE conditions.

        We try to:
          - shrink expiry_days from Dte conditions
          - set strike_gt / strike_lt from Strike conditions
          - set opt_type from strategy name
        """
        # Defaults
        hints: Dict[str, Any] = {
            "opt_type": self._infer_opt_type_hint(ast.strategy),
            "expiry_days": 365,
            "strike_gt": None,
            "strike_lt": None,
            "level": None,
            "require_greek": True,
        }

        max_dte = 365
        # Use a bit of slack for approximate ranges
        DTE_PADDING_APPROX = 20  # extra days for '~'
        DTE_PADDING_UPPER = 5    # extra days for strict '<='

        strike_min = None  # we want max of lower bounds
        strike_max = None  # we want min of upper bounds

        for cond in ast.where:
            field = cond.field.lower()
            op = cond.op
            val = cond.val

            # Dte hints
            if field == "dte":
                try:
                    v = float(val)
                except Exception:
                    continue

                if op in ("<", "<="):
                    # upper bound
                    candidate = v + DTE_PADDING_UPPER
                    max_dte = min(max_dte, candidate)
                elif op == "~":
                    # centered around v, we only care about an upper bound
                    candidate = v + DTE_PADDING_APPROX
                    max_dte = min(max_dte, candidate)
                # For >, >= we cannot express lower bound with this API, so ignore

            # Strike hints
            if field == "strike":
                try:
                    v = float(val)
                except Exception:
                    continue

                if op in (">", ">="):
                    # lower bound
                    candidate = v * 0.9  # a bit below requested bound
                    if strike_min is None:
                        strike_min = candidate
                    else:
                        strike_min = max(strike_min, candidate)
                elif op in ("<", "<="):
                    # upper bound
                    candidate = v * 1.1  # a bit above requested bound
                    if strike_max is None:
                        strike_max = candidate
                    else:
                        strike_max = min(strike_max, candidate)
                elif op == "~":
                    # approximate: ±20% around center strike
                    low = v * 0.8
                    high = v * 1.2
                    strike_min = low if strike_min is None else max(strike_min, low)
                    strike_max = high if strike_max is None else min(strike_max, high)

        hints["expiry_days"] = int(max_dte)

        if strike_min is not None:
            hints["strike_gt"] = strike_min
        if strike_max is not None:
            hints["strike_lt"] = strike_max

        return hints

    # ------------------------------------------------------------------
    # Main execution
    # ------------------------------------------------------------------
    def execute(self, query_str: str, as_of_date: str):
        as_of_date = as_of_date or datetime.now().strftime("%Y-%m-%d")

        try:
            ast: QueryAST = OQLParser().parse(query_str)
            print(
                f"\n🔍 Executing: {ast.strategy} on {ast.ticker} (Date: {as_of_date})"
            )
        except Exception as e:
            return f"Parser Error: {e}"

        if ast.strategy not in self.registry:
            return f"Strategy {ast.strategy} is not implemented."

        # Infer chain query hints from AST (WHERE) + strategy
        chain_hints = self._build_chain_hints(ast)

        # Fetch option chain snapshot (potentially filtered server-side)
        df_chain, spot = self.client.get_chain_data(
            ast.ticker,
            as_of_date,
            **chain_hints,
        )
        if df_chain.empty:
            return "No data returned from API."

        # Build combos via strategy
        builder = self.registry[ast.strategy]
        try:
            df_combo = builder.build(df_chain, ast)
        except Exception as e:
            return f"Strategy Execution Error: {e}"

        # HAVING filters
        df_combo = apply_having(df_combo, ast.having)

        # ORDER BY (multi-key)
        df_combo = sort_df(df_combo, ast.order)

        # LIMIT
        return df_combo.head(ast.limit)
