from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict

from .enums import MarginStatus, Market, AccountStatus, Side


class MarginConfig(BaseModel):
    stock_initial: float = 0.50
    stock_maintenance: float = 0.25
    short_stock_initial: float = 1.50
    short_stock_maintenance: float = 1.30
    option_short_a: float = 0.20
    option_short_b: float = 0.10


class AccountConstraints(BaseModel):
    no_overnight: bool = True
    force_flatten_at_close: bool = True


class CreateAccountRequest(BaseModel):
    base_currency: Optional[str] = None  # defaults to the market currency
    account_type: str = "MARGIN"
    initial_cash: Optional[float] = None  # None → broker default (PMB config)
    market: Optional[Market] = None       # None → broker default market
    timezone: Optional[str] = None  # defaults to the market timezone
    # open_date is the public alias agents use; start_date kept for back-compat.
    start_date: Optional[str] = None
    open_date: Optional[str] = None
    constraints: Optional[AccountConstraints] = None
    margin_config: Optional[MarginConfig] = None

    def resolved_open_date(self) -> Optional[str]:
        return self.open_date or self.start_date


# ── Broker book (self-contained, agent-driven paper trading) ────────────


class BrokerPosition(BaseModel):
    symbol: str
    qty: int = 0
    avg_price: float = 0.0
    last_price: float = 0.0

    def market_value(self) -> float:
        return round(self.qty * self.last_price, 2)

    def unrealized_pnl(self) -> float:
        return round(self.qty * (self.last_price - self.avg_price), 2)

    def to_view(self) -> dict:
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "avg_price": round(self.avg_price, 4),
            "last_price": round(self.last_price, 4),
            "market_value": self.market_value(),
            "unrealized_pnl": self.unrealized_pnl(),
        }


class BrokerFill(BaseModel):
    """A single executed paper trade, stamped with the trading day it belongs to."""

    trade_id: str
    trading_day: int
    date: str
    symbol: str
    side: Side
    qty: int
    price: float
    gross: float
    fees: float
    realized_pnl: float = 0.0
    note: Optional[str] = None


class TradingDayRecord(BaseModel):
    """One step in the account's trading history — a single trading day."""

    trading_day: int
    date: str
    opening_equity: float
    closing_equity: float
    realized_pnl: float
    cash: float
    num_trades: int
    fees: float
    trades: List[BrokerFill] = []
    positions: List[Dict[str, Any]] = []
    closed_at: str


class TradeRequest(BaseModel):
    symbol: str
    side: Side
    qty: int = Field(gt=0)
    # price is optional: when omitted the broker tries to mark from UPQ, otherwise
    # the caller (agent) supplies the execution price it observed.
    price: Optional[float] = None
    note: Optional[str] = None


class NextDayRequest(BaseModel):
    # Optional explicit date; otherwise the broker advances to the next weekday.
    date: Optional[str] = None


# ── Snapshot returned to clients ────────────────────────────────────────


class AccountState(BaseModel):
    cash_available: float
    cash_locked: float = 0.0
    loan: float = 0.0
    equity: float
    initial_margin_req: float = 0.0
    maintenance_margin_req: float = 0.0
    margin_excess: float = 0.0
    buying_power: float = 0.0
    margin_status: MarginStatus = MarginStatus.NORMAL
    positions: List[Any] = []
    open_orders: List[Any] = []


class Account(BaseModel):
    account_id: str
    base_currency: str = "USD"
    account_type: str = "MARGIN"
    market: Market = Market.US
    initial_cash: float
    timezone: str = "America/New_York"
    # open_date is the canonical field; start_date mirrors it for back-compat.
    open_date: str
    start_date: str
    created_at: str
    constraints: AccountConstraints = AccountConstraints()
    margin_config: MarginConfig = MarginConfig()

    # ── Day-gated broker book (mutated by AccountService) ──────────────
    status: AccountStatus = AccountStatus.ACTIVE
    trading_day: int = 1
    current_date: str = ""
    cash: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    trade_seq: int = 0
    positions: Dict[str, BrokerPosition] = {}
    trades_today: List[BrokerFill] = []
    day_opening_equity: float = 0.0
    history: List[TradingDayRecord] = []

    # equity / valuation helpers ----------------------------------------

    def positions_value(self) -> float:
        return sum(p.qty * p.last_price for p in self.positions.values())

    def equity(self) -> float:
        return self.cash + self.positions_value()

    def open_positions(self) -> List[BrokerPosition]:
        return [p for p in self.positions.values() if p.qty != 0]
