"""
OQLEngine orchestrates: parse -> fetch -> build strategy -> having -> order -> limit.
"""
from datetime import datetime
import pandas as pd

from parsing.parser import OQLParser
from parsing.ast import QueryAST
from executor.data_client import OptionDataClient
from executor.filters import apply_having
from executor.sorter import sort_df

from strategy.vertical import BullCallSpread, BearPutSpread
from strategy.calendar import CalendarCall, CalendarPut
from strategy.straddle import Straddle

class OQLEngine:
    def __init__(self, data_client: OptionDataClient):
        self.client = data_client or OptionDataClient()
        # Strategy registry: name -> instance
        self.registry = {
            "BULL_CALL_SPREAD": BullCallSpread(),
            "BEAR_PUT_SPREAD":  BearPutSpread(),
            "CALENDAR_CALL":    CalendarCall(),
            "CALENDAR_PUT":     CalendarPut(),
            "STRADDLE":         Straddle(),
        }

    def register_strategy(self, name: str, strategy_obj) -> None:
        self.registry[name.upper()] = strategy_obj

    def list_strategies(self) -> list[str]:
        return sorted(self.registry.keys())

    def execute(self, query_str: str, as_of_date: str):
        as_of_date = as_of_date or datetime.now().strftime("%Y-%m-%d")

        try:
            ast: QueryAST = OQLParser().parse(query_str)
            print(f"\n🔍 Executing: {ast.strategy} on {ast.ticker} (Date: {as_of_date})")
        except Exception as e:
            return f"Parser Error: {e}"

        df_chain, spot = self.client.get_chain_data(ast.ticker, as_of_date)
        if df_chain.empty:
            return "No data returned from API."

        if ast.strategy not in self.registry:
            return f"Strategy {ast.strategy} is not implemented."

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
