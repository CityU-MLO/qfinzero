"""
PMB Client — Python client for the Paper Money Broker REST API.

Usage:
    from qfinzero.clients.pmb import PMBClient

    with PMBClient() as pmb:
        acct = pmb.create_account(initial_cash=50000.0, start_date="2025-01-06")
        sess = pmb.create_session(
            account_id=acct["account_id"],
            frequency="1d",
            start_ts="2025-01-06",
            end_ts="2025-01-31",
            universe={"stocks": ["AAPL"]},
        )
        while True:
            result = pmb.step(sess["session_id"])
            if not result.is_running:
                break
            price = result.get_stock_price("AAPL")
            pmb.buy(sess["session_id"], acct["account_id"], "AAPL", 10)
"""

import requests
from typing import Optional

from qfinzero.config import PMB_URL


class PMBError(Exception):
    """Error from PMB API."""

    def __init__(self, message: str, status_code: int = None, response: dict = None):
        self.status_code = status_code
        self.response = response or {}
        super().__init__(message)


class StepResult:
    """Wrapper around the step response for convenient event access."""

    def __init__(self, data: dict):
        self.ok = data.get("ok", False)
        self.clock = data.get("clock", {})
        self.events = data.get("events", [])
        self.session_id = data.get("session_id")
        self._raw = data

    @property
    def is_running(self) -> bool:
        return self.ok and self.clock.get("status") == "RUNNING"

    @property
    def current_ts(self) -> str:
        return self.clock.get("current_ts", "")

    @property
    def status(self) -> str:
        return self.clock.get("status", "")

    def get_event(self, event_type: str) -> Optional[dict]:
        """Get first event of given type, or None."""
        for e in self.events:
            if e.get("type") == event_type:
                return e.get("payload")
        return None

    def get_market_tick(self) -> Optional[dict]:
        """Get MARKET_TICK payload: {"stocks": [...], "options": [...]}."""
        return self.get_event("MARKET_TICK")

    def get_snapshot(self) -> Optional[dict]:
        """Get ACCOUNT_SNAPSHOT payload."""
        return self.get_event("ACCOUNT_SNAPSHOT")

    def get_stock_price(self, symbol: str) -> Optional[float]:
        """Get close price of a stock from MARKET_TICK."""
        tick = self.get_market_tick()
        if not tick:
            return None
        for bar in tick.get("stocks", []):
            if bar.get("symbol") == symbol:
                return bar.get("close")
        return None

    def get_stock_bar(self, symbol: str) -> Optional[dict]:
        """Get full bar (open/high/low/close/volume) for a stock."""
        tick = self.get_market_tick()
        if not tick:
            return None
        for bar in tick.get("stocks", []):
            if bar.get("symbol") == symbol:
                return bar
        return None


