import uuid
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from models.enums import Frequency, EventType, SessionStatus
from models.account import Account, MarginConfig
from models.session import (
    CreateSessionRequest,
    ExecutionConfig,
    FeeModel,
    ClockState,
    SessionSummary,
)
from models.event import (
    EventEnvelope,
    MarketTickPayload,
    AccountSnapshotPayload,
    RiskEventPayload,
)
from domain.session_clock import SessionClock, ns_to_iso
from domain.market_data_cache import MarketDataCache
from domain.order_manager import OrderManager
from domain.execution_engine import ExecutionEngine
from domain.margin_engine import MarginEngine
from domain.ledger import Ledger
from domain.history_store import HistoryStore
from domain.option_lifecycle import check_option_expiries, get_expiring_contracts
from clients.upq_client import UPQClient

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Container for all domain objects belonging to one session."""

    session_id: str
    account_id: str
    config: CreateSessionRequest
    clock: SessionClock
    cache: MarketDataCache
    ledger: Ledger
    order_manager: OrderManager
    execution_engine: ExecutionEngine
    margin_engine: MarginEngine
    history: HistoryStore
    event_seq: int = 0
    status: SessionStatus = SessionStatus.RUNNING
    run_id: str | None = None

    def next_event_id(self) -> str:
        self.event_seq += 1
        return f"evt_{self.event_seq:06d}"


class SessionService:
    """Orchestrates session lifecycle and step execution."""

    def __init__(self, upq_client: UPQClient):
        self._sessions: dict[str, SessionState] = {}
        self._upq = upq_client

    async def create_session(
        self, req: CreateSessionRequest, account: Account
    ) -> tuple[str, ClockState]:
        """Create a session: prefetch data from UPQ, build domain objects."""
        session_id = f"sess_{uuid.uuid4().hex[:8]}"

        cache = MarketDataCache()

        # Prefetch stock data
        if req.universe.stocks:
            if req.frequency == Frequency.MINUTE:
                bars = await self._upq.get_stock_minute_bars(
                    req.universe.stocks, req.start_ts, req.end_ts
                )
            else:
                start_date = req.start_ts[:10]
                end_date = req.end_ts[:10]
                bars = await self._upq.get_stock_daily_bars(
                    req.universe.stocks, start_date, end_date
                )
            for bar in bars:
                if bar.symbol not in cache._stock_bars:
                    cache.load_stock_bars(bar.symbol, [])
                cache._stock_bars.setdefault(bar.symbol, {})[bar.window_start_ns] = bar
            cache._rebuild_timestamps()

        # Prefetch option data
        if req.universe.options:
            for contract in req.universe.options:
                if req.frequency == Frequency.MINUTE:
                    opt_bars = await self._upq.get_option_minute_bars(
                        contract, req.start_ts, req.end_ts
                    )
                else:
                    start_date = req.start_ts[:10]
                    end_date = req.end_ts[:10]
                    opt_bars = await self._upq.get_option_daily_bars(
                        contract, start_date, end_date
                    )
                cache.load_option_bars(contract, opt_bars)

        # For daily sessions, patch bar.open with 15:50 ET minute bar open price
        # to eliminate look-ahead bias (MARKET orders fill at bar.open).
        if req.frequency == Frequency.DAILY:
            await self._patch_daily_open_with_minute_price(req, cache)

        timestamps = cache.get_all_timestamps()
        clock = SessionClock(timestamps, req.frequency, req.end_ts)

        exec_config = req.execution_config or ExecutionConfig()
        repro = req.reproducibility

        state = SessionState(
            session_id=session_id,
            account_id=req.account_id,
            config=req,
            clock=clock,
            cache=cache,
            ledger=Ledger(account.initial_cash),
            order_manager=OrderManager(),
            execution_engine=ExecutionEngine(
                seed=repro.seed if repro else None,
                slippage_bps=exec_config.slippage_bps,
                fee_model=exec_config.fee_model,
                option_spread_pct=exec_config.option_spread_pct,
            ),
            margin_engine=MarginEngine(account.margin_config),
            history=HistoryStore(),
            run_id=repro.run_id if repro else None,
        )

        self._sessions[session_id] = state

        clock_state = ClockState(
            frequency=req.frequency,
            current_ts=clock.current_ts,
            end_ts=req.end_ts,
            status=SessionStatus.RUNNING,
        )

        return session_id, clock_state

    def step(self, session_id: str, n: int = 1) -> dict:
        """Advance clock by n ticks and return events."""
        state = self._sessions.get(session_id)
        if state is None:
            return {"ok": False, "error": "session not found"}
        if state.status != SessionStatus.RUNNING:
            return {"ok": False, "error": "session not running"}

        all_events: list[dict] = []

        traversed = state.clock.step(n)
        if not traversed:
            state.status = SessionStatus.FINISHED
            return {
                "ok": True,
                "session_id": session_id,
                "clock": self._clock_state(state),
                "events": [],
            }

        for ts_ns in traversed:
            ts = ns_to_iso(ts_ns)
            tick_events = self._process_tick(state, ts_ns, ts)
            all_events.extend(tick_events)

        if state.clock.is_done:
            state.status = SessionStatus.FINISHED

        prev_ts = state.clock.prev_ts
        return {
            "ok": True,
            "session_id": session_id,
            "clock": {
                "prev_ts": prev_ts,
                "current_ts": state.clock.current_ts,
                "frequency": state.clock.frequency.value,
                "status": state.status.value,
            },
            "events": all_events,
        }

    def _process_tick(
        self, state: SessionState, ts_ns: int, ts: str
    ) -> list[dict]:
        """Process a single tick: market data, execution, snapshots."""
        events: list[dict] = []

        # 1. Market tick
        stock_bars = state.cache.get_stock_bars_at(ts_ns)
        option_bars = state.cache.get_option_bars_at(ts_ns)

        stocks_payload = []
        for sym, bar in stock_bars.items():
            stocks_payload.append(
                {
                    "symbol": sym,
                    "window_start_ns": bar.window_start_ns,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
            )

        options_payload = []
        for contract, bar in option_bars.items():
            opt_entry = {
                "contract": contract,
                "window_start_ns": bar.window_start_ns,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            if bar.iv is not None:
                opt_entry["iv"] = bar.iv
            if bar.delta is not None:
                opt_entry["delta"] = bar.delta
            if bar.gamma is not None:
                opt_entry["gamma"] = bar.gamma
            if bar.theta is not None:
                opt_entry["theta"] = bar.theta
            if bar.vega is not None:
                opt_entry["vega"] = bar.vega
            if bar.rho is not None:
                opt_entry["rho"] = bar.rho
            if bar.greek_status is not None:
                opt_entry["greek_status"] = bar.greek_status
            options_payload.append(opt_entry)

        market_event = EventEnvelope(
            event_id=state.next_event_id(),
            ts=ts,
            type=EventType.MARKET_TICK,
            payload=MarketTickPayload(
                frequency=state.clock.frequency.value,
                stocks=stocks_payload,
                options=options_payload,
            ).model_dump(),
        )
        events.append(market_event.model_dump())
        state.history.append_event(market_event)

        # 2. Update market prices in ledger
        prices = state.cache.get_prices_at(ts_ns)
        state.ledger.update_market_prices(prices)

        # 2b. Option expiry lifecycle check — only at the last bar of the expiry date.
        # For DAILY sessions every bar is EOD, so this always fires.
        # For MINUTE sessions this fires only at the last intraday bar (e.g. 15:59/16:00),
        # not at 09:31, so the full day of option mark-to-market is preserved.
        current_date = ts[:10]  # "YYYY-MM-DD"
        is_eod = state.clock.is_last_bar_of_date(ts_ns)

        if is_eod:
            underlying_prices = {sym: bar.close for sym, bar in stock_bars.items()}
            expiry_actions = check_option_expiries(
                state.ledger.positions,
                current_date,
                underlying_prices,
            )
            if expiry_actions:
                expiry_events = state.execution_engine.process_expiries(
                    ts,
                    expiry_actions,
                    state.ledger,
                    state.order_manager,
                    state.margin_engine,
                )
                for evt in expiry_events:
                    events.append(evt.model_dump())
                    state.history.append_event(evt)

        # 3. Cancel open orders on contracts expiring today before execution.
        # Orders on expired contracts must not fill — they are cancelled at EOD
        # before the execution engine processes them.
        if is_eod:
            expiring = get_expiring_contracts(
                current_date,
                list({
                    iid[len("OPTION:"):] for iid in state.ledger.positions
                    if iid.startswith("OPTION:")
                } | {
                    o.instrument_id[len("OPTION:"):] for o in state.order_manager.get_open_orders()
                    if o.instrument_id.startswith("OPTION:")
                }),
            )
            for order in state.order_manager.get_open_orders():
                if not order.instrument_id.startswith("OPTION:"):
                    continue
                contract = order.instrument_id[len("OPTION:"):]
                if contract in expiring:
                    state.order_manager.cancel(order.order_id, ts)
                    state.history.update_order(order)

        # 4. Execution: process open orders (expired-contract orders already cancelled above)
        exec_events, trades = state.execution_engine.process_step(
            ts=ts,
            ts_ns=ts_ns,
            stock_bars=stock_bars,
            option_bars=option_bars,
            order_manager=state.order_manager,
            ledger=state.ledger,
            margin_engine=state.margin_engine,
        )

        for evt in exec_events:
            events.append(evt.model_dump())
            state.history.append_event(evt)

        for trade in trades:
            state.history.record_trade(trade)

        # Update order history
        for order in state.order_manager.get_all_orders():
            state.history.update_order(order)

        # 4b. Re-mark positions created/modified by fills to bar close
        if trades:
            state.ledger.update_market_prices(prices)

        # 4. Account snapshot
        im = state.margin_engine.total_initial_margin(state.ledger.positions)
        mm = state.margin_engine.total_maintenance_margin(state.ledger.positions)

        open_orders_data = [
            {
                "order_id": o.order_id,
                "instrument_id": o.instrument_id,
                "side": o.side.value,
                "order_type": o.order_type.value,
                "qty": o.qty,
                "limit_price": o.limit_price,
                "status": o.status.value,
            }
            for o in state.order_manager.get_open_orders()
        ]

        snapshot = state.ledger.get_snapshot(
            initial_margin_req=im,
            maintenance_margin_req=mm,
            margin_status=state.margin_engine.margin_status,
            open_orders=open_orders_data,
        )

        snapshot_event = EventEnvelope(
            event_id=state.next_event_id(),
            ts=ts,
            type=EventType.ACCOUNT_SNAPSHOT,
            payload=snapshot.model_dump(),
        )
        events.append(snapshot_event.model_dump())
        state.history.append_event(snapshot_event)
        state.history.record_snapshot(ts, snapshot)
        state.history.record_equity_point(ts, state.ledger.total_equity())

        # 5. Risk check
        risk = state.margin_engine.check_maintenance(
            state.ledger.total_equity(), state.ledger.positions
        )
        if risk is not None:
            risk_event = EventEnvelope(
                event_id=state.next_event_id(),
                ts=ts,
                type=EventType.RISK_EVENT,
                payload=risk.model_dump(),
            )
            events.append(risk_event.model_dump())
            state.history.append_event(risk_event)

        return events

    def stop_session(self, session_id: str) -> bool:
        state = self._sessions.get(session_id)
        if state is None:
            return False
        state.status = SessionStatus.STOPPED
        return True

    def get_session(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def get_summary(self, session_id: str) -> SessionSummary | None:
        state = self._sessions.get(session_id)
        if state is None:
            return None

        equity_curve = state.history.get_equity_curve()
        initial_equity = state.ledger.initial_cash
        final_equity = state.ledger.total_equity()
        total_return = (final_equity - initial_equity) / initial_equity if initial_equity else 0.0

        # Max drawdown
        max_dd = 0.0
        peak = initial_equity
        for pt in equity_curve:
            eq = pt["equity"]
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        all_orders = state.order_manager.get_all_orders()
        num_orders = len(all_orders)
        num_rejected = sum(1 for o in all_orders if o.status.value == "REJECTED")
        reject_rate = num_rejected / num_orders if num_orders > 0 else 0.0

        trades = state.history.get_trades(session_id=session_id)

        return SessionSummary(
            session_id=session_id,
            run_id=state.run_id,
            start_ts=state.config.start_ts,
            end_ts=state.config.end_ts,
            final_equity=round(final_equity, 2),
            total_return=round(total_return, 6),
            max_drawdown=round(max_dd, 6),
            fees_paid=round(state.ledger.total_fees, 2),
            num_orders=num_orders,
            num_trades=len(trades),
            reject_rate=round(reject_rate, 4),
            margin_call_count=state.margin_engine.margin_call_count,
        )

    def _clock_state(self, state: SessionState) -> dict:
        return {
            "frequency": state.clock.frequency.value,
            "current_ts": state.clock.current_ts,
            "end_ts": state.clock.end_ts,
            "status": state.status.value,
        }

    async def _patch_daily_open_with_minute_price(
        self, req: CreateSessionRequest, cache: MarketDataCache
    ) -> None:
        """Replace daily bar.open with 15:50 ET minute bar open to fix look-ahead bias.

        Fallback chain: 15:50 bar → latest bar in 15:40-15:49 → daily bar close.
        """
        from zoneinfo import ZoneInfo

        ET = ZoneInfo("America/New_York")

        # --- Patch stock bars ---
        for symbol, daily_bars_by_ns in cache._stock_bars.items():
            dates = set()
            for ns in daily_bars_by_ns:
                dt_utc = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
                dates.add(dt_utc.strftime("%Y-%m-%d"))

            if not dates:
                continue

            min_date = min(dates)
            max_date = max(dates)
            # Query 19:40-20:51 UTC to cover both EDT and EST
            start_ts = f"{min_date}T19:40:00+00:00"
            end_ts = f"{max_date}T20:51:00+00:00"

            try:
                minute_bars = await self._upq.get_stock_minute_bars(
                    [symbol], start_ts, end_ts
                )
            except Exception:
                logger.warning("Failed to fetch minute bars for %s, skipping patch", symbol)
                continue

            # Group minute bars by date
            minute_by_date: dict[str, list] = {}
            for mb in minute_bars:
                dt_utc = datetime.fromtimestamp(mb.window_start_ns / 1e9, tz=timezone.utc)
                date_key = dt_utc.strftime("%Y-%m-%d")
                minute_by_date.setdefault(date_key, []).append(mb)

            patched = 0
            for ns, daily_bar in daily_bars_by_ns.items():
                dt_utc = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
                date_key = dt_utc.strftime("%Y-%m-%d")

                bars_for_day = minute_by_date.get(date_key, [])
                patch_price = self._pick_near_close_price(bars_for_day, ET)

                if patch_price is not None:
                    daily_bar.open = patch_price
                    patched += 1
                else:
                    daily_bar.open = daily_bar.close

            logger.debug("Patched %d/%d daily bars for %s", patched, len(daily_bars_by_ns), symbol)

        # --- Patch option bars ---
        for contract, daily_bars_by_ns in cache._option_bars.items():
            dates = set()
            for ns in daily_bars_by_ns:
                dt_utc = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
                dates.add(dt_utc.strftime("%Y-%m-%d"))

            if not dates:
                continue

            min_date = min(dates)
            max_date = max(dates)
            start_ts = f"{min_date}T19:40:00+00:00"
            end_ts = f"{max_date}T20:51:00+00:00"

            try:
                minute_bars = await self._upq.get_option_minute_bars(
                    contract, start_ts, end_ts
                )
            except Exception:
                logger.warning("Failed to fetch minute bars for %s, skipping patch", contract)
                continue

            minute_by_date: dict[str, list] = {}
            for mb in minute_bars:
                dt_utc = datetime.fromtimestamp(mb.window_start_ns / 1e9, tz=timezone.utc)
                date_key = dt_utc.strftime("%Y-%m-%d")
                minute_by_date.setdefault(date_key, []).append(mb)

            for ns, daily_bar in daily_bars_by_ns.items():
                dt_utc = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
                date_key = dt_utc.strftime("%Y-%m-%d")

                bars_for_day = minute_by_date.get(date_key, [])
                patch_price = self._pick_near_close_price(bars_for_day, ET)

                if patch_price is not None:
                    daily_bar.open = patch_price
                else:
                    daily_bar.open = daily_bar.close

    @staticmethod
    def _pick_near_close_price(minute_bars: list, et_tz) -> float | None:
        """Pick best minute bar open price from the 15:40-15:50 ET window.

        Priority: 15:50 bar → latest bar in 15:40-15:49 window.
        Returns None if no bars in the window.
        """
        if not minute_bars:
            return None

        target_bar = None
        best_fallback = None
        best_fallback_ns = -1

        for bar in minute_bars:
            dt_utc = datetime.fromtimestamp(bar.window_start_ns / 1e9, tz=timezone.utc)
            dt_et = dt_utc.astimezone(et_tz)

            if dt_et.hour == 15 and dt_et.minute == 50:
                target_bar = bar
                break

            if dt_et.hour == 15 and 40 <= dt_et.minute <= 49:
                if bar.window_start_ns > best_fallback_ns:
                    best_fallback = bar
                    best_fallback_ns = bar.window_start_ns

        if target_bar is not None:
            return target_bar.open
        if best_fallback is not None:
            return best_fallback.open
        return None
