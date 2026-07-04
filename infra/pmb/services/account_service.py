import random
from datetime import datetime, timedelta, timezone

from models.enums import Market, AccountStatus, Side, MARKET_PROFILE
from models.account import (
    Account,
    CreateAccountRequest,
    MarginConfig,
    AccountConstraints,
    BrokerPosition,
    BrokerFill,
    TradingDayRecord,
)

# Per-share commission applied to every fill. Kept at 0 by default so paper P&L
# is clean; bump this to model a brokerage commission.
DEFAULT_FEE_PER_SHARE = 0.0

# Fallback open date when a caller allocates an account without one.
DEFAULT_OPEN_DATE = "2024-01-02"


class FrozenAccountError(Exception):
    """Raised when a trade is attempted on a frozen (day-closed) account."""


class AccountClosedError(Exception):
    """Raised when an operation is attempted on a permanently closed account."""


class AccountService:
    """Manages 10-digit broker accounts and their day-gated trading book.

    An account is allocated with a market (cn/us/hk) and a unique 10-digit id.
    Agents trade against it during a trading day, then call ``end_day`` which
    freezes the account; trading is rejected until ``next_day`` advances the
    simulated calendar. Every closed day is appended to the account's history,
    giving a step-by-step trading record queryable by the account id alone.
    """

    def __init__(self, fee_per_share: float = DEFAULT_FEE_PER_SHARE,
                 buying_power_multiplier: float = 2.0):
        self._accounts: dict[str, Account] = {}
        self._fee_per_share = fee_per_share
        self._bp_mult = buying_power_multiplier

    # ── Allocation ────────────────────────────────────────────────────

    def _new_account_id(self, market: Market) -> str:
        """A unique 10-digit account number whose leading digit encodes market."""
        lead = MARKET_PROFILE[market]["lead_digit"]
        for _ in range(10_000):
            tail = "".join(str(random.randint(0, 9)) for _ in range(9))
            candidate = lead + tail
            if candidate not in self._accounts:
                return candidate
        raise RuntimeError("could not allocate a unique account id")

    def create_account(self, req: CreateAccountRequest) -> Account:
        market = req.market
        profile = MARKET_PROFILE[market]
        account_id = self._new_account_id(market)
        now = datetime.now(timezone.utc).isoformat()
        open_date = req.resolved_open_date() or DEFAULT_OPEN_DATE

        account = Account(
            account_id=account_id,
            base_currency=req.base_currency or profile["currency"],
            account_type=req.account_type,
            market=market,
            initial_cash=req.initial_cash,
            timezone=req.timezone or profile["timezone"],
            open_date=open_date,
            start_date=open_date,
            created_at=now,
            constraints=req.constraints or AccountConstraints(),
            margin_config=req.margin_config or MarginConfig(),
            status=AccountStatus.ACTIVE,
            trading_day=1,
            current_date=open_date,
            cash=req.initial_cash,
            day_opening_equity=req.initial_cash,
        )
        self._accounts[account_id] = account
        return account

    def get_account(self, account_id: str) -> Account | None:
        return self._accounts.get(account_id)

    def list_accounts(self) -> list[Account]:
        return list(self._accounts.values())

    # ── Trading ───────────────────────────────────────────────────────

    def trade(
        self,
        account_id: str,
        symbol: str,
        side: Side,
        qty: int,
        price: float,
        note: str | None = None,
    ) -> BrokerFill:
        account = self._require_open(account_id)
        if account.status == AccountStatus.FROZEN:
            raise FrozenAccountError(
                "account is frozen for the day; call next_day to continue trading"
            )
        if qty <= 0:
            raise ValueError("qty must be positive")
        if price is None or price <= 0:
            raise ValueError("a positive execution price is required")

        symbol = symbol.upper()
        fees = round(qty * self._fee_per_share, 4)
        realized = self._apply_fill(account, symbol, side, qty, price, fees)

        account.trade_seq += 1
        fill = BrokerFill(
            trade_id=f"{account_id}-T{account.trade_seq:05d}",
            trading_day=account.trading_day,
            date=account.current_date,
            symbol=symbol,
            side=side,
            qty=qty,
            price=round(price, 4),
            gross=round(qty * price, 2),
            fees=fees,
            realized_pnl=round(realized, 2),
            note=note,
        )
        account.trades_today.append(fill)
        return fill

    def _apply_fill(
        self, account: Account, symbol: str, side: Side, qty: int, price: float, fees: float
    ) -> float:
        pos = account.positions.get(symbol)
        if pos is None:
            pos = BrokerPosition(symbol=symbol)
            account.positions[symbol] = pos

        realized = 0.0
        if side == Side.BUY:
            account.cash -= qty * price + fees
            if pos.qty >= 0:
                new_qty = pos.qty + qty
                pos.avg_price = (
                    (pos.avg_price * pos.qty + price * qty) / new_qty if new_qty else price
                )
                pos.qty = new_qty
            else:  # covering an existing short
                cover = min(qty, -pos.qty)
                realized = cover * (pos.avg_price - price)
                pos.qty += qty
                if pos.qty > 0:  # flipped to long
                    pos.avg_price = price
        else:  # SELL
            account.cash += qty * price - fees
            if pos.qty <= 0:
                absq = -pos.qty
                new_abs = absq + qty
                pos.avg_price = (
                    (pos.avg_price * absq + price * qty) / new_abs if new_abs else price
                )
                pos.qty = -new_abs
            else:  # closing a long
                close = min(qty, pos.qty)
                realized = close * (price - pos.avg_price)
                pos.qty -= qty
                if pos.qty < 0:  # flipped to short
                    pos.avg_price = price

        pos.last_price = price
        if pos.qty == 0:
            account.positions.pop(symbol, None)

        account.realized_pnl += realized
        account.fees_paid += fees
        return realized

    def mark_prices(self, account_id: str, prices: dict[str, float]) -> None:
        """Update last_price on held positions (mark-to-market)."""
        account = self._accounts.get(account_id)
        if account is None:
            return
        for symbol, px in prices.items():
            pos = account.positions.get(symbol.upper())
            if pos is not None and px:
                pos.last_price = px

    # ── Day gating ────────────────────────────────────────────────────

    def end_day(self, account_id: str) -> TradingDayRecord:
        """Close the current trading day and freeze the account."""
        account = self._require_open(account_id)
        if account.status == AccountStatus.FROZEN:
            # idempotent: return the already-recorded day
            return account.history[-1]

        closing_equity = account.equity()
        day_realized = round(
            sum(t.realized_pnl for t in account.trades_today), 2
        )
        day_fees = round(sum(t.fees for t in account.trades_today), 2)
        record = TradingDayRecord(
            trading_day=account.trading_day,
            date=account.current_date,
            opening_equity=round(account.day_opening_equity, 2),
            closing_equity=round(closing_equity, 2),
            realized_pnl=day_realized,
            cash=round(account.cash, 2),
            num_trades=len(account.trades_today),
            fees=day_fees,
            trades=list(account.trades_today),
            positions=[p.to_view() for p in account.open_positions()],
            closed_at=datetime.now(timezone.utc).isoformat(),
        )
        account.history.append(record)
        account.status = AccountStatus.FROZEN
        return record

    def next_day(self, account_id: str, date: str | None = None) -> Account:
        """Unfreeze the account and advance to the next trading day."""
        account = self._require_open(account_id)
        if account.status == AccountStatus.ACTIVE:
            # Auto-close the open day first so history stays contiguous.
            self.end_day(account_id)

        account.current_date = date or self._next_weekday(account.current_date)
        account.trading_day += 1
        account.trades_today = []
        account.day_opening_equity = account.equity()
        account.status = AccountStatus.ACTIVE
        return account

    def close_account(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(account_id)
        if account.status == AccountStatus.ACTIVE:
            self.end_day(account_id)
        account.status = AccountStatus.CLOSED
        return account

    @staticmethod
    def _next_weekday(date_str: str) -> str:
        try:
            d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            d = datetime.now(timezone.utc).date()
        d += timedelta(days=1)
        while d.weekday() >= 5:  # skip Saturday/Sunday
            d += timedelta(days=1)
        return d.isoformat()

    def _require_open(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise KeyError(account_id)
        if account.status == AccountStatus.CLOSED:
            raise AccountClosedError(account_id)
        return account

    # ── Views ─────────────────────────────────────────────────────────

    def status_view(self, account_id: str) -> dict | None:
        account = self._accounts.get(account_id)
        if account is None:
            return None
        equity = account.equity()
        unrealized = round(
            sum(p.unrealized_pnl() for p in account.open_positions()), 2
        )
        return {
            "account_id": account.account_id,
            "market": account.market.value,
            "base_currency": account.base_currency,
            "account_type": account.account_type,
            "status": account.status.value,
            "frozen": account.status == AccountStatus.FROZEN,
            "can_trade": account.status == AccountStatus.ACTIVE,
            # session-snapshot alias preserved for back-compat readers
            "margin_status": "NORMAL",
            "open_date": account.open_date,
            "current_date": account.current_date,
            "trading_day": account.trading_day,
            "created_at": account.created_at,
            "timezone": account.timezone,
            "initial_cash": round(account.initial_cash, 2),
            "cash": round(account.cash, 2),
            # cash_available / equity mirror the session-snapshot field names so
            # existing agent code reading those keys keeps working.
            "cash_available": round(account.cash, 2),
            "equity": round(equity, 2),
            "buying_power": round(max(0.0, equity * self._bp_mult), 2),
            "realized_pnl": round(account.realized_pnl, 2),
            "unrealized_pnl": unrealized,
            "total_pnl": round(equity - account.initial_cash, 2),
            "total_return": round(
                (equity - account.initial_cash) / account.initial_cash, 6
            )
            if account.initial_cash
            else 0.0,
            "fees_paid": round(account.fees_paid, 2),
            "day_opening_equity": round(account.day_opening_equity, 2),
            "day_pnl": round(equity - account.day_opening_equity, 2),
            "num_positions": len(account.open_positions()),
            "positions": [p.to_view() for p in account.open_positions()],
            "num_trades_today": len(account.trades_today),
            "trades_today": [t.model_dump() for t in account.trades_today],
            "history_days": len(account.history),
        }

    def history_view(self, account_id: str, limit: int | None = None) -> list[dict] | None:
        account = self._accounts.get(account_id)
        if account is None:
            return None
        records = account.history
        if limit:
            records = records[-limit:]
        return [r.model_dump() for r in records]
