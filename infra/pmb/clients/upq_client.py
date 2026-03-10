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
        self, contract: str, start: str, end: str
    ) -> list[OptionBar]:
        """GET /option/ticker_query with resolution=minute and Greeks."""
        resp = await self._client.get(
            "/option/ticker_query",
            params={
                "contract": contract,
                "start": start,
                "end": end,
                "resolution": "minute",
                "include_greeks": "true",
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
