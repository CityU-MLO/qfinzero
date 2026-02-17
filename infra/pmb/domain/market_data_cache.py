from models.market import StockBar, OptionBar


class MarketDataCache:
    """Prefetched market data indexed by timestamp. Zero I/O during stepping."""

    def __init__(self):
        self._stock_bars: dict[str, dict[int, StockBar]] = {}  # symbol -> {ns -> bar}
        self._option_bars: dict[str, dict[int, OptionBar]] = {}  # contract -> {ns -> bar}
        self._all_timestamps: list[int] = []

    def load_stock_bars(self, symbol: str, bars: list[StockBar]):
        by_ts = {}
        for bar in bars:
            by_ts[bar.window_start_ns] = bar
        self._stock_bars[symbol] = by_ts
        self._rebuild_timestamps()

    def load_option_bars(self, contract: str, bars: list[OptionBar]):
        by_ts = {}
        for bar in bars:
            by_ts[bar.window_start_ns] = bar
        self._option_bars[contract] = by_ts
        self._rebuild_timestamps()

    def _rebuild_timestamps(self):
        ts_set: set[int] = set()
        for by_ts in self._stock_bars.values():
            ts_set.update(by_ts.keys())
        for by_ts in self._option_bars.values():
            ts_set.update(by_ts.keys())
        self._all_timestamps = sorted(ts_set)

    def get_all_timestamps(self) -> list[int]:
        return self._all_timestamps

    def get_stock_bars_at(self, ts_ns: int) -> dict[str, StockBar]:
        result = {}
        for symbol, by_ts in self._stock_bars.items():
            bar = by_ts.get(ts_ns)
            if bar is not None:
                result[symbol] = bar
        return result

    def get_option_bars_at(self, ts_ns: int) -> dict[str, OptionBar]:
        result = {}
        for contract, by_ts in self._option_bars.items():
            bar = by_ts.get(ts_ns)
            if bar is not None:
                result[contract] = bar
        return result

    def get_latest_price(self, instrument_id: str, up_to_ns: int) -> float | None:
        """Return close price of most recent bar <= up_to_ns for a symbol/contract."""
        # Check stocks
        prefix = instrument_id.split(":", 1)
        if len(prefix) == 2:
            key = prefix[1]
        else:
            key = instrument_id

        if key in self._stock_bars:
            by_ts = self._stock_bars[key]
            best_ns = None
            for ns in by_ts:
                if ns <= up_to_ns:
                    if best_ns is None or ns > best_ns:
                        best_ns = ns
            if best_ns is not None:
                return by_ts[best_ns].close

        if key in self._option_bars:
            by_ts = self._option_bars[key]
            best_ns = None
            for ns in by_ts:
                if ns <= up_to_ns:
                    if best_ns is None or ns > best_ns:
                        best_ns = ns
            if best_ns is not None:
                return by_ts[best_ns].close

        return None

    def get_prices_at(self, ts_ns: int) -> dict[str, float]:
        """Return {instrument_id: close_price} for all instruments with data at ts_ns."""
        prices: dict[str, float] = {}
        for symbol, by_ts in self._stock_bars.items():
            bar = by_ts.get(ts_ns)
            if bar is not None:
                prices[f"STOCK:{symbol}"] = bar.close
        for contract, by_ts in self._option_bars.items():
            bar = by_ts.get(ts_ns)
            if bar is not None:
                prices[f"OPTION:{contract}"] = bar.close
        return prices
