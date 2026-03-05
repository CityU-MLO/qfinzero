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
    return f"{year:04d}-{mm}-{dd}"
