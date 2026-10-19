"""Rate files loaded in Settings: formats, units, overlay that survives conversion."""

from __future__ import annotations

import os
import sys

import pytest

duckdb = pytest.importorskip("duckdb")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero.admin import rates_loader as R  # noqa: E402

TREASURY = """Date,"1 Mo","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
08/21/2026,4.21,4.20,4.18,4.15,4.10,3.98,3.80,3.75,3.82,3.95,4.10,4.45,4.40
08/20/2026,4.22,4.21,4.19,4.16,4.11,3.99,3.81,3.76,3.83,3.96,4.11,4.46,4.41
"""
FRED = "observation_date,DGS3MO\n2026-08-20,4.19\n2026-08-21,.\n2026-08-24,4.17\n"


def test_formats_are_recognised():
    t = R.parse(TREASURY, "daily-treasury-rates.csv")
    assert t["dates"] == 2 and t["start"] == "2026-08-20" and t["end"] == "2026-08-21"
    assert t["tenors"] == R.TENORS and "2 Mo" in t["ignored_columns"]
    assert t["rows"]["2026-08-21"]["yield_3_month"] == 4.18
    f = R.parse(FRED, "DGS3MO.csv")
    assert f["tenors"] == ["yield_3_month"] and f["dates"] == 2          # "." is missing, not zero
    g = R.parse("date,1M,10Y\n2026-08-21,4.2,4.1\n")
    assert g["rows"]["2026-08-21"] == {"yield_1_month": 4.2, "yield_10_year": 4.1}
    with pytest.raises(ValueError, match="percent"):
        R.parse("date,10Y\n2026-08-21,0.041\n2026-08-22,41\n")
    with pytest.raises(ValueError, match="tenor"):
        R.parse("date,foo\n2026-08-21,1\n")


def test_overlay_survives_a_rates_conversion(tmp_path):
    from qfinzero.pipeline.convert import Converter
    from qfinzero.pipeline.paths import resolve
    massive = tmp_path / "massive"
    (massive / "economy").mkdir(parents=True)
    (massive / "economy" / "treasury_yields.jsonl").write_text(
        '{"date":"2026-06-25","yield_1_year":3.96,"yield_5_year":4.15,"yield_10_year":4.4}\n')
    (tmp_path / "tushare").mkdir()
    paths = resolve(massive, tmp_path / "tushare", tmp_path / "upq")
    with Converter(paths) as cv:
        cv.convert_rates()
    res = R.apply(tmp_path / "upq", [R.parse(TREASURY), R.parse(FRED)])
    assert res["loaded_dates"] == 3 and res["store"]["dates"] == 4
    with Converter(paths) as cv:               # a later update rewrites the massive base
        r = cv.convert_rates()
    assert any("laid over" in n for n in r.notes)
    con = duckdb.connect()
    rows = dict(con.execute(f"SELECT CAST(date AS VARCHAR), yield_3_month FROM read_parquet('{tmp_path}/upq/rates/rates.parquet')").fetchall())
    assert rows["2026-08-21"] == 4.18 and rows["2026-08-24"] == 4.17 and rows["2026-06-25"] is None
    st = R.status(tmp_path / "upq")
    assert st["store"]["end"] == "2026-08-24" and st["loaded"]["dates"] == 3
