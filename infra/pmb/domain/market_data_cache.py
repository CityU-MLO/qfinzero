import bisect

from models.market import OptionBar, Quote, StockBar

NS_PER_MIN = 60_000_000_000


class MarketDataCache:
    """Prefetched market data indexed by timestamp. Zero I/O during stepping."""

    def __init__(self):
        self._stock_bars: dict[str, dict[int, StockBar]] = {}  # symbol -> {ns -> bar}
        self._option_bars: dict[str, dict[int, OptionBar]] = {}  # contract -> {ns -> bar}
        self._option_quotes: dict[str, list[Quote]] = {}  # contract -> quotes by time
        self._quote_keys: dict[str, list[int]] = {}
        self._all_timestamps: list[int] = []

    # ── option quotes (NBBO at minute ends) ──────────────────────────

    def load_option_quotes(self, contract: str, quotes: list[Quote]) -> None:
        qs = sorted(quotes, key=lambda q: q.window_start_ns)
        self._option_quotes[contract] = qs
        self._quote_keys[contract] = [q.window_start_ns for q in qs]

    def has_quotes(self, contract: str) -> bool:
        return bool(self._option_quotes.get(contract))

    def get_option_quote_at(self, contract: str, ts_ns: int) -> Quote | None:
        """The book in force when the bar starting at ``ts_ns`` opens: the latest
        quote whose minute had closed by then (``window_start + 60s <= ts_ns``).
        Minutes without an update carry the previous quote."""
        keys = self._quote_keys.get(contract)
        if not keys:
            return None
        i = bisect.bisect_right(keys, ts_ns - NS_PER_MIN)
        return self._option_quotes[contract][i - 1] if i else None

    def get_option_quotes_at(self, ts_ns: int) -> dict[str, Quote]:
        out = {}
        for contract in self._option_quotes:
            q = self.get_option_quote_at(contract, ts_ns)
            if q is not None:
                out[contract] = q
        return out

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
        # Options with quotes mark at the mid, also in minutes without a trade.
        for contract in self._option_quotes:
            q = self.get_option_quote_at(contract, ts_ns + NS_PER_MIN)   # book at bar close
            if q is not None and q.mid is not None:
                prices[f"OPTION:{contract}"] = q.mid
        return prices
