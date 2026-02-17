from pydantic import BaseModel
from typing import Optional, List, Any

from .enums import Frequency, SessionStatus


class Universe(BaseModel):
    stocks: List[str] = []
    options: List[str] = []


class UPQConfig(BaseModel):
    base_url: str = "http://127.0.0.1:23333"
    fields_stock_minute: str = "ticker,window_start,open,high,low,close,volume"
    fields_stock_daily: str = "ticker,date,open,high,low,close,volume"


class FeeModel(BaseModel):
    stock_fee_per_share: float = 0.0005
    option_fee_per_contract: float = 0.65


class PartialFillConfig(BaseModel):
    enabled: bool = False
    max_fill_ratio_per_tick: float = 1.0


class ExecutionConfig(BaseModel):
    price_rule: str = "LAST"
    slippage_bps: float = 1.0
    fee_model: FeeModel = FeeModel()
    partial_fill: PartialFillConfig = PartialFillConfig()


class ReproducibilityConfig(BaseModel):
    seed: Optional[int] = None
    run_id: Optional[str] = None


class ClockState(BaseModel):
    frequency: Frequency
    current_ts: str
    end_ts: str
    status: SessionStatus


class CreateSessionRequest(BaseModel):
    account_id: str
    frequency: Frequency = Frequency.MINUTE
    start_ts: str
    end_ts: str
    universe: Universe
    upq: Optional[UPQConfig] = None
    execution_config: Optional[ExecutionConfig] = None
    reproducibility: Optional[ReproducibilityConfig] = None


class StepRequest(BaseModel):
    step: int = 1
    target_ts: Optional[str] = None


class SessionSummary(BaseModel):
    session_id: str
    run_id: Optional[str] = None
    start_ts: str
    end_ts: str
    final_equity: float
    total_return: float
    max_drawdown: float
    fees_paid: float
    num_orders: int
    num_trades: int
    reject_rate: float = 0.0
    invalid_action_rate: float = 0.0
    margin_call_count: int = 0
