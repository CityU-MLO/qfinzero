from models.account import MarginConfig
from models.enums import Side, InstrumentType, MarginStatus
from models.position import Position
from models.event import RiskEventPayload


class MarginEngine:
    """Calculates margin requirements and detects margin calls."""

    def __init__(self, config: MarginConfig):
        self._config = config
        self._margin_status = MarginStatus.NORMAL
        self._margin_call_count = 0

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
        mv = qty * price
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
            mv = abs(pos.qty) * pos.mark_price
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
            mv = abs(pos.qty) * pos.mark_price
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

        if equity < mm and mm > 0:
            if self._margin_status == MarginStatus.NORMAL:
                self._margin_call_count += 1
            self._margin_status = MarginStatus.MARGIN_CALL
            return RiskEventPayload(
                level="MARGIN_CALL",
                reason_code="EQUITY_BELOW_MAINTENANCE",
                equity=round(equity, 2),
                maintenance_margin_req=round(mm, 2),
                action="RESTRICT_NEW_POSITIONS",
            )

        if equity >= mm:
            self._margin_status = MarginStatus.NORMAL
        return None

    def can_open_position(self) -> bool:
        """Whether new positions are allowed under current margin status."""
        return self._margin_status == MarginStatus.NORMAL
