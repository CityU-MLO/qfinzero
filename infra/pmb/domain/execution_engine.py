import random
import uuid

from models.enums import Side, OrderType, OrderStatus, InstrumentType, EventType
from models.order import Order
from models.trade import Trade
from models.market import StockBar, OptionBar, FutureBar, Quote
from models.event import (
    EventEnvelope,
    OrderEventPayload,
    TradeEventPayload,
    OptionExpiryEventPayload,
    AssignmentPayload,
)
from models.session import FeeModel, PartialFillConfig
from domain.trading_sessions import Segment, order_may_execute
from domain.order_manager import OrderManager
from domain.ledger import Ledger, OPTION_MULTIPLIER
from domain.margin_engine import MarginEngine


class ExecutionEngine:
    """Matches open orders against current bars, generates fills."""

    def __init__(
        self,
        seed: int | None,
        slippage_bps: float,
        fee_model: FeeModel,
        option_spread_pct: float = 0.0,
        partial_fill: PartialFillConfig | None = None,
        enforce_trading_hours: bool = False,
        option_fill_model: str = "bar",
    ):
        self._rng = random.Random(seed)
        self._partial = partial_fill or PartialFillConfig()
        self._enforce_hours = enforce_trading_hours
        self._quote_model = option_fill_model == "quote"
        self._quotes: dict[str, Quote] = {}
        self._future_bars: dict[str, FutureBar] = {}
        self._future_quotes: dict[str, Quote] = {}
        self._slippage_bps = slippage_bps
        self._option_spread_pct = option_spread_pct
        self._fee_model = fee_model
        self._event_seq = 0

    def _next_event_id(self) -> str:
        self._event_seq += 1
        return f"evt_{self._event_seq:06d}"

    def process_step(
        self,
        ts: str,
        ts_ns: int,
        stock_bars: dict[str, StockBar],
        option_bars: dict[str, OptionBar],
        order_manager: OrderManager,
        ledger: Ledger,
        margin_engine: MarginEngine,
        segment: Segment = Segment.REGULAR,
        trading_date: str | None = None,
        option_quotes: dict[str, Quote] | None = None,
        future_bars: dict[str, FutureBar] | None = None,
        future_quotes: dict[str, Quote] | None = None,
    ) -> tuple[list[EventEnvelope], list[Trade]]:
        """Process all open orders against current bars.

        Spread orders (linked by spread_id) are executed atomically:
        both legs fill or both are rejected. Non-spread orders execute individually.

        With trading hours enforced, an order only matches in the segments its
        ``trading_hours`` allow (options: REGULAR only); a DAY order is stamped
        with the trading date of its first eligible bar so it can expire at the
        end of that date.

        Returns (events, trades) generated this step.
        """
        events: list[EventEnvelope] = []
        trades: list[Trade] = []
        self._quotes = (option_quotes or {}) if self._quote_model else {}
        # Futures fill against their book whenever the session loaded one.
        self._future_bars = future_bars or {}
        self._future_quotes = future_quotes or {}

        open_orders = order_manager.get_open_orders()
        if self._enforce_hours:
            eligible = []
            for o in open_orders:
                if not order_may_execute(o.trading_hours, o.instrument_id, segment):
                    continue
                if o.session_date is None:
                    o.session_date = trading_date
                eligible.append(o)
            open_orders = eligible

        # Separate spread orders from individual orders
        spread_groups: dict[str, list[Order]] = {}
        individual_orders: list[Order] = []
        for order in open_orders:
            if order.spread_id:
                spread_groups.setdefault(order.spread_id, []).append(order)
            else:
                individual_orders.append(order)

        # Process spread groups atomically
        for spread_id, legs in spread_groups.items():
            spread_events, spread_trades = self._process_spread(
                ts, legs, stock_bars, option_bars, order_manager, ledger, margin_engine
            )
            events.extend(spread_events)
            trades.extend(spread_trades)

        # Process individual orders
        for order in individual_orders:
            order_events, order_trades = self._process_single_order(
                ts, order, stock_bars, option_bars, order_manager, ledger, margin_engine
            )
            events.extend(order_events)
            trades.extend(order_trades)

        return events, trades

    def _process_spread(
        self,
        ts: str,
        legs: list[Order],
        stock_bars: dict[str, StockBar],
        option_bars: dict[str, OptionBar],
        order_manager: OrderManager,
        ledger: Ledger,
        margin_engine: MarginEngine,
    ) -> tuple[list[EventEnvelope], list[Trade]]:
        """Execute a spread atomically: all legs fill or all are rejected."""
        events: list[EventEnvelope] = []
        trades: list[Trade] = []

        # Pre-check: all legs must have bars and fill prices
        leg_fills: list[tuple[Order, float]] = []
        for leg in legs:
            bar = self._get_bar_for_order(leg, stock_bars, option_bars)
            quote = self._quote_for(leg)
            if bar is None and quote is None:
                return events, trades  # Can't execute — wait
            fill_price = (self._quote_fill_price(quote, bar, leg) if quote is not None
                          else self._calculate_fill_price(bar, leg))
            if fill_price is None:
                return events, trades  # Can't execute — wait
            leg_fills.append((leg, fill_price))

        # Margin check not needed — spread margin is already handled at order submission
        # But check margin status
        if not margin_engine.can_open_position():
            for leg in legs:
                order_manager.reject(leg.order_id, "MARGIN_RESTRICTED", ts)
                events.append(EventEnvelope(
                    event_id=self._next_event_id(), ts=ts,
                    type=EventType.ORDER_EVENT,
                    payload=OrderEventPayload(
                        order_id=leg.order_id, client_order_id=leg.client_order_id,
                        status=OrderStatus.REJECTED.value,
                        filled_qty=leg.filled_qty, remaining_qty=leg.remaining_qty,
                        reason_code="MARGIN_RESTRICTED",
                    ).model_dump(),
                ))
            return events, trades

        # Execute all legs atomically
        for leg, fill_price in leg_fills:
            fill_qty = leg.remaining_qty
            fees = self._calculate_fees(leg, fill_qty)
            instrument_type = self._instrument_type(leg)

            ledger.apply_fill(
                instrument_id=leg.instrument_id,
                instrument_type=instrument_type,
                side=leg.side,
                qty=fill_qty,
                price=fill_price,
                fees=fees,
            )

            order_manager.record_fill(leg.order_id, fill_qty, fill_price, ts)

            trade_id = f"trd_{uuid.uuid4().hex[:8]}"
            trade = Trade(
                trade_id=trade_id, order_id=leg.order_id,
                instrument_id=leg.instrument_id, side=leg.side,
                qty=fill_qty, price=fill_price, fees=fees, ts=ts,
            )
            trades.append(trade)

            events.append(EventEnvelope(
                event_id=self._next_event_id(), ts=ts,
                type=EventType.ORDER_EVENT,
                payload=OrderEventPayload(
                    order_id=leg.order_id, client_order_id=leg.client_order_id,
                    status=leg.status.value,
                    filled_qty=leg.filled_qty, remaining_qty=leg.remaining_qty,
                    avg_fill_price=leg.avg_fill_price,
                ).model_dump(),
            ))
            events.append(EventEnvelope(
                event_id=self._next_event_id(), ts=ts,
                type=EventType.TRADE_EVENT,
                payload=TradeEventPayload(
                    trade_id=trade_id, order_id=leg.order_id,
                    instrument_id=leg.instrument_id, side=leg.side.value,
                    qty=fill_qty, price=fill_price, fees=fees,
                ).model_dump(),
            ))

        return events, trades

    def _process_single_order(
        self,
        ts: str,
        order: Order,
        stock_bars: dict[str, StockBar],
        option_bars: dict[str, OptionBar],
        order_manager: OrderManager,
        ledger: Ledger,
        margin_engine: MarginEngine,
    ) -> tuple[list[EventEnvelope], list[Trade]]:
        """Process a single (non-spread) order."""
        events: list[EventEnvelope] = []
        trades: list[Trade] = []

        bar = self._get_bar_for_order(order, stock_bars, option_bars)
        quote = self._quote_for(order)
        if bar is None and quote is None:
            return events, trades

        fill_price = (self._quote_fill_price(quote, bar, order) if quote is not None
                      else self._calculate_fill_price(bar, order))
        if fill_price is None:
            return events, trades

        is_future = order.instrument_id.startswith("FUTURE:")
        spec = margin_engine.future_spec(order.instrument_id.split(":", 1)[1]) if is_future else None
        if is_future and spec is None:
            return self._reject(order, "UNKNOWN_FUTURE_SPEC", ts, order_manager), trades
        if spec is not None:
            fill_price = spec.round_to_tick(fill_price)

        # Check if this is an opening position and margin allows it
        is_opening = self._is_opening_trade(order, ledger)
        if is_opening and not margin_engine.can_open_position():
            order_manager.reject(order.order_id, "MARGIN_RESTRICTED", ts)
            events.append(
                EventEnvelope(
                    event_id=self._next_event_id(),
                    ts=ts,
                    type=EventType.ORDER_EVENT,
                    payload=OrderEventPayload(
                        order_id=order.order_id,
                        client_order_id=order.client_order_id,
                        status=OrderStatus.REJECTED.value,
                        filled_qty=order.filled_qty,
                        remaining_qty=order.remaining_qty,
                        reason_code="MARGIN_RESTRICTED",
                    ).model_dump(),
                )
            )
            return events, trades

        # Futures: the opening contracts' initial margin must be free
        # (equity minus the initial margin of everything already held).
        if is_opening and is_future:
            need = margin_engine.future_initial_for_order(
                order.instrument_id.split(":", 1)[1], order.remaining_qty, fill_price) or 0.0
            free = ledger.total_equity() - margin_engine.total_initial_margin(ledger.positions)
            if need > free:
                return self._reject(order, "INSUFFICIENT_MARGIN", ts, order_manager), trades

        # Check buying power for this order
        if is_opening and not is_future:
            mult = OPTION_MULTIPLIER if order.instrument_id.startswith("OPTION:") else 1
            order_cost = order.remaining_qty * fill_price * mult
            total_needed = order_cost if order.side == Side.BUY else 0
            equity = ledger.total_equity()
            im = margin_engine.total_initial_margin(ledger.positions)
            bp = margin_engine.buying_power(equity, im)

            if order.side == Side.BUY and total_needed > ledger.cash + bp:
                order_manager.reject(order.order_id, "INSUFFICIENT_BUYING_POWER", ts)
                events.append(
                    EventEnvelope(
                        event_id=self._next_event_id(),
                        ts=ts,
                        type=EventType.ORDER_EVENT,
                        payload=OrderEventPayload(
                            order_id=order.order_id,
                            client_order_id=order.client_order_id,
                            status=OrderStatus.REJECTED.value,
                            filled_qty=order.filled_qty,
                            remaining_qty=order.remaining_qty,
                            reason_code="INSUFFICIENT_BUYING_POWER",
                        ).model_dump(),
                    )
                )
                return events, trades

        # Execute fill (optionally capped at a share of the bar's volume)
        fill_qty = order.remaining_qty
        if self._partial.enabled:
            if quote is not None:
                # displayed size on the side we take
                shown = quote.ask_size if order.side == Side.BUY else quote.bid_size
                cap = int(shown)
            else:
                cap = int(getattr(bar, "volume", 0) * self._partial.max_fill_ratio_per_tick)
            if cap <= 0:
                return events, trades      # no liquidity this bar: wait
            fill_qty = min(fill_qty, cap)
        fees = self._calculate_fees(order, fill_qty)
        if spec is not None and spec.fee_per_contract is not None:
            fees = round(fill_qty * spec.fee_per_contract, 4)

        instrument_type = self._instrument_type(order)

        ledger.apply_fill(
            instrument_id=order.instrument_id,
            instrument_type=instrument_type,
            side=order.side,
            qty=fill_qty,
            price=fill_price,
            fees=fees,
            multiplier=spec.multiplier if spec is not None else None,
        )

        order_manager.record_fill(order.order_id, fill_qty, fill_price, ts)

        trade_id = f"trd_{uuid.uuid4().hex[:8]}"
        trade = Trade(
            trade_id=trade_id,
            order_id=order.order_id,
            instrument_id=order.instrument_id,
            side=order.side,
            qty=fill_qty,
            price=fill_price,
            fees=fees,
            ts=ts,
        )
        trades.append(trade)

        # Order event
        events.append(
            EventEnvelope(
                event_id=self._next_event_id(),
                ts=ts,
                type=EventType.ORDER_EVENT,
                payload=OrderEventPayload(
                    order_id=order.order_id,
                    client_order_id=order.client_order_id,
                    status=order.status.value,
                    filled_qty=order.filled_qty,
                    remaining_qty=order.remaining_qty,
                    avg_fill_price=order.avg_fill_price,
                ).model_dump(),
            )
        )

        # Trade event
        events.append(
            EventEnvelope(
                event_id=self._next_event_id(),
                ts=ts,
                type=EventType.TRADE_EVENT,
                payload=TradeEventPayload(
                    trade_id=trade_id,
                    order_id=order.order_id,
                    instrument_id=order.instrument_id,
                    side=order.side.value,
                    qty=fill_qty,
                    price=fill_price,
                    fees=fees,
                ).model_dump(),
            )
        )

        return events, trades

    def _get_bar_for_order(
        self,
        order: Order,
        stock_bars: dict[str, StockBar],
        option_bars: dict[str, OptionBar],
    ) -> StockBar | OptionBar | None:
        iid = order.instrument_id
        if iid.startswith("STOCK:"):
            symbol = iid.split(":", 1)[1]
            return stock_bars.get(symbol)
        elif iid.startswith("OPTION:"):
            contract = iid.split(":", 1)[1]
            return option_bars.get(contract)
        elif iid.startswith("FUTURE:"):
            return self._future_bars.get(iid.split(":", 1)[1])
        return None

    def _quote_for(self, order: Order) -> Quote | None:
        if order.instrument_id.startswith("FUTURE:"):
            return self._future_quotes.get(order.instrument_id.split(":", 1)[1])
        if not self._quote_model or not order.instrument_id.startswith("OPTION:"):
            return None
        return self._quotes.get(order.instrument_id.split(":", 1)[1])

    def _reject(self, order: Order, reason: str, ts: str, order_manager: OrderManager) -> list[EventEnvelope]:
        order_manager.reject(order.order_id, reason, ts)
        return [EventEnvelope(
            event_id=self._next_event_id(), ts=ts, type=EventType.ORDER_EVENT,
            payload=OrderEventPayload(
                order_id=order.order_id, client_order_id=order.client_order_id,
                status=OrderStatus.REJECTED.value, filled_qty=order.filled_qty,
                remaining_qty=order.remaining_qty, reason_code=reason,
            ).model_dump(),
        )]

    def _quote_fill_price(self, quote: Quote, bar: OptionBar | None, order: Order) -> float | None:
        """Fill against the book in force at the bar open.

        MARKET takes the ask (buy) or bid (sell). A marketable LIMIT fills at the
        quote; a resting LIMIT fills at its own price only if a trade printed
        through it during the bar. STOP orders trigger on the bar or the book and
        then take the quote. No book side, no fill (the order waits).
        """
        is_buy = order.side == Side.BUY
        take = quote.valid_ask if is_buy else quote.valid_bid

        def through(price: float) -> bool:
            if bar is None:
                return False
            return bar.low <= price if is_buy else bar.high >= price

        def limit_fill(limit: float) -> float | None:
            if take is not None and (take <= limit if is_buy else take >= limit):
                return round(take, 4)
            if through(limit):
                return round(limit, 4)
            return None

        if order.order_type == OrderType.MARKET:
            return round(take, 4) if take is not None else None
        if order.order_type == OrderType.LIMIT:
            return limit_fill(order.limit_price)
        stop = order.stop_price
        trig = (bar is not None and (bar.high >= stop if is_buy else bar.low <= stop)) or (
            take is not None and (take >= stop if is_buy else take <= stop))
        if not trig:
            return None
        if order.order_type == OrderType.STOP:
            return round(take, 4) if take is not None else None
        if order.order_type == OrderType.STOP_LIMIT:
            return limit_fill(order.limit_price)
        return None

    def _calculate_fill_price(self, bar: StockBar | OptionBar, order: Order) -> float | None:
        is_buy = order.side == Side.BUY

        if order.order_type == OrderType.MARKET:
            price = self._apply_slippage(bar.open, is_buy)
            # Apply bid-ask spread cost for options (half-spread adverse to trader)
            if self._option_spread_pct > 0 and order.instrument_id.startswith("OPTION:"):
                half_spread = bar.open * self._option_spread_pct / 2
                price = price + half_spread if is_buy else price - half_spread
                price = max(price, 0.0001)  # floor at minimum tick
            return round(price, 4)

        if order.order_type == OrderType.LIMIT:
            if is_buy and bar.low <= order.limit_price:
                return min(order.limit_price, bar.close)
            if not is_buy and bar.high >= order.limit_price:
                return max(order.limit_price, bar.close)
            return None

        if order.order_type == OrderType.STOP:
            if is_buy and bar.high >= order.stop_price:
                return self._apply_slippage(max(order.stop_price, bar.open), is_buy)
            if not is_buy and bar.low <= order.stop_price:
                return self._apply_slippage(min(order.stop_price, bar.open), not is_buy)
            return None

        if order.order_type == OrderType.STOP_LIMIT:
            # Check stop trigger
            triggered = False
            if is_buy and bar.high >= order.stop_price:
                triggered = True
            if not is_buy and bar.low <= order.stop_price:
                triggered = True
            if not triggered:
                return None
            # Then check limit
            if is_buy and bar.low <= order.limit_price:
                return min(order.limit_price, bar.close)
            if not is_buy and bar.high >= order.limit_price:
                return max(order.limit_price, bar.close)
            return None

        return None

    def _apply_slippage(self, price: float, is_buy: bool) -> float:
        bps = self._rng.uniform(0, self._slippage_bps)
        factor = 1 + bps / 10000 if is_buy else 1 - bps / 10000
        return round(price * factor, 4)

    def _calculate_fees(self, order: Order, qty: int) -> float:
        if order.instrument_id.startswith("OPTION:"):
            return round(qty * self._fee_model.option_fee_per_contract, 4)
        if order.instrument_id.startswith("FUTURE:"):
            return round(qty * self._fee_model.future_fee_per_contract, 4)
        return round(qty * self._fee_model.stock_fee_per_share, 4)

    def _instrument_type(self, order: Order) -> InstrumentType:
        if order.instrument_id.startswith("STOCK:"):
            return InstrumentType.STOCK
        if order.instrument_id.startswith("FUTURE:"):
            return InstrumentType.FUTURE
        return InstrumentType.OPTION

    def liquidate_futures(self, ts: str, prices: dict[str, float], ledger: Ledger,
                          margin_engine: MarginEngine) -> tuple[list[EventEnvelope], list[Trade]]:
        """Close every futures position at ``prices`` (the settlement) after an
        unmet margin call. Fills carry the order id ``LIQUIDATION``."""
        events: list[EventEnvelope] = []
        trades: list[Trade] = []
        for pos in list(ledger.future_positions()):
            price = prices.get(pos.instrument_id, pos.mark_price)
            spec = margin_engine.future_spec(pos.instrument_id.split(":", 1)[1])
            qty = abs(pos.qty)
            side = Side.SELL if pos.qty > 0 else Side.BUY
            per = spec.fee_per_contract if spec is not None and spec.fee_per_contract is not None \
                else self._fee_model.future_fee_per_contract
            fees = round(qty * per, 4)
            ledger.apply_fill(pos.instrument_id, InstrumentType.FUTURE, side, qty, price, fees,
                              multiplier=pos.multiplier)
            trade = Trade(trade_id=f"trd_{uuid.uuid4().hex[:8]}", order_id="LIQUIDATION",
                          instrument_id=pos.instrument_id, side=side, qty=qty, price=price,
                          fees=fees, ts=ts)
            trades.append(trade)
            events.append(EventEnvelope(
                event_id=self._next_event_id(), ts=ts, type=EventType.TRADE_EVENT,
                payload=TradeEventPayload(trade_id=trade.trade_id, order_id="LIQUIDATION",
                                          instrument_id=pos.instrument_id, side=side.value,
                                          qty=qty, price=price, fees=fees).model_dump(),
            ))
        return events, trades

    def _is_opening_trade(self, order: Order, ledger: Ledger) -> bool:
        """Check if this order opens or increases a position."""
        pos = ledger.positions.get(order.instrument_id)
        if pos is None:
            return True
        if order.side == Side.BUY and pos.qty >= 0:
            return True  # adding to long
        if order.side == Side.SELL and pos.qty <= 0:
            return True  # adding to short
        return False  # closing existing position

    def process_expiries(
        self,
        ts: str,
        actions: list,
        ledger: "Ledger",
        order_manager: "OrderManager",
        margin_engine: "MarginEngine",
    ) -> list:
        """Apply option expiry lifecycle actions. Returns list of EventEnvelope."""
        from domain.option_lifecycle import ExpiryAction

        events = []
        for action in actions:
            pos = action.option_pos
            option_iid = action.instrument_id

            # Capture signed qty before apply_fill mutates the position to 0
            original_qty = pos.qty

            # 1. Close option position at expiry settlement price
            # Short position (assignment): close at 0.0, ITM value captured via stock fill at strike
            # Long position (exercise): close at intrinsic_value to realize profit
            close_price = 0.0 if original_qty < 0 else action.intrinsic_value
            exercise_fee = self._fee_model.option_exercise_fee * abs(original_qty)
            realized_option = ledger.apply_fill(
                instrument_id=option_iid,
                instrument_type=InstrumentType.OPTION,
                side=Side.BUY if original_qty < 0 else Side.SELL,
                qty=abs(original_qty),
                price=close_price,
                fees=exercise_fee,
            )

            # 2. If ITM short: execute underlying stock transaction at strike price
            assignment = None
            if action.stock_side is not None and action.underlying is not None:
                stock_iid = f"STOCK:{action.underlying}"
                stock_fee = self._fee_model.stock_fee_per_share * action.stock_qty
                ledger.apply_fill(
                    instrument_id=stock_iid,
                    instrument_type=InstrumentType.STOCK,
                    side=action.stock_side,
                    qty=action.stock_qty,
                    price=action.strike,
                    fees=stock_fee,
                )
                assignment = AssignmentPayload(
                    underlying=action.underlying,
                    side=action.stock_side.value,
                    qty=action.stock_qty,
                    strike=action.strike,
                )

            # 3. Emit OPTION_EXPIRY_EVENT
            payload = OptionExpiryEventPayload(
                contract=action.contract,
                is_itm=action.is_itm,
                intrinsic_value=action.intrinsic_value,
                option_qty=original_qty,
                realized_pnl=round(realized_option, 4),
                assignment=assignment,
            )
            events.append(EventEnvelope(
                event_id=self._next_event_id(),
                ts=ts,
                type=EventType.OPTION_EXPIRY_EVENT,
                payload=payload.model_dump(),
            ))

        return events
