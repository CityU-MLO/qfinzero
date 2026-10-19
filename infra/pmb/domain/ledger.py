from models.enums import Side, InstrumentType, MarginStatus
from models.position import Position
from models.event import AccountSnapshotPayload

OPTION_MULTIPLIER = 100


def multiplier_of(pos: Position) -> float:
    if pos.type == InstrumentType.OPTION:
        return OPTION_MULTIPLIER
    if pos.type == InstrumentType.FUTURE:
        return pos.multiplier or 1.0
    return 1


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
        """Market value of stocks and options plus the open trade equity of
        futures (their change since the last settlement; futures have no
        market value of their own)."""
        total = 0.0
        for p in self._positions.values():
            if p.type == InstrumentType.FUTURE:
                total += p.qty * (p.mark_price - (p.basis_price or p.avg_price)) * multiplier_of(p)
            else:
                total += p.qty * p.mark_price * multiplier_of(p)
        return total

    def future_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.type == InstrumentType.FUTURE and p.qty]

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
        multiplier: float | None = None,
    ) -> float:
        """Apply a trade fill. Returns realized_pnl for this fill.

        For options, qty is in contracts and price is per-share premium.
        The multiplier (100) is applied to convert to notional value.
        Futures (``multiplier`` = the contract's) move only fees and realized
        P&L through cash; see :meth:`_apply_future_fill`.
        """
        if instrument_type == InstrumentType.FUTURE:
            return self._apply_future_fill(instrument_id, side, qty, price, fees, multiplier or 1.0)
        self._total_fees += fees
        realized = 0.0
        is_buy = side == Side.BUY
        mult = OPTION_MULTIPLIER if instrument_type == InstrumentType.OPTION else 1

        pos = self._positions.get(instrument_id)

        if is_buy:
            cost = qty * price * mult + fees
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
                realized = cover_qty * (pos.avg_price - price) * mult
                self._realized_pnl += realized
                remaining_buy = qty - cover_qty
                pos.qty += qty
                if pos.qty > 0:
                    pos.avg_price = price
                elif pos.qty == 0:
                    self._positions.pop(instrument_id, None)
        else:
            # SELL
            proceeds = qty * price * mult - fees
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
                realized = sell_qty * (price - pos.avg_price) * mult
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

    def _apply_future_fill(self, instrument_id: str, side: Side, qty: int, price: float,
                           fees: float, mult: float) -> float:
        """A futures fill posts no premium: cash pays the fees, and a closing
        fill settles the move since the basis (the last settlement) in cash.
        Realized P&L is measured from the trade price (``avg_price``)."""
        self._total_fees += fees
        self._cash -= fees
        signed = qty if side == Side.BUY else -qty
        pos = self._positions.get(instrument_id)
        realized = 0.0
        if pos is None or pos.qty == 0:
            self._positions[instrument_id] = Position(
                instrument_id=instrument_id, type=InstrumentType.FUTURE, qty=signed,
                avg_price=price, mark_price=price, multiplier=mult, basis_price=price,
                realized_pnl=pos.realized_pnl if pos else 0.0,
            )
            return 0.0
        basis = pos.basis_price if pos.basis_price is not None else pos.avg_price
        if (pos.qty > 0) == (signed > 0):          # adding
            n0, n = abs(pos.qty), abs(pos.qty) + qty
            pos.avg_price = (pos.avg_price * n0 + price * qty) / n
            pos.basis_price = (basis * n0 + price * qty) / n
            pos.qty += signed
        else:                                       # reducing, closing or flipping
            close = min(qty, abs(pos.qty))
            direction = 1 if pos.qty > 0 else -1
            realized = close * (price - pos.avg_price) * mult * direction
            self._cash += close * (price - basis) * mult * direction
            self._realized_pnl += realized
            pos.realized_pnl += realized
            pos.qty += signed
            if pos.qty == 0:
                self._positions.pop(instrument_id, None)
            elif qty > close:                       # flipped: the rest opens at this price
                pos.avg_price = price
                pos.basis_price = price
                pos.last_settle_date = None
        return realized

    def roll_future(self, instrument_id: str, new_price: float, contract_id: int) -> dict | None:
        """Move a futures position on a continuous series to its next contract at
        ``new_price``. Entry and basis shift by the gap from the old contract's
        mark, so open P&L carries over and the spread between the contracts is
        not booked as a gain or loss."""
        pos = self._positions.get(instrument_id)
        if pos is None or pos.type != InstrumentType.FUTURE or not pos.qty:
            return None
        old = pos.mark_price or (pos.basis_price if pos.basis_price is not None else pos.avg_price)
        shift = new_price - old
        prev = pos.contract_id
        pos.avg_price += shift
        pos.basis_price = (pos.basis_price if pos.basis_price is not None else old) + shift
        pos.mark_price = new_price
        pos.contract_id = contract_id
        return {"instrument_id": instrument_id, "qty": pos.qty, "from_contract": prev, "to_contract": contract_id,
                "old_price": old, "new_price": new_price}

    def settle_futures(self, settles: dict[str, float], session_date: str) -> list[dict]:
        """Daily settlement: pay ``qty * (settle - basis) * multiplier`` into cash
        for each futures position with a settle price, and move its basis to the
        settle. Returns one record per settled position."""
        out = []
        for iid, pos in self._positions.items():
            if pos.type != InstrumentType.FUTURE or not pos.qty or iid not in settles:
                continue
            if pos.last_settle_date == session_date:
                continue
            settle = settles[iid]
            prev = pos.basis_price if pos.basis_price is not None else pos.avg_price
            amount = pos.qty * (settle - prev) * multiplier_of(pos)
            self._cash += amount
            pos.basis_price = settle
            pos.mark_price = settle
            pos.last_settle_date = session_date
            pos.unrealized_pnl = pos.qty * (settle - pos.avg_price) * multiplier_of(pos)
            out.append({"instrument_id": iid, "session_date": session_date, "qty": pos.qty,
                        "prev_price": round(prev, 10), "settle": settle, "amount": round(amount, 2)})
        return out

    def update_market_prices(self, prices: dict[str, float]):
        """Mark-to-market all positions."""
        for iid, pos in self._positions.items():
            if iid in prices:
                pos.mark_price = prices[iid]
                pos.unrealized_pnl = pos.qty * (pos.mark_price - pos.avg_price) * multiplier_of(pos)

    def get_snapshot(
        self,
        initial_margin_req: float,
        maintenance_margin_req: float,
        margin_status: MarginStatus,
        open_orders: list,
        leverage: float = 2.0,
    ) -> AccountSnapshotPayload:
        equity = self.total_equity()
        margin_excess = equity - maintenance_margin_req
        buying_power = max(0.0, equity * leverage - initial_margin_req)

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
