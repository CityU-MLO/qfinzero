"""Futures: contract specifications, exchange-style margin and CME sessions.

A futures position is not paid for. Opening one posts *initial margin* (a
per-contract deposit the account must have free); the position then settles
daily: at the end of each session the change from the previous settlement
price, ``qty * (settle - basis) * multiplier``, is paid into or out of cash
(*variation margin*) and the basis moves to the settle. Between settlements the
open trade equity ``qty * (mark - basis) * multiplier`` counts toward equity.

When equity falls below the *maintenance margin* of the open futures the
account is in a margin call: new positions are refused, and the call is met
only when equity is back at the *initial* margin (as at CME). A call that is
still open after ``future_margin_call_sessions`` settlements is liquidated at
the settlement price.

Margin per contract is either a fixed amount (``maintenance_margin``, in USD,
as the exchange publishes it) or ``margin_rate`` of the notional at the last
settlement (``settle * multiplier``); initial margin is ``initial_ratio`` times
maintenance (CME: 110% for speculators). The built-in rates are rough
approximations of exchange levels, meant for simulation: set the real
requirements per root in the account's ``margin_config.future_specs``.

Sessions follow CME Globex: 18:00 ET the evening before to 17:00 ET, with the
trade date of the session's end. Daily bars from UPQ carry ``settle``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel

ET = ZoneInfo("America/New_York")
SESSION_SHIFT_NS = 6 * 3_600 * 1_000_000_000      # 18:00 ET + 6 h = next date 00:00

# Root of a contract symbol: ``ZNZ6`` / ``ESZ26`` -> ``ZN`` / ``ES``; ``ZN`` and
# ``ZN.v.1`` -> ``ZN`` (same rule as the Databento adapter).
_ROOT_RE = re.compile(r"^([A-Z0-9]+?)([FGHJKMNQUVXZ][0-9]{1,2})?$")


def root_of(symbol: str) -> str:
    base = symbol.strip().upper().split(".", 1)[0]
    m = _ROOT_RE.match(base)
    return m.group(1) if m else base


def session_date_of(ts_ns: int) -> str:
    """CME session (trade) date of a timestamp: bars from 18:00 ET belong to the next date."""
    t = datetime.fromtimestamp((ts_ns + SESSION_SHIFT_NS) / 1e9, tz=timezone.utc).astimezone(ET)
    return t.date().isoformat()


class FutureSpec(BaseModel):
    root: str
    name: str = ""
    multiplier: float = 1.0               # USD per 1.0 of price
    tick_size: float = 0.01
    margin_rate: float = 0.08             # maintenance / notional, when no fixed amount
    maintenance_margin: Optional[float] = None   # USD per contract (overrides margin_rate)
    initial_ratio: float = 1.10           # initial = maintenance * ratio
    fee_per_contract: Optional[float] = None     # overrides the session fee model

    def maintenance_per_contract(self, ref_price: float) -> float:
        if self.maintenance_margin is not None:
            return float(self.maintenance_margin)
        return abs(ref_price) * self.multiplier * self.margin_rate

    def initial_per_contract(self, ref_price: float) -> float:
        return self.maintenance_per_contract(ref_price) * self.initial_ratio

    def round_to_tick(self, price: float) -> float:
        if self.tick_size <= 0:
            return price
        return round(round(price / self.tick_size) * self.tick_size, 10)


def _s(root, name, mult, tick, rate):
    return FutureSpec(root=root, name=name, multiplier=mult, tick_size=tick, margin_rate=rate)


# Common US-listed contracts. Prices in the units UPQ stores (index points,
# USD per barrel / ounce, Treasury points, cents per bushel for grains).
DEFAULT_SPECS: dict[str, FutureSpec] = {s.root: s for s in (
    _s("ES", "E-mini S&P 500", 50, 0.25, 0.07),
    _s("MES", "Micro E-mini S&P 500", 5, 0.25, 0.07),
    _s("NQ", "E-mini Nasdaq-100", 20, 0.25, 0.08),
    _s("MNQ", "Micro E-mini Nasdaq-100", 2, 0.25, 0.08),
    _s("YM", "E-mini Dow", 5, 1.0, 0.06),
    _s("MYM", "Micro E-mini Dow", 0.5, 1.0, 0.06),
    _s("RTY", "E-mini Russell 2000", 50, 0.1, 0.07),
    _s("M2K", "Micro E-mini Russell 2000", 5, 0.1, 0.07),
    _s("CL", "Crude Oil (WTI)", 1000, 0.01, 0.08),
    _s("MCL", "Micro WTI Crude Oil", 100, 0.01, 0.08),
    _s("NG", "Henry Hub Natural Gas", 10000, 0.001, 0.12),
    _s("RB", "RBOB Gasoline", 42000, 0.0001, 0.08),
    _s("HO", "NY Harbor ULSD", 42000, 0.0001, 0.08),
    _s("GC", "Gold", 100, 0.1, 0.07),
    _s("MGC", "Micro Gold", 10, 0.1, 0.07),
    _s("SI", "Silver", 5000, 0.005, 0.09),
    _s("HG", "Copper", 25000, 0.0005, 0.07),
    _s("PL", "Platinum", 50, 0.1, 0.08),
    _s("ZT", "2-Year T-Note", 2000, 0.00390625, 0.006),
    _s("ZF", "5-Year T-Note", 1000, 0.0078125, 0.012),
    _s("ZN", "10-Year T-Note", 1000, 0.015625, 0.02),
    _s("TN", "Ultra 10-Year T-Note", 1000, 0.015625, 0.025),
    _s("ZB", "U.S. Treasury Bond", 1000, 0.03125, 0.035),
    _s("UB", "Ultra U.S. Treasury Bond", 1000, 0.03125, 0.05),
    _s("6E", "Euro FX", 125000, 0.00005, 0.03),
    _s("6J", "Japanese Yen", 12500000, 0.0000005, 0.035),
    _s("6B", "British Pound", 62500, 0.0001, 0.03),
    _s("6A", "Australian Dollar", 100000, 0.00005, 0.035),
    _s("6C", "Canadian Dollar", 100000, 0.00005, 0.025),
    # grains: price in cents per bushel, 5,000 bushels -> $50 per cent
    _s("ZC", "Corn", 50, 0.25, 0.06),
    _s("ZS", "Soybeans", 50, 0.25, 0.05),
    _s("ZW", "Chicago SRW Wheat", 50, 0.25, 0.07),
)}


def resolve_spec(symbol: str, overrides: dict[str, FutureSpec] | None = None) -> FutureSpec | None:
    """The spec of a contract or root: an account override, else a built-in one."""
    root = root_of(symbol)
    if overrides and root in overrides:
        spec = overrides[root]
        return spec if spec.root else spec.model_copy(update={"root": root})
    return DEFAULT_SPECS.get(root)
