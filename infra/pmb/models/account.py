from pydantic import BaseModel
from typing import Optional, List, Any

from .enums import MarginStatus


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
    base_currency: str = "USD"
    account_type: str = "MARGIN"
    initial_cash: float
    timezone: str = "America/New_York"
    start_date: str
    constraints: Optional[AccountConstraints] = None
    margin_config: Optional[MarginConfig] = None


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
    initial_cash: float
    timezone: str = "America/New_York"
    start_date: str
    created_at: str
    constraints: AccountConstraints = AccountConstraints()
    margin_config: MarginConfig = MarginConfig()