class PMBClient:
    """Synchronous client for the Paper Money Broker REST API."""

    DEFAULT_URL = PMB_URL

    def __init__(self, base_url: str = None, timeout: int = 30, headers: dict = None):
        self.base_url = (base_url or self.DEFAULT_URL).rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        if headers:   # e.g. the hub identity (x-qfz-user / x-qfz-role) to scope accounts
            self._session.headers.update(headers)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._session.close()

    # ── HTTP helpers ──────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self.base_url}/v1{path}"

    def _get(self, path: str, params: dict = None) -> dict:
        resp = self._session.get(self._url(path), params=params, timeout=self.timeout)
        return self._handle(resp)

    def _post(self, path: str, json: dict = None) -> dict:
        resp = self._session.post(self._url(path), json=json, timeout=self.timeout)
        return self._handle(resp)

    def _put(self, path: str, json: dict = None) -> dict:
        resp = self._session.put(self._url(path), json=json, timeout=self.timeout)
        return self._handle(resp)

    def _handle(self, resp: requests.Response) -> dict:
        try:
            data = resp.json()
        except Exception:
            raise PMBError(f"Non-JSON response: {resp.status_code} {resp.text[:200]}", resp.status_code)
        if resp.status_code >= 400:
            msg = data.get("message") or data.get("detail") or str(data)
            raise PMBError(msg, resp.status_code, data)
        return data

    # ── Health ────────────────────────────────────────────────────

    def health(self) -> dict:
        return self._get("/health")

    # ── Account ───────────────────────────────────────────────────

    def create_account(
        self,
        initial_cash: float = None,
        account_type: str = "MARGIN",
        market: str = None,
        start_date: str = None,
        open_date: str = None,
        margin_config: dict = None,
        **kwargs,
    ) -> dict:
        """Allocate a broker account. Returns a 10-digit account id under
        ``account_id`` plus the initial broker status under ``account``.

        ``initial_cash`` / ``market`` default to the broker config (see
        ``get_config``) when omitted. ``market`` is one of "us", "cn", "hk".
        """
        body = {"account_type": account_type, **kwargs}
        if initial_cash is not None:
            body["initial_cash"] = initial_cash
        if market is not None:
            body["market"] = market
        # open_date is the canonical field; start_date kept for back-compat.
        if open_date:
            body["open_date"] = open_date
        if start_date:
            body["start_date"] = start_date
        if margin_config:
            body["margin_config"] = margin_config
        return self._post("/accounts", body)

    # ``allocate`` reads more naturally for agents allocating a fresh account.
    allocate = create_account

    def get_account(self, account_id: str) -> dict:
        return self._get(f"/accounts/{account_id}")

    # ── Broker (day-gated account book) ───────────────────────────

    def get_status(self, account_id: str) -> dict:
        """Canonical broker status: balances, P&L, positions, day-gate state."""
        return self._get(f"/accounts/{account_id}/status")

    def get_history(self, account_id: str, limit: int = None) -> list:
        """Step-by-step trading history (one record per closed trading day)."""
        params = {"limit": limit} if limit else None
        data = self._get(f"/accounts/{account_id}/history", params=params)
        return data.get("days", [])

    def trade(
        self,
        account_id: str,
        symbol: str,
        side: str,
        qty: int,
        price: float = None,
        note: str = None,
    ) -> dict:
        """Execute an immediate paper fill against the broker book.

        Omit ``price`` to fill at the real UPQ market price for the account's
        current trading day (recommended for agents).
        """
        body = {"symbol": symbol, "side": side, "qty": qty}
        if price is not None:
            body["price"] = price
        if note:
            body["note"] = note
        return self._post(f"/accounts/{account_id}/trade", body)

    def broker_buy(self, account_id: str, symbol: str, qty: int, price: float = None, note: str = None) -> dict:
        return self.trade(account_id, symbol, "BUY", qty, price, note)

    def broker_sell(self, account_id: str, symbol: str, qty: int, price: float = None, note: str = None) -> dict:
        return self.trade(account_id, symbol, "SELL", qty, price, note)

    def quote(self, account_id: str, symbols) -> dict:
        """Real UPQ prices for symbols at the account's current trading day."""
        if isinstance(symbols, (list, tuple)):
            symbols = ",".join(symbols)
        return self._get(f"/accounts/{account_id}/quote", {"symbols": symbols})

    # ── Broker settings ───────────────────────────────────────────

    def get_config(self) -> dict:
        """Broker settings (fees, slippage, leverage, pricing rule, defaults)."""
        return self._get("/config")

    def put_config(self, patch: dict) -> dict:
        """Update broker settings; applies live."""
        return self._put("/config", patch)

    def end_day(self, account_id: str) -> dict:
        """Close the current trading day and freeze the account."""
        return self._post(f"/accounts/{account_id}/end_day", {})

    def next_day(self, account_id: str, date: str = None) -> dict:
        """Unfreeze and advance to the next trading day."""
        body = {"date": date} if date else {}
        return self._post(f"/accounts/{account_id}/next_day", body)

    def close_account(self, account_id: str) -> dict:
        return self._post(f"/accounts/{account_id}/close", {})

    def get_positions(self, account_id: str) -> list:
        data = self._get(f"/accounts/{account_id}/positions")
        return data.get("positions", [])

    def get_orders(self, account_id: str, session_id: str = None) -> list:
        params = {}
        if session_id:
            params["session_id"] = session_id
        data = self._get(f"/accounts/{account_id}/orders", params=params)
        return data.get("orders", [])

    def get_trades(self, account_id: str, session_id: str = None) -> list:
        params = {}
        if session_id:
            params["session_id"] = session_id
        data = self._get(f"/accounts/{account_id}/trades", params=params)
        return data.get("trades", [])

    # ── Session ───────────────────────────────────────────────────

    def create_session(
        self,
        account_id: str,
        frequency: str,
        start_ts: str,
        end_ts: str,
        universe: dict,
        execution_config: dict = None,
        reproducibility: dict = None,
        **kwargs,
    ) -> dict:
        body = {
            "account_id": account_id,
            "frequency": frequency,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "universe": universe,
            **kwargs,
        }
        if execution_config:
            body["execution_config"] = execution_config
        if reproducibility:
            body["reproducibility"] = reproducibility
        return self._post("/sessions", body)

    def step(self, session_id: str, n: int = 1) -> StepResult:
        data = self._post(f"/sessions/{session_id}/step", {"step": n})
        return StepResult(data)

    def step_until(
        self,
        session_id: str,
        until_ts: str = None,
        max_steps: int = 390,
        stop_on_fill: bool = True,
        price_triggers: list = None,
        stop_on_segment: str = None,
    ) -> dict:
        """Advance until a condition holds instead of one bar at a time.

        Stops at the first of: ``until_ts`` reached, ``max_steps`` bars, a fill
        (``stop_on_fill``), a price trigger such as
        ``{"symbol": "SPY", "op": ">=", "price": 500}``, or entering segment
        ``stop_on_segment`` (REGULAR / PRE / POST / OVERNIGHT). Market ticks are
        summarized to the last bar so the response stays small.
        """
        body = {"max_steps": max_steps, "stop_on_fill": stop_on_fill}
        if until_ts:
            body["until_ts"] = until_ts
        if price_triggers:
            body["price_triggers"] = price_triggers
        if stop_on_segment:
            body["stop_on_segment"] = stop_on_segment
        return self._post(f"/sessions/{session_id}/step_until", body)

    def stop_session(self, session_id: str) -> dict:
        return self._post(f"/sessions/{session_id}/stop")

    def get_summary(self, session_id: str) -> dict:
        return self._get(f"/sessions/{session_id}/summary")

    def export(self, session_id: str, fmt: str = "json") -> any:
        resp = self._session.get(
            self._url(f"/sessions/{session_id}/export"),
            params={"format": fmt},
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            return self._handle(resp)
        if fmt == "csv":
            return resp.text
        return resp.json()

    def get_market(self, session_id: str) -> dict:
        return self._get(f"/sessions/{session_id}/market")

    def get_session_state(self, session_id: str) -> dict:
        """Consolidated snapshot: clock, account, positions, open orders, market."""
        return self._get(f"/sessions/{session_id}/state")

    def get_timeline(self, session_id: str) -> dict:
        """The full list of bar timestamps — the scrubbable simulation clock."""
        return self._get(f"/sessions/{session_id}/timeline")

    def rewind(self, session_id: str, target_ts: str) -> dict:
        """Time-travel back to target_ts, undoing every order placed after it."""
        return self._post(f"/sessions/{session_id}/rewind", {"target_ts": target_ts})

    def checkpoint(self, session_id: str) -> dict:
        """Export account and deterministic state for an experiment branch."""
        return self._get(f"/sessions/{session_id}/checkpoint")

    export_checkpoint = checkpoint

    def restore_checkpoint(self, checkpoint: dict, account: dict = None) -> dict:
        """Restore a checkpoint into a new account and independent session.

        ``checkpoint`` may be the full response from :meth:`checkpoint`, or the
        nested checkpoint object when ``account`` is passed separately.
        """
        body = checkpoint if account is None else {
            "account": account,
            "checkpoint": checkpoint,
        }
        return self._post("/sessions/restore", body)

    def add_stocks(self, session_id: str, symbols: list) -> dict:
        """Add stock symbols to a running session (grow the watchlist/universe)."""
        return self._post(f"/sessions/{session_id}/add_stocks", {"symbols": symbols})

    def add_contracts(self, session_id: str, contracts: list) -> dict:
        """Load option contracts into a running session so they can be traded."""
        return self._post(f"/sessions/{session_id}/add_contracts", {"contracts": contracts})

    def add_futures(self, session_id: str, symbols: list) -> dict:
        """Load futures (contracts such as ZNZ6, or front-month roots such as ZN)."""
        return self._post(f"/sessions/{session_id}/add_futures", {"symbols": symbols})

    # ── Order helpers ─────────────────────────────────────────────

    def _place_order(
        self,
        session_id: str,
        account_id: str,
        instrument: dict,
        side: str,
        qty: int,
        order_type: str = "MARKET",
        limit_price: float = None,
        stop_price: float = None,
        time_in_force: str = "DAY",
        client_order_id: str = None,
        trading_hours: str = "REGULAR",
        expire_ts: str = None,
    ) -> dict:
        order_spec = {
            "instrument": instrument,
            "side": side,
            "order_type": order_type,
            "qty": qty,
            "time_in_force": time_in_force,
            "trading_hours": trading_hours,
        }
        if expire_ts:
            order_spec["expire_ts"] = expire_ts
        if limit_price is not None:
            order_spec["limit_price"] = limit_price
        if stop_price is not None:
            order_spec["stop_price"] = stop_price

        body = {
            "session_id": session_id,
            "account_id": account_id,
            "order": order_spec,
        }
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._post("/orders", body)

    def buy(
        self,
        session_id: str,
        account_id: str,
        symbol: str,
        qty: int,
        order_type: str = "MARKET",
        limit_price: float = None,
        stop_price: float = None,
        time_in_force: str = "DAY",
        client_order_id: str = None,
        trading_hours: str = "REGULAR",
        expire_ts: str = None,
    ) -> dict:
        """``trading_hours``: REGULAR (default), EXTENDED (04:00-20:00 ET) or
        OVERNIGHT (24/5); outside REGULAR only LIMIT orders are accepted."""
        return self._place_order(
            session_id, account_id,
            instrument={"type": "STOCK", "symbol": symbol},
            side="BUY", qty=qty, order_type=order_type,
            limit_price=limit_price, stop_price=stop_price,
            time_in_force=time_in_force, client_order_id=client_order_id,
            trading_hours=trading_hours, expire_ts=expire_ts,
        )

    def sell(
        self,
        session_id: str,
        account_id: str,
        symbol: str,
        qty: int,
        order_type: str = "MARKET",
        limit_price: float = None,
        stop_price: float = None,
        time_in_force: str = "DAY",
        client_order_id: str = None,
        trading_hours: str = "REGULAR",
        expire_ts: str = None,
    ) -> dict:
        """``trading_hours``: REGULAR (default), EXTENDED (04:00-20:00 ET) or
        OVERNIGHT (24/5); outside REGULAR only LIMIT orders are accepted."""
        return self._place_order(
            session_id, account_id,
            instrument={"type": "STOCK", "symbol": symbol},
            side="SELL", qty=qty, order_type=order_type,
            limit_price=limit_price, stop_price=stop_price,
            time_in_force=time_in_force, client_order_id=client_order_id,
            trading_hours=trading_hours, expire_ts=expire_ts,
        )

    def buy_option(
        self,
        session_id: str,
        account_id: str,
        contract: str,
        qty: int,
        order_type: str = "MARKET",
        limit_price: float = None,
        time_in_force: str = "GTC",
        client_order_id: str = None,
    ) -> dict:
        return self._place_order(
            session_id, account_id,
            instrument={"type": "OPTION", "contract": contract},
            side="BUY", qty=qty, order_type=order_type,
            limit_price=limit_price, time_in_force=time_in_force,
            client_order_id=client_order_id,
        )

    def sell_option(
        self,
        session_id: str,
        account_id: str,
        contract: str,
        qty: int,
        order_type: str = "MARKET",
        limit_price: float = None,
        time_in_force: str = "GTC",
        client_order_id: str = None,
    ) -> dict:
        return self._place_order(
            session_id, account_id,
            instrument={"type": "OPTION", "contract": contract},
            side="SELL", qty=qty, order_type=order_type,
            limit_price=limit_price, time_in_force=time_in_force,
            client_order_id=client_order_id,
        )

    def trade_future(
        self,
        session_id: str,
        account_id: str,
        symbol: str,
        side: str,
        qty: int,
        order_type: str = "MARKET",
        limit_price: float = None,
        stop_price: float = None,
        time_in_force: str = "DAY",
        client_order_id: str = None,
    ) -> dict:
        """Futures order: ``qty`` contracts of ``symbol`` (contract or front-month
        root). Opening contracts need their initial margin free; positions settle
        daily (variation margin)."""
        return self._place_order(
            session_id, account_id,
            instrument={"type": "FUTURE", "symbol": symbol},
            side=side, qty=qty, order_type=order_type, limit_price=limit_price,
            stop_price=stop_price, time_in_force=time_in_force, client_order_id=client_order_id,
        )

    def buy_future(self, session_id: str, account_id: str, symbol: str, qty: int, **kw) -> dict:
        return self.trade_future(session_id, account_id, symbol, "BUY", qty, **kw)

    def sell_future(self, session_id: str, account_id: str, symbol: str, qty: int, **kw) -> dict:
        return self.trade_future(session_id, account_id, symbol, "SELL", qty, **kw)

    def cancel_order(self, order_id: str, session_id: str, account_id: str) -> dict:
        return self._post(
            f"/orders/{order_id}/cancel",
            {"session_id": session_id, "account_id": account_id},
        )
