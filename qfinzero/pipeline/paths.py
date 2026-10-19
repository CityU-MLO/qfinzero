"""Resolved filesystem locations for the data pipeline.

Raw sources are read **in place**; the converter only ever writes under
``UPQ_STORAGE_ROOT``. All values come from :mod:`qfinzero.config` (env-driven).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from qfinzero.config import (
    RAW_DATABENTO_DIR,
    RAW_MASSIVE_DIR,
    RAW_TUSHARE_DIR,
    UPQ_STORAGE_ROOT,
)


# ── UPQ storage sub-stores (must match what the UPQ Rust service reads) ──
STOCK_DAILY = "stock_daily"
STOCK_MINUTE = "stock_minute"
OPTION_DAY = "option_day"
OPTION_MINUTE = "option_minute"
STOCK_QUOTE_MINUTE = "stock_quote_minute"
OPTION_QUOTE_MINUTE = "option_quote_minute"
FUTURE_DAILY = "future_daily"
FUTURE_MINUTE = "future_minute"
FUTURE_QUOTE_MINUTE = "future_quote_minute"
# 24-hour markets from massive global flat files; trade_date is the UTC day
CRYPTO_DAILY = "crypto_daily"
CRYPTO_MINUTE = "crypto_minute"
FX_DAILY = "fx_daily"
FX_MINUTE = "fx_minute"
FX_QUOTE_MINUTE = "fx_quote_minute"
RATES = "rates"
CORPORATE_ACTIONS = "corporate_actions"
DIVIDENDS = "dividends"  # back-compat store for option Greeks / /dividends/query


@dataclass(frozen=True)
class PipelinePaths:
    massive: Path
    tushare: Path
    storage: Path
    databento: Path = Path(RAW_DATABENTO_DIR)
    tiingo: Path = Path(os.environ.get("RAW_TIINGO_DIR") or "/data/tiingo")

    # ── raw massive layout ──────────────────────────────────────
    @property
    def massive_stock_day(self) -> Path:
        return self.massive / "us_stocks_sip" / "day_aggs_v1"

    @property
    def massive_stock_minute(self) -> Path:
        return self.massive / "us_stocks_sip" / "minute_aggs_v1"

    @property
    def massive_option_day(self) -> Path:
        return self.massive / "us_options_opra" / "day_aggs_v1"

    @property
    def massive_option_minute(self) -> Path:
        return self.massive / "us_options_opra" / "minute_aggs_v1"

    @property
    def massive_crypto_day(self) -> Path:
        return self.massive / "global_crypto" / "day_aggs_v1"

    @property
    def massive_crypto_minute(self) -> Path:
        return self.massive / "global_crypto" / "minute_aggs_v1"

    @property
    def massive_fx_day(self) -> Path:
        return self.massive / "global_forex" / "day_aggs_v1"

    @property
    def massive_fx_minute(self) -> Path:
        return self.massive / "global_forex" / "minute_aggs_v1"

    @property
    def massive_fx_quotes(self) -> Path:
        return self.massive / "global_forex" / "quotes_v1"

    @property
    def massive_treasury(self) -> Path:
        return self.massive / "economy" / "treasury_yields.jsonl"

    @property
    def massive_splits(self) -> Path:
        return self.massive / "corporate_actions" / "splits"

    @property
    def massive_dividends(self) -> Path:
        return self.massive / "corporate_actions" / "dividends"

    # ── raw tushare layout ──────────────────────────────────────
    @property
    def tushare_cn_daily(self) -> Path:
        return self.tushare / "cn" / "daily"

    @property
    def tushare_cn_dividend(self) -> Path:
        return self.tushare / "cn" / "dividend"

    @property
    def tushare_cn_adj_factor(self) -> Path:
        return self.tushare / "cn" / "adj_factor"

    @property
    def tushare_stock_basic(self) -> Path:
        return self.tushare / "meta" / "stock_basic.parquet"

    # ── state written beside the UPQ storage ────────────────────
    @property
    def state_dir(self) -> Path:
        return self.storage / "_state"

    @property
    def databento_staging(self) -> Path:
        """Per-source-file bar cache for the Databento converter."""
        return self.storage / "_staging" / "databento"

    @property
    def tiingo_staging(self) -> Path:
        """Per-month bar / per-day quote cache for the Tiingo converter."""
        return self.storage / "_staging" / "tiingo"

    # ── UPQ storage output sub-stores ───────────────────────────
    def store(self, name: str) -> Path:
        return self.storage / name

    def partition(self, store: str, trade_date: str) -> Path:
        """Hive-style partition dir, e.g. ``stock_daily/trade_date=2025-01-06``."""
        return self.storage / store / f"trade_date={trade_date}"


def resolve(
    massive: str | os.PathLike | None = None,
    tushare: str | os.PathLike | None = None,
    storage: str | os.PathLike | None = None,
    databento: str | os.PathLike | None = None,
    tiingo: str | os.PathLike | None = None,
) -> PipelinePaths:
    """Resolve all pipeline locations, with optional explicit overrides.

    The Databento root falls back to ``RAW_DATABENTO_DIR`` read at call time, so
    a value applied by the config store after import is honoured.
    """
    return PipelinePaths(
        massive=Path(massive or RAW_MASSIVE_DIR).expanduser(),
        tushare=Path(tushare or RAW_TUSHARE_DIR).expanduser(),
        storage=Path(storage or UPQ_STORAGE_ROOT).expanduser(),
        databento=Path(
            databento or os.environ.get("RAW_DATABENTO_DIR") or RAW_DATABENTO_DIR
        ).expanduser(),
        tiingo=Path(tiingo or os.environ.get("RAW_TIINGO_DIR") or "/data/tiingo").expanduser(),
    )
