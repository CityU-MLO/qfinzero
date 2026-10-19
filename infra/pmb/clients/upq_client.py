import httpx

from models.market import StockBar, OptionBar


class UPQClient:
    """Async HTTP client for the UPQ market data service."""

    def __init__(self, base_url: str):
        self._base_url = base_url
        self._client: httpx.AsyncClient | None = None

    async def start(self):
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=30.0)

    async def close(self):
        if self._client:
            await self._client.aclose()

    async def health(self) -> bool:
        resp = await self._client.get("/health")
        return resp.status_code == 200

    async def get_stock_minute_bars(
        self, tickers: list[str], start: str, end: str
    ) -> list[StockBar]:
        """GET /stock for minute bars. start/end in YYYY-MM-DDTHH:MM:SS format."""
        resp = await self._client.get(
            "/stock",
            params={
                "tickers": ",".join(tickers),
                "start": start,
                "end": end,
                "fields": "ticker,window_start,open,high,low,close,volume",
            },
        )
        resp.raise_for_status()
        rows = resp.json()
        return [
            StockBar(
                symbol=r["ticker"],
                window_start_ns=r["window_start"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
            )
            for r in rows
        ]

    async def get_stock_daily_bars(
        self, tickers: list[str], start: str, end: str
    ) -> list[StockBar]:
        """GET /stock/daily. start/end in YYYY-MM-DD format."""
        resp = await self._client.get(
            "/stock/daily",
            params={
                "tickers": ",".join(tickers),
                "start": start,
                "end": end,
                "fields": "ticker,date,open,high,low,close,volume",
            },
        )
        resp.raise_for_status()
        rows = resp.json()
        bars = []
        for r in rows:
            # Daily bars use date string, convert to ns for uniform handling
            from domain.session_clock import iso_to_ns

            date_str = r["date"]
            ns = iso_to_ns(date_str + "T00:00:00+00:00")
            bars.append(
                StockBar(
                    symbol=r["ticker"],
                    window_start_ns=ns,
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=r["volume"],
                )
            )
        return bars

    async def get_option_minute_bars(
        self, contract: str, start: str, end: str, include_greeks: bool = True
    ) -> list[OptionBar]:
        """GET /option/ticker_query with resolution=minute (Greeks optional)."""
        resp = await self._client.get(
            "/option/ticker_query",
            params={
                "contract": contract,
                "start": start,
                "end": end,
                "resolution": "minute",
                "include_greeks": "true" if include_greeks else "false",
            },
        )
        resp.raise_for_status()
        rows = resp.json()
        return [
            OptionBar(
                contract=r.get("contract", r.get("ticker", contract)),
                window_start_ns=r["window_start"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
                iv=r.get("iv"),
                delta=r.get("delta"),
                gamma=r.get("gamma"),
                theta=r.get("theta"),
                vega=r.get("vega"),
                rho=r.get("rho"),
                greek_status=r.get("greek_status"),
            )
            for r in rows
        ]

    async def get_option_quotes(self, contract: str, start: str, end: str):
        """GET /option/quote — minute NBBO for one contract (empty if the UPQ
        build has no quote store or the contract has no quotes)."""
        from domain.session_clock import iso_to_ns, ns_to_iso
        from models.market import Quote
        try:
            resp = await self._client.get(
                "/option/quote",
                params={"contract": contract, "start": ns_to_iso(iso_to_ns(start))[:19],
                        "end": ns_to_iso(iso_to_ns(end))[:19], "limit": 100000},
            )
        except Exception:  # noqa: BLE001 - quotes are an optional enhancement
            return []
        if resp.status_code != 200:
            return []
        return [
            Quote(window_start_ns=r["window_start"], bid=r.get("bid_price"), ask=r.get("ask_price"),
                  bid_size=r.get("bid_size") or 0, ask_size=r.get("ask_size") or 0)
            for r in resp.json()
        ]

    # ── futures ──────────────────────────────────────────────────────

    async def _get_rows(self, path: str, params: dict) -> list[dict]:
        resp = await self._client.get(path, params=params)
        if resp.status_code == 404:      # a UPQ build without futures endpoints
            return []
        resp.raise_for_status()
        return resp.json()

    async def get_future_minute_bars(self, tickers: list[str], start: str, end: str) -> list:
        """GET /future — minute bars (contracts or front-month roots)."""
        from domain.futures import session_date_of
        from domain.session_clock import iso_to_ns, ns_to_iso
        from models.market import FutureBar
        out, cursor, end_s = [], ns_to_iso(iso_to_ns(start))[:19], ns_to_iso(iso_to_ns(end))[:19]
        while True:      # 24-hour sessions: page through the 100k row limit
            rows = await self._get_rows("/future", {"tickers": ",".join(tickers), "start": cursor,
                                                    "end": end_s, "limit": 100000})
            out += [FutureBar(symbol=r["ticker"], root=r.get("root"), window_start_ns=r["window_start"],
                              open=r["open"], high=r["high"], low=r["low"], close=r["close"],
                              volume=r["volume"], session_date=session_date_of(r["window_start"]),
                              instrument_id=r.get("instrument_id"))
                    for r in rows]
            if len(rows) < 100000:
                return out
            cursor = ns_to_iso(max(r["window_start"] for r in rows) + 60_000_000_000)[:19]

    async def get_future_daily_bars(self, tickers: list[str], start: str, end: str) -> list:
        """GET /future/daily — one bar per CME session with ``settle``; stamped
        ``date T00:00Z`` like stock daily bars."""
        from domain.session_clock import iso_to_ns
        from models.market import FutureBar
        rows = await self._get_rows("/future/daily", {"tickers": ",".join(tickers), "start": start, "end": end})
        return [FutureBar(symbol=r["ticker"], root=r.get("root"),
                          window_start_ns=iso_to_ns(r["date"] + "T00:00:00+00:00"),
                          open=r["open"], high=r["high"], low=r["low"], close=r["close"],
                          volume=r["volume"], settle=r.get("settle"), session_date=r["date"],
                          settle_source=r.get("settle_source"), instrument_id=r.get("instrument_id"))
                for r in rows]

    async def get_future_quotes(self, symbol: str, start: str, end: str):
        """GET /future/quote — the book per kept minute (empty when absent)."""
        from domain.session_clock import iso_to_ns, ns_to_iso
        from models.market import Quote
        try:
            rows = await self._get_rows("/future/quote", {
                "tickers": symbol, "start": ns_to_iso(iso_to_ns(start))[:19],
                "end": ns_to_iso(iso_to_ns(end))[:19], "limit": 100000})
        except Exception:  # noqa: BLE001 - quotes are optional
            return []
        return [Quote(window_start_ns=r["window_start"], bid=r.get("bid_price"), ask=r.get("ask_price"),
                      bid_size=r.get("bid_size") or 0, ask_size=r.get("ask_size") or 0) for r in rows]

    async def chain_snapshot(self, underlying: str, at: str, expiry: str | None = None,
                             strike_min: float | None = None, strike_max: float | None = None) -> list[dict]:
        """GET /option/chain_snapshot — the chain as it stood at ``at`` (UTC ISO):
        last trade, volume so far, the latest bid/ask/mid and Greeks from the
        underlying's minute close at that time. Only data final at ``at`` is used."""
        params: dict = {"underlying": underlying, "at": at, "include_greeks": "true"}
        if expiry:
            params["expiry_min"] = expiry
            params["expiry_max"] = expiry
        if strike_min is not None:
            params["strike_min"] = strike_min
        if strike_max is not None:
            params["strike_max"] = strike_max
        resp = await self._client.get("/option/chain_snapshot", params=params)
        resp.raise_for_status()
        return resp.json()

    async def option_chain(self, underlying: str, date: str, expiry_min: str | None = None) -> list[dict]:
        """GET /option/chain_query — the day's option chain (strikes, greeks) for an underlying."""
        params = {
            "underlying": underlying,
            "date": date,
            "include_greeks": "true",
        }
        if expiry_min:
            params["expiry_min"] = expiry_min
        resp = await self._client.get("/option/chain_query", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_option_daily_bars(
        self, contract: str, start: str, end: str
    ) -> list[OptionBar]:
        """GET /option/ticker_query with resolution=day and Greeks."""
        resp = await self._client.get(
            "/option/ticker_query",
            params={
                "contract": contract,
                "start": start,
                "end": end,
                "resolution": "day",
                "include_greeks": "true",
            },
        )
        resp.raise_for_status()
        rows = resp.json()
        bars = []
        for r in rows:
            bars.append(
                OptionBar(
                    contract=r.get("contract", r.get("ticker", contract)),
                    window_start_ns=r.get("window_start", 0),
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=r["volume"],
                    underlying=r.get("underlying"),
                    expiry=r.get("expiry"),
                    strike=r.get("strike"),
                    right=r.get("type", r.get("right")),
                    iv=r.get("iv"),
                    delta=r.get("delta"),
                    gamma=r.get("gamma"),
                    theta=r.get("theta"),
                    vega=r.get("vega"),
                    rho=r.get("rho"),
                    greek_status=r.get("greek_status"),
                )
            )
        return bars
