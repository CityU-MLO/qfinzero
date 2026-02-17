from models.enums import Side, InstrumentType, MarginStatus
from models.position import Position
from models.event import AccountSnapshotPayload


class Ledger:
    """Pure in-memory accounting: cash, positions, P&L."""

    def __init__(self, initial_cash: float):
        self._cash: float = initial_cash
        self._initial_cash: float = initial_cash
        self._cash_locked: float = 0.0
        self._loan: float = 0.0
        self._positions: dict[str, Position] = {}
        self._realized_pnl: float = 0.0
        self._total_fees: float = 0.0

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def cash_locked(self) -> float:
        return self._cash_locked

    @property
    def loan(self) -> float:
        return self._loan

    @property
    def initial_cash(self) -> float:
        return self._initial_cash

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def total_fees(self) -> float:
        return self._total_fees

    @property
    def positions(self) -> dict[str, Position]:
        return self._positions

    def positions_list(self) -> list[Position]:
        return [p for p in self._positions.values() if p.qty != 0]

    def net_positions_value(self) -> float:
        return sum(p.qty * p.mark_price for p in self._positions.values())

    def total_equity(self) -> float:
        return self._cash + self.net_positions_value() - self._loan

    def apply_fill(
        self,
        instrument_id: str,
        instrument_type: InstrumentType,
        side: Side,
        qty: int,
        price: float,
        fees: float,
    ) -> float:
        """Apply a trade fill. Returns realized_pnl for this fill."""
        self._total_fees += fees
        realized = 0.0
        is_buy = side == Side.BUY

        pos = self._positions.get(instrument_id)

        if is_buy:
            cost = qty * price + fees
            self._cash -= cost
            if pos is None:
                self._positions[instrument_id] = Position(
                    instrument_id=instrument_id,
                    type=instrument_type,
                    qty=qty,
                    avg_price=price,
                    mark_price=price,
                )
            elif pos.qty >= 0:
                # Adding to long
                total_qty = pos.qty + qty
                new_avg = (pos.avg_price * pos.qty + price * qty) / total_qty
                pos.qty = total_qty
                pos.avg_price = new_avg
            else:
                # Covering short
                cover_qty = min(qty, abs(pos.qty))
                realized = cover_qty * (pos.avg_price - price)
                self._realized_pnl += realized
                remaining_buy = qty - cover_qty
                pos.qty += qty
                if pos.qty > 0:
                    pos.avg_price = price
                elif pos.qty == 0:
                    self._positions.pop(instrument_id, None)
        else:
            # SELL
            proceeds = qty * price - fees
            self._cash += proceeds
            if pos is None:
                # Opening short
                self._positions[instrument_id] = Position(
                    instrument_id=instrument_id,
                    type=instrument_type,
                    qty=-qty,
                    avg_price=price,
                    mark_price=price,
                )
            elif pos.qty > 0:
                # Closing long
                sell_qty = min(qty, pos.qty)
                realized = sell_qty * (price - pos.avg_price)
                self._realized_pnl += realized
                remaining_sell = qty - sell_qty
                pos.qty -= qty
                if pos.qty < 0:
                    pos.avg_price = price
                elif pos.qty == 0:
                    self._positions.pop(instrument_id, None)
            else:
                # Adding to short
                total_qty = abs(pos.qty) + qty
                new_avg = (pos.avg_price * abs(pos.qty) + price * qty) / total_qty
                pos.qty = -total_qty
                pos.avg_price = new_avg

        pos = self._positions.get(instrument_id)
        if pos is not None:
            pos.realized_pnl += realized

        return realized

    def update_market_prices(self, prices: dict[str, float]):
        """Mark-to-market all positions."""
        for iid, pos in self._positions.items():
            if iid in prices:
                pos.mark_price = prices[iid]
                pos.unrealized_pnl = pos.qty * (pos.mark_price - pos.avg_price)

    def get_snapshot(
        self,
        initial_margin_req: float,
        maintenance_margin_req: float,
        margin_status: MarginStatus,
        open_orders: list,
    ) -> AccountSnapshotPayload:
        equity = self.total_equity()
        margin_excess = equity - maintenance_margin_req
        buying_power = max(0.0, equity * 2 - initial_margin_req)

        return AccountSnapshotPayload(
            cash_available=round(self._cash, 2),
            cash_locked=round(self._cash_locked, 2),
            loan=round(self._loan, 2),
            equity=round(equity, 2),
            initial_margin_req=round(initial_margin_req, 2),
            maintenance_margin_req=round(maintenance_margin_req, 2),
            margin_excess=round(margin_excess, 2),
            buying_power=round(buying_power, 2),
            margin_status=margin_status.value,
            positions=[p.model_dump() for p in self.positions_list()],
            open_orders=open_orders,
        )
