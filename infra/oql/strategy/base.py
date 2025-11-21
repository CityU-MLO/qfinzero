"""
Base classes and helpers for strategies.
- Strategy: abstract base with build()
- calc_net_greeks: utility to compute net_{greek} columns over legs
"""
from abc import ABC, abstractmethod
import pandas as pd

GREEKS = ["delta", "gamma", "theta", "vega", "iv", "rho"]  # include rho if present

class Strategy(ABC):
    @abstractmethod
    def build(self, df: pd.DataFrame, ast) -> pd.DataFrame:
        """Build a combo dataframe for the given strategy and parsed AST."""

    @staticmethod
    def calc_net_greeks(df: pd.DataFrame, legs: list[tuple[str, int]]) -> None:
        """
        Compute net greek columns in-place.

        Args:
            df: merged combo dataframe (with suffixed greek columns)
            legs: list of (suffix, sign), e.g. [("_L", +1), ("_S", -1)]
        """
        for g in GREEKS:
            total = None
            for suffix, sign in legs:
                col = f"{g}{suffix}"
                if col in df.columns:
                    term = df[col] * sign
                    total = term if total is None else (total + term)
            if total is not None:
                df[f"net_{g}"] = total
