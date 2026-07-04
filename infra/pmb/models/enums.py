from enum import Enum


class Frequency(str, Enum):
    MINUTE = "1m"
    DAILY = "1d"


class InstrumentType(str, Enum):
    STOCK = "STOCK"
    OPTION = "OPTION"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TimeInForce(str, Enum):
    DAY = "DAY"
    GTC = "GTC"
    GTD = "GTD"


class OrderStatus(str, Enum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class MarginStatus(str, Enum):
    NORMAL = "NORMAL"
    MARGIN_CALL = "MARGIN_CALL"
    RESTRICTED = "RESTRICTED"
    LIQUIDATION = "LIQUIDATION"


class EventType(str, Enum):
    MARKET_TICK = "MARKET_TICK"
    ORDER_EVENT = "ORDER_EVENT"
    TRADE_EVENT = "TRADE_EVENT"
    ACCOUNT_SNAPSHOT = "ACCOUNT_SNAPSHOT"
    RISK_EVENT = "RISK_EVENT"
    ERROR_EVENT = "ERROR_EVENT"
    OPTION_EXPIRY_EVENT = "OPTION_EXPIRY_EVENT"


class SessionStatus(str, Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FINISHED = "FINISHED"


class Market(str, Enum):
    """Tradable market an account is opened against."""

    CN = "cn"  # Mainland China A-shares
    US = "us"  # United States
    HK = "hk"  # Hong Kong


# Per-market defaults: account-id leading digit, base currency, exchange timezone.
# The leading digit makes a 10-digit account number self-describing (like a real
# brokerage routing prefix): 6xxxxxxxxx → CN, 1xxxxxxxxx → US, 3xxxxxxxxx → HK.
MARKET_PROFILE: dict[Market, dict] = {
    Market.CN: {"lead_digit": "6", "currency": "CNY", "timezone": "Asia/Shanghai"},
    Market.US: {"lead_digit": "1", "currency": "USD", "timezone": "America/New_York"},
    Market.HK: {"lead_digit": "3", "currency": "HKD", "timezone": "Asia/Hong_Kong"},
}


class AccountStatus(str, Enum):
    """Broker-account day-gating lifecycle.

    ACTIVE  — open for trading on the current simulated day.
    FROZEN  — the day has been closed; trading is rejected until next_day().
    CLOSED  — the account has been permanently closed.
    """

    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"
