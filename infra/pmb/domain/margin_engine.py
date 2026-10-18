from models.account import MarginConfig
from models.enums import Side, InstrumentType, MarginStatus
from models.position import Position
from models.event import RiskEventPayload
from domain.futures import FutureSpec, resolve_spec
from domain.ledger import OPTION_MULTIPLIER


class MarginEngine:
    """Calculates margin requirements and detects margin calls.

    Stocks and options use Reg-T style ratios of market value. Futures use a
    fixed amount per contract from their spec (see ``domain/futures.py``),
    priced off the last settlement, and a futures margin call is met only when
    equity is back at the initial margin.
    """

    def __init__(self, config: MarginConfig):
        self._config = config
        self._margin_status = MarginStatus.NORMAL
        self._margin_call_count = 0
        self._call_sessions = 0      # settlements a futures margin call has stayed open

    # ── futures ──────────────────────────────────────────────────────

    def future_spec(self, symbol: str) -> FutureSpec | None:
        return resolve_spec(symbol, self._config.future_specs)

    def _future_margin(self, pos: Position, initial: bool) -> float:
        spec = self.future_spec(pos.instrument_id.split(":", 1)[1])
        if spec is None:
            return 0.0
        ref = pos.basis_price if pos.basis_price is not None else pos.avg_price
        per = spec.initial_per_contract(ref) if initial else spec.maintenance_per_contract(ref)
        return abs(pos.qty) * per

    def future_initial_for_order(self, symbol: str, qty: int, price: float) -> float | None:
        """Initial margin to open ``qty`` contracts at ``price`` (None: unknown contract)."""
        spec = self.future_spec(symbol)
        return None if spec is None else qty * spec.initial_per_contract(price)

    @property
    def call_sessions(self) -> int:
        return self._call_sessions

    def on_settlement(self, equity: float, positions: dict[str, Position]) -> str | None:
        """After a futures settlement: ``"LIQUIDATE"`` when a margin call has stayed
        open for ``future_margin_call_sessions`` settlements, else None."""
        has_futures = any(p.type == InstrumentType.FUTURE and p.qty for p in positions.values())
        if self._margin_status == MarginStatus.NORMAL or not has_futures:
            self._call_sessions = 0
            return None
        self._call_sessions += 1
        limit = self._config.future_margin_call_sessions
        if limit > 0 and self._call_sessions > limit:
            self._margin_status = MarginStatus.LIQUIDATION
            return "LIQUIDATE"
        return None

    @property
    def margin_status(self) -> MarginStatus:
        return self._margin_status

    @property
    def margin_call_count(self) -> int:
        return self._margin_call_count

    def initial_margin_for_order(
        self, side: Side, instrument_type: InstrumentType, qty: int, price: float
    ) -> float:
        """Margin required to accept an order."""
        if instrument_type == InstrumentType.FUTURE:
            return 0.0      # see future_initial_for_order (needs the contract)
        mult = OPTION_MULTIPLIER if instrument_type == InstrumentType.OPTION else 1
        mv = qty * price * mult
        if instrument_type == InstrumentType.STOCK:
            if side == Side.BUY:
                return mv * self._config.stock_initial
            else:
                return mv * self._config.short_stock_initial
        else:
            # OPTION
            if side == Side.BUY:
                return 0.0  # long option: premium only
            else:
                return mv * self._config.option_short_a

    def total_initial_margin(self, positions: dict[str, Position]) -> float:
        """Sum of initial margin across all positions."""
        total = 0.0
        for pos in positions.values():
            if pos.qty == 0:
                continue
            if pos.type == InstrumentType.FUTURE:
                total += self._future_margin(pos, initial=True)
                continue
            mult = OPTION_MULTIPLIER if pos.type == InstrumentType.OPTION else 1
            mv = abs(pos.qty) * pos.mark_price * mult
            if pos.type == InstrumentType.STOCK:
                if pos.qty > 0:
                    total += mv * self._config.stock_initial
                else:
                    total += mv * self._config.short_stock_initial
            else:
                if pos.qty < 0:
                    total += mv * self._config.option_short_a
        return total

    def total_maintenance_margin(self, positions: dict[str, Position]) -> float:
        """Sum of maintenance margin across all positions."""
        total = 0.0
        for pos in positions.values():
            if pos.qty == 0:
                continue
            if pos.type == InstrumentType.FUTURE:
                total += self._future_margin(pos, initial=False)
                continue
            mult = OPTION_MULTIPLIER if pos.type == InstrumentType.OPTION else 1
            mv = abs(pos.qty) * pos.mark_price * mult
            if pos.type == InstrumentType.STOCK:
                if pos.qty > 0:
                    total += mv * self._config.stock_maintenance
                else:
                    total += mv * self._config.short_stock_maintenance
            else:
                if pos.qty < 0:
                    total += mv * self._config.option_short_b
        return total

    def buying_power(self, equity: float, initial_margin: float) -> float:
        return max(0.0, equity * 2 - initial_margin)

    def check_maintenance(
        self, equity: float, positions: dict[str, Position]
    ) -> RiskEventPayload | None:
        """Check if equity is below maintenance margin. Returns RiskEvent if breached."""
        mm = self.total_maintenance_margin(positions)
        has_futures = any(p.type == InstrumentType.FUTURE and p.qty for p in positions.values())
        im = self.total_initial_margin(positions)

        if equity < mm and mm > 0:
            if self._margin_status == MarginStatus.NORMAL:
                self._margin_call_count += 1
            if self._margin_status != MarginStatus.LIQUIDATION:
                self._margin_status = MarginStatus.MARGIN_CALL
            return RiskEventPayload(
                level="MARGIN_CALL",
                reason_code="EQUITY_BELOW_MAINTENANCE",
                equity=round(equity, 2),
                maintenance_margin_req=round(mm, 2),
                action="RESTRICT_NEW_POSITIONS",
                initial_margin_req=round(im, 2),
                # futures calls are met at the initial margin (CME), others at maintenance
                call_amount=round((im if has_futures else mm) - equity, 2),
            )

        # A futures call stays open until equity is back at the initial margin.
        if self._margin_status != MarginStatus.NORMAL and has_futures and equity < im:
            return None
        if equity >= mm:
            self._margin_status = MarginStatus.NORMAL
            self._call_sessions = 0
        return None

    def margin_for_spread(self, spread_width: float, qty: int, multiplier: int = 100) -> float:
        """Margin for a spread = max loss = width × qty × multiplier."""
        return spread_width * qty * multiplier

    def can_open_position(self) -> bool:
        """Whether new positions are allowed under current margin status."""
        return self._margin_status == MarginStatus.NORMAL
