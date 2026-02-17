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


class SessionStatus(str, Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FINISHED = "FINISHED"
