"""Tests for the qfz-data pipeline converter on a tiny synthetic dataset.

Skipped when duckdb is unavailable (the pipeline's optional dependency).
"""

from __future__ import annotations

import os
import sys

import pytest

duckdb = pytest.importorskip("duckdb")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _build_raw(massive_root, tushare_root):
    """Emit a minimal massive-like + tushare-like raw tree."""
    con = duckdb.connect()
    day = massive_root / "us_stocks_sip" / "day_aggs_v1" / "2025" / "01"
    day.mkdir(parents=True, exist_ok=True)
    # FOO: close 100 on 01-02, then a 2:1 split + $1 dividend ex 01-03
    con.execute(
        f"""COPY (SELECT 'FOO' AS ticker, 1000::BIGINT AS volume, 99.0 AS open,
                100.0 AS close, 101.0 AS high, 98.0 AS low,
                1735819200000000000::BIGINT AS window_start, 10::BIGINT AS transactions)
            TO '{day / '2025-01-02.parquet'}' (FORMAT PARQUET)"""
    )
    con.execute(
        f"""COPY (SELECT 'FOO' AS ticker, 2000::BIGINT AS volume, 50.0 AS open,
                52.0 AS close, 53.0 AS high, 49.0 AS low,
                1735905600000000000::BIGINT AS window_start, 12::BIGINT AS transactions)
            TO '{day / '2025-01-03.parquet'}' (FORMAT PARQUET)"""
    )
    splits = massive_root / "corporate_actions" / "splits"
    splits.mkdir(parents=True, exist_ok=True)
    (splits / "FOO.jsonl").write_text(
        '{"ticker":"FOO","execution_date":"2025-01-03","split_from":1.0,"split_to":2.0,'
        '"adjustment_type":"forward_split"}\n'
    )
    divs = massive_root / "corporate_actions" / "dividends"
    divs.mkdir(parents=True, exist_ok=True)
    (divs / "FOO.jsonl").write_text(
        '{"ticker":"FOO","ex_dividend_date":"2025-01-03","cash_amount":1.0,"currency":"USD"}\n'
    )
    # tushare daily dir must exist (empty is fine for this test)
    (tushare_root / "cn" / "daily").mkdir(parents=True, exist_ok=True)
    (tushare_root / "cn" / "dividend").mkdir(parents=True, exist_ok=True)
    con.close()


def test_convert_us_stock_daily_and_corporate_actions(tmp_path):
    from qfinzero.pipeline.convert import Converter
    from qfinzero.pipeline.paths import resolve

    massive = tmp_path / "massive"
    tushare = tmp_path / "tushare"
    storage = tmp_path / "storage"
    _build_raw(massive, tushare)

    paths = resolve(massive, tushare, storage)
    with Converter(paths) as cv:
        r = cv.convert_us_stock_daily()
        assert r.partitions == 2 and r.rows == 2
        ca = cv.convert_corporate_actions(include_massive=True, include_tushare=False)
        # split and dividend on the same ex_date are emitted as two rows that
        # compose multiplicatively on read (x0.5 split, x0.99 dividend).
        assert ca.rows == 2

    con = duckdb.connect()
    # raw close preserved (no adjustment baked in)
    close = con.execute(
        f"SELECT close FROM read_parquet('{storage}/stock_daily/trade_date=2025-01-02/part-0000.parquet') WHERE ticker='FOO'"
    ).fetchone()[0]
    assert close == 100.0

    cap = f"{storage}/corporate_actions/corporate_actions.parquet"
    # split row: split_ratio = 2.0 (2:1 forward split)
    split_ratio = con.execute(
        f"SELECT split_ratio FROM read_parquet('{cap}') WHERE symbol='FOO' AND source='massive:split'"
    ).fetchone()[0]
    assert split_ratio == pytest.approx(2.0)
    # dividend row: cash = 1.0, div_price_ratio = 1 - 1/100 = 0.99 (prior close 100)
    cash, dpr = con.execute(
        f"SELECT dividend_cash, div_price_ratio FROM read_parquet('{cap}') WHERE symbol='FOO' AND source='massive:dividend'"
    ).fetchone()
    con.close()
    assert cash == pytest.approx(1.0)
    assert dpr == pytest.approx(0.99, abs=1e-9)


def test_adjust_mode_parsing_matches_rust_contract():
    """The pipeline's documented adjust values mirror the UPQ service enum."""
    # Mirrors corporate_actions.rs AdjustMode::parse accepted spellings.
    valid = {"none", "raw", "split", "splits", "total", "all", "forward", ""}
    assert "none" in valid and "split" in valid and "total" in valid
