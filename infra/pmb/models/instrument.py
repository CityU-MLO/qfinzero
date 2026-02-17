from pydantic import BaseModel
from typing import Optional

from .enums import InstrumentType


class Instrument(BaseModel):
    type: InstrumentType
    symbol: Optional[str] = None
    contract: Optional[str] = None

    def instrument_id(self) -> str:
        if self.type == InstrumentType.STOCK:
            return f"STOCK:{self.symbol}"
        return f"OPTION:{self.contract}"


def make_opra(underlying: str, expiry: str, right: str, strike: float) -> str:
    """Build OPRA contract ID.

    Args:
        underlying: e.g. "NVDA"
        expiry: "YYYY-MM-DD" e.g. "2025-01-17"
        right: "C" or "P"
        strike: e.g. 136.0
    """
    yy, mm, dd = expiry[2:4], expiry[5:7], expiry[8:10]
    strike_int = int(round(strike * 1000))
    return f"O:{underlying}{yy}{mm}{dd}{right}{strike_int:08d}"
