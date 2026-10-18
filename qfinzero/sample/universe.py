"""The synthetic market: a fixed, fictional universe and calendar.

Everything here is invented. Tickers do not exist on any exchange, so a
language model cannot answer benchmark questions from memory, and the data can
be redistributed freely. The calendar is the real NYSE calendar for Q1 2025
(weekends and exchange holidays removed) so times, sessions and DST behave like
production data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

SAMPLE_VERSION = "1.0"
SEED = 20250102

START = date(2025, 1, 2)
END = date(2025, 3, 31)
# NYSE closures in the window (New Year's Day, the national day of mourning
# on 2025-01-09, MLK day, Presidents' day).
HOLIDAYS = {date(2025, 1, 1), date(2025, 1, 9), date(2025, 1, 20), date(2025, 2, 17)}
# Minute bars (and quotes) exist for the last MINUTE_DAYS trading days.
MINUTE_DAYS = 10
# Names that also trade on the overnight venue (20:00-04:00 ET) in that window.
OVERNIGHT_TICKERS = ("ACME", "NOVA", "QZSP")


@dataclass(frozen=True)
class Stock:
    ticker: str
    name: str
    sector: str
    price: float          # first close
    vol: float            # annualised idiosyncratic volatility
    beta: float
    adv: int              # average daily volume, shares
    dividend: float = 0.0           # quarterly cash dividend per share
    split: tuple[str, float] | None = None   # (ex-date, ratio)
    options: bool = False


@dataclass(frozen=True)
class EarningsEvent:
    ticker: str
    day: date
    timing: str           # "BMO" (before open) or "AMC" (after close)
    eps_estimate: float
    eps_actual: float
    revenue_estimate: float
    revenue_actual: float
    jump: float           # price reaction on the reaction session (log return)

    @property
    def surprise(self) -> float:
        return self.eps_actual - self.eps_estimate


@dataclass(frozen=True)
class MacroEvent:
    event: str
    day: date
    time_et: str          # HH:MM
    importance: str       # low / medium / high
    actual: float | None
    consensus: float | None
    previous: float | None
    unit: str
    jump: float = 0.0     # market reaction (log return) at release


STOCKS: tuple[Stock, ...] = (
    Stock("QZSP", "QFinZero Synthetic 500 ETF", "Index", 520.0, 0.0, 1.0, 60_000_000, 1.65, options=True),
    Stock("ACME", "Acme Robotics", "Technology", 182.0, 0.32, 1.25, 28_000_000, options=True),
    # NOVA splits 2:1; it has no listed options (no contract adjustments needed)
    Stock("NOVA", "Nova Semiconductor", "Technology", 96.0, 0.45, 1.6, 41_000_000,
          split=("2025-03-03", 2.0)),
    Stock("BOLT", "Bolt Electric Vehicles", "Consumer", 41.0, 0.55, 1.8, 35_000_000, options=True),
    Stock("CRUX", "Crux Cloud Systems", "Technology", 248.0, 0.30, 1.15, 9_000_000),
    Stock("DYNE", "Dyne Biotherapeutics", "Healthcare", 63.0, 0.50, 0.9, 6_500_000),
    Stock("EMBR", "Ember Energy", "Energy", 78.0, 0.28, 0.8, 12_000_000, 0.92),
    Stock("FERN", "Fern Foods", "Staples", 54.0, 0.18, 0.55, 5_000_000, 0.48),
    Stock("GALE", "Gale Airlines", "Industrials", 33.0, 0.40, 1.3, 14_000_000),
    Stock("HALO", "Halo Health Insurance", "Healthcare", 410.0, 0.22, 0.7, 3_100_000, 2.10),
    Stock("IRIS", "Iris Optical", "Technology", 121.0, 0.35, 1.2, 4_200_000),
    Stock("JADE", "Jade Retail Group", "Consumer", 72.0, 0.30, 1.0, 7_800_000, 0.35),
    Stock("KITE", "Kite Payments", "Financials", 156.0, 0.29, 1.1, 8_600_000),
    Stock("LUMA", "Luma Lighting", "Industrials", 22.0, 0.42, 1.2, 4_700_000),
    Stock("MESA", "Mesa Regional Bank", "Financials", 47.0, 0.26, 1.05, 6_100_000, 0.55),
    Stock("NEXA", "Nexa Telecom", "Communication", 29.0, 0.20, 0.6, 11_000_000, 0.41),
    Stock("ORCA", "Orca Shipping", "Industrials", 18.0, 0.48, 1.3, 9_300_000, 0.30),
    Stock("PIKE", "Pike Software", "Technology", 335.0, 0.33, 1.2, 2_500_000),
    Stock("QUIL", "Quill Media", "Communication", 15.0, 0.38, 1.0, 7_000_000),
    Stock("RIFT", "Rift Mining", "Materials", 44.0, 0.40, 1.1, 8_100_000, 0.25),
)

BY_TICKER = {s.ticker: s for s in STOCKS}


def trading_days(start: date = START, end: date = END) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in HOLIDAYS:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = trading_days()
MINUTE_WINDOW = DAYS[-MINUTE_DAYS:]


def nth(n: int) -> date:
    return DAYS[n]


# Earnings: one report per stock with options and several others. The jump
# follows the surprise, so "did they beat?" and "how did the stock react?" are
# consistent questions. Two reports fall inside the minute-data window.
EARNINGS: tuple[EarningsEvent, ...] = (
    EarningsEvent("ACME", DAYS[-6], "AMC", 1.42, 1.61, 5.10e9, 5.34e9, 0.071),
    EarningsEvent("BOLT", DAYS[-3], "BMO", -0.18, -0.31, 1.95e9, 1.71e9, -0.118),
    EarningsEvent("NOVA", DAYS[24], "AMC", 0.88, 0.97, 7.40e9, 7.62e9, 0.054),
    EarningsEvent("CRUX", DAYS[18], "AMC", 2.05, 2.11, 3.30e9, 3.28e9, -0.021),
    EarningsEvent("DYNE", DAYS[30], "BMO", -0.62, -0.48, 0.21e9, 0.24e9, 0.093),
    EarningsEvent("EMBR", DAYS[12], "BMO", 1.30, 1.22, 8.10e9, 7.95e9, -0.034),
    EarningsEvent("FERN", DAYS[15], "BMO", 0.74, 0.75, 4.20e9, 4.22e9, 0.006),
    EarningsEvent("HALO", DAYS[21], "BMO", 6.85, 7.40, 31.0e9, 31.9e9, 0.046),
    EarningsEvent("JADE", DAYS[35], "AMC", 0.92, 0.80, 6.70e9, 6.52e9, -0.087),
    EarningsEvent("KITE", DAYS[27], "AMC", 1.55, 1.71, 2.40e9, 2.51e9, 0.062),
    EarningsEvent("MESA", DAYS[9], "BMO", 1.10, 1.16, 0.95e9, 0.97e9, 0.019),
    EarningsEvent("PIKE", DAYS[33], "AMC", 3.20, 3.65, 1.10e9, 1.18e9, 0.112),
)

# Macro calendar with market-wide reactions at release (applied to every
# stock through its beta).
MACRO: tuple[MacroEvent, ...] = (
    MacroEvent("Nonfarm Payrolls", DAYS[2], "08:30", "high", 256.0, 160.0, 212.0, "K", -0.006),
    MacroEvent("CPI YoY", DAYS[8], "08:30", "high", 2.9, 2.9, 2.7, "%", 0.009),
    MacroEvent("FOMC Rate Decision", DAYS[18], "14:00", "high", 4.50, 4.50, 4.50, "%", -0.004),
    MacroEvent("Retail Sales MoM", DAYS[10], "08:30", "medium", -0.9, -0.2, 0.7, "%", -0.003),
    MacroEvent("Nonfarm Payrolls", DAYS[22], "08:30", "high", 143.0, 170.0, 256.0, "K", -0.005),
    MacroEvent("CPI YoY", DAYS[27], "08:30", "high", 3.0, 2.9, 2.9, "%", -0.011),
    MacroEvent("ISM Manufacturing PMI", DAYS[40], "10:00", "medium", 50.3, 50.5, 50.9, "", 0.002),
    MacroEvent("Nonfarm Payrolls", DAYS[44], "08:30", "high", 151.0, 160.0, 125.0, "K", 0.003),
    MacroEvent("CPI YoY", DAYS[48], "08:30", "high", 2.8, 2.9, 3.0, "%", 0.012),
    MacroEvent("FOMC Rate Decision", DAYS[-9], "14:00", "high", 4.50, 4.50, 4.50, "%", 0.008),
    MacroEvent("Initial Jobless Claims", DAYS[-4], "08:30", "low", 223.0, 225.0, 221.0, "K", 0.0),
)

# Option chains: expiries are Fridays (or the Thursday before a holiday).
OPTION_UNDERLYINGS = tuple(s.ticker for s in STOCKS if s.options)


@dataclass
class Universe:
    """Handle passed to the writers (kept small so tests can build variants)."""
    stocks: tuple[Stock, ...] = STOCKS
    days: list[date] = field(default_factory=lambda: list(DAYS))
    minute_days: list[date] = field(default_factory=lambda: list(MINUTE_WINDOW))
    earnings: tuple[EarningsEvent, ...] = EARNINGS
    macro: tuple[MacroEvent, ...] = MACRO
    seed: int = SEED
