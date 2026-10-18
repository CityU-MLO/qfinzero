"""The synthetic sample dataset: determinism, storage contract and consistency."""

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import duckdb
import pytest

from qfinzero.pipeline import schema
from qfinzero.sample import events, market
from qfinzero.sample.universe import DAYS, EARNINGS, HOLIDAYS, MINUTE_WINDOW, STOCKS, Universe

ET = ZoneInfo("America/New_York")


@pytest.fixture(scope="module")
def built(sample_root):
    return sample_root, json.loads((sample_root / "sample_manifest.json").read_text())


def q(sql: str):
    return duckdb.sql(sql).fetchall()


def _digest(p: market.Paths) -> str:
    h = hashlib.sha256()
    for t in sorted(p.close):
        for d in sorted(p.close[t]):
            h.update(p.close[t][d].tobytes())
            h.update(p.volume[t][d].tobytes())
    return h.hexdigest()


def test_simulation_is_deterministic():
    u = Universe()
    a, b = market.simulate(u), market.simulate(u)
    assert _digest(a) == _digest(b)
    assert events.news_items(u, a) == events.news_items(u, b)


def test_calendar_skips_weekends_and_holidays():
    assert all(d.weekday() < 5 and d not in HOLIDAYS for d in DAYS)
    assert DAYS[0] == date(2025, 1, 2) and DAYS[-1] == date(2025, 3, 31)
    assert len(DAYS) == 60


STORES = {
    "stock_daily": schema.STOCK_DAILY, "stock_minute": schema.STOCK_MINUTE,
    "option_day": schema.OPTION_DAY, "option_minute": schema.OPTION_MINUTE,
    "stock_quote_minute": schema.STOCK_QUOTE_MINUTE,
    "option_quote_minute": schema.OPTION_QUOTE_MINUTE,
}


@pytest.mark.parametrize("store", sorted(STORES))
def test_parts_match_storage_schema(built, store):
    root, _ = built
    cols = duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{root}/upq/{store}/trade_date=*/*.parquet', "
                      "hive_partitioning=false)").fetchall()
    assert [(c[0], c[1]) for c in cols] == list(STORES[store].items())


def test_manifest_counts(built):
    _, m = built
    assert m["rows"]["stock_daily"] == len(DAYS) * len(STOCKS)
    assert m["rows"]["earnings"] == len(EARNINGS)
    assert m["rows"]["news"] > 100


def test_daily_close_is_last_regular_minute(built):
    root, _ = built
    d = MINUTE_WINDOW[3]
    rows = q(f"""
        WITH m AS (
          SELECT ticker, close, window_start FROM read_parquet('{root}/upq/stock_minute/trade_date={d}/*.parquet')
          WHERE window_start < {market.et_ns(d, 16 * 60)}
          QUALIFY row_number() OVER (PARTITION BY ticker ORDER BY window_start DESC) = 1)
        SELECT d.ticker, d.close, m.close FROM read_parquet('{root}/upq/stock_daily/trade_date={d}/*.parquet') d
        JOIN m USING (ticker)""")
    assert len(rows) == len(STOCKS)
    for _, daily, minute in rows:
        assert daily == pytest.approx(minute, rel=1e-9)


def test_bars_are_well_formed(built):
    root, _ = built
    (bad,) = q(f"""SELECT count(*) FROM read_parquet('{root}/upq/stock_minute/*/*.parquet')
                   WHERE NOT (low <= least(open, close) AND high >= greatest(open, close) AND volume > 0)""")[0]
    assert bad == 0
    (bad,) = q(f"""SELECT count(*) FROM read_parquet('{root}/upq/stock_quote_minute/*/*.parquet')
                   WHERE NOT (bid_price > 0 AND ask_price > bid_price)""")[0]
    assert bad == 0
    # far out-of-the-money options may bid zero, as in real chains
    (bad,) = q(f"""SELECT count(*) FROM read_parquet('{root}/upq/option_quote_minute/*/*.parquet')
                   WHERE NOT (bid_price >= 0 AND ask_price > 0 AND ask_price >= bid_price)""")[0]
    assert bad == 0


def test_overnight_bars_only_for_overnight_names(built):
    root, _ = built
    rows = q(f"""SELECT DISTINCT ticker FROM read_parquet('{root}/upq/stock_minute/*/*.parquet')
                 WHERE hour(timezone('America/New_York', to_timestamp(window_start / 1e9))) >= 20""")
    assert {r[0] for r in rows} == {"ACME", "NOVA", "QZSP"}


def test_split_in_raw_prices_and_corporate_actions(built):
    root, _ = built
    before, after = q(f"""SELECT close FROM read_parquet('{root}/upq/stock_daily/*/*.parquet')
        WHERE ticker = 'NOVA' AND trade_date IN ('2025-02-28', '2025-03-03') ORDER BY trade_date""")
    assert 1.6 < before[0] / after[0] < 2.5          # 2:1 split plus one day of noise
    ca = q(f"SELECT ex_date, split_ratio FROM read_parquet('{root}/upq/corporate_actions/*.parquet') "
           "WHERE symbol = 'NOVA'")
    assert ca == [(date(2025, 3, 3), 2.0)]


def test_esp_matches_universe(built):
    root, _ = built
    con = sqlite3.connect(root / "esp" / "benzinga_earnings.sqlite3")
    rows = dict(con.execute("SELECT ticker, actual_eps FROM earnings").fetchall())
    assert rows == {e.ticker: e.eps_actual for e in EARNINGS}
    con = sqlite3.connect(root / "esp" / "news.sqlite3")
    (n_tick,) = con.execute("SELECT count(DISTINCT ticker) FROM news_tickers").fetchone()
    assert n_tick == len(STOCKS)


def test_reaction_headline_matches_prices():
    u = Universe()
    p = market.simulate(u)
    items = [i for i in events.news_items(u, p) if i["kind"] == "earnings_reaction"]
    assert len(items) == len(EARNINGS)
    for e in EARNINGS:
        day, ret = events.earnings_reaction(u, p, e)
        (item,) = [i for i in items if i["tickers"] == [e.ticker]]
        assert item["facts"]["ret"] == round(ret, 4)
        assert ("rise" in item["title"]) == (ret > 0)
        # published after the reaction day's close
        pub = datetime.fromisoformat(item["published_utc"]).astimezone(ET)
        assert pub.date() == day and pub.hour == 16


def test_news_never_precedes_its_event():
    u = Universe()
    p = market.simulate(u)
    by = {e.ticker: e for e in EARNINGS}
    for i in events.news_items(u, p):
        if i["kind"] == "earnings_result":
            e = by[i["tickers"][0]]
            release = datetime.combine(e.day, datetime.min.time(), ET).replace(
                hour=16 if e.timing == "AMC" else 7, minute=5 if e.timing == "AMC" else 0)
            assert datetime.fromisoformat(i["published_utc"]) > release.astimezone(timezone.utc)


def test_cli_no_esp(tmp_path, monkeypatch):
    from qfinzero.sample import cli
    calls = {}
    monkeypatch.setattr("qfinzero.sample.generate", lambda out, with_esp: calls.update(out=out, esp=with_esp) or {})
    assert cli.main(["generate", "--out", str(tmp_path), "--no-esp"]) == 0
    assert calls == {"out": str(tmp_path), "esp": False}
