import datetime
import re
from dataclasses import dataclass
from typing import Optional

from models.enums import Side
from models.position import Position


_OPRA_RE = re.compile(
    r"^O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$"
)


def parse_opra_expiry(contract: str) -> Optional[str]:
    """Parse expiry date from OPRA contract string.

    Returns "YYYY-MM-DD" or None if contract is not a valid OPRA string.
    Example: "O:NVDA250117C00136000" -> "2025-01-17"
    """
    m = _OPRA_RE.match(contract)
    if not m:
        return None
    yy, mm, dd = m.group(2), m.group(3), m.group(4)
    year = 2000 + int(yy)
    try:
        datetime.date(year, int(mm), int(dd))
    except ValueError:
        return None
    return f"{year:04d}-{mm}-{dd}"


@dataclass
class ExpiryAction:
    contract: str
    instrument_id: str
    option_pos: Position
    is_itm: bool
    intrinsic_value: float
    underlying: Optional[str]
    stock_side: Optional[Side]
    strike: Optional[float]
    stock_qty: int


def _parse_opra_parts(contract: str) -> Optional[tuple[str, str, float]]:
    """Return (underlying, right, strike_float) or None."""
    m = _OPRA_RE.match(contract)
    if not m:
        return None
    underlying = m.group(1)
    right = m.group(5)
    strike = int(m.group(6)) / 1000.0
    return underlying, right, strike


def check_option_expiries(
    positions: dict,
    current_date: str,
    underlying_prices: dict,
) -> list:
    """Return one ExpiryAction per option position whose expiry == current_date.

    Args:
        positions: dict of instrument_id -> Position from the ledger
        current_date: "YYYY-MM-DD" string for today
        underlying_prices: symbol -> spot price (from stock bars)
    """
    actions = []
    for iid, pos in positions.items():
        if not iid.startswith("OPTION:"):
            continue
        contract = iid[len("OPTION:"):]
        expiry = parse_opra_expiry(contract)
        if expiry != current_date:
            continue

        parts = _parse_opra_parts(contract)
        if parts is None:
            continue

        underlying, right, strike = parts
        spot = underlying_prices.get(underlying)

        if spot is None:
            # Cannot determine moneyness — treat as OTM, skip assignment
            actions.append(ExpiryAction(
                contract=contract,
                instrument_id=iid,
                option_pos=pos,
                is_itm=False,
                intrinsic_value=0.0,
                underlying=underlying,
                stock_side=None,
                strike=strike,
                stock_qty=abs(pos.qty) * 100,
            ))
            continue

        if right == "C":
            intrinsic = max(0.0, spot - strike)
        else:
            intrinsic = max(0.0, strike - spot)

        is_itm = intrinsic > 0.0

        # Stock transaction only for short positions
        stock_side = None
        if is_itm and pos.qty < 0:
            stock_side = Side.SELL if right == "C" else Side.BUY

        actions.append(ExpiryAction(
            contract=contract,
            instrument_id=iid,
            option_pos=pos,
            is_itm=is_itm,
            intrinsic_value=intrinsic,
            underlying=underlying,
            stock_side=stock_side,
            strike=strike,
            stock_qty=abs(pos.qty) * 100,
        ))

    return actions


def get_expiring_contracts(current_date: str, contracts: list[str]) -> set[str]:
    """Return the set of OPRA contract ids (without 'OPTION:' prefix) expiring on current_date."""
    expiring = set()
    for contract in contracts:
        if parse_opra_expiry(contract) == current_date:
            expiring.add(contract)
    return expiring
