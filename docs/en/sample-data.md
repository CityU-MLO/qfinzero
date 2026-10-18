# Sample dataset

> 中文: [docs/cn/sample-data.md](../cn/sample-data.md)

`qfz-sample` writes a complete, redistributable QFinZero data root: prices,
quotes, options, corporate actions, rates, earnings, macro releases and news.
It is what the Docker image starts with, what the end-to-end tests run on and
what the [agent benchmark](bench.md) is built from.

```bash
qfz-sample generate --out ./qfz-sample       # about 25 s, about 22 MB
QFZ_DATA_ROOT=./qfz-sample qfz-server
```

`--no-esp` skips the event databases. The command replaces `upq/` and `esp/`
under the target and writes `sample_manifest.json` with row counts.

## Why synthetic

The tickers do not exist on any exchange. A language model cannot answer
questions about them from memory, so a correct answer shows that the agent
used the tools. The data can also be shared without a vendor licence. It is
generated from a fixed seed, so every run produces identical files.

It is not market data. Use it to test software and agents, not to draw
conclusions about markets.

## Calendar

- 2025-01-02 to 2025-03-31 on the NYSE calendar: 60 trading days. The market
  holidays (New Year, MLK Day, Presidents' Day) and the 2025-01-09 national day
  of mourning are closed.
- Daily bars on every trading day. Minute bars, stock quotes and option quotes
  for the last 10 trading days, 2025-03-18 to 2025-03-31.
- Minute bars cover 04:00 to 20:00 ET (pre-market, regular, after-hours).
  ACME, NOVA and QZSP also trade on the overnight venue (20:00 to 04:00 ET) on
  Monday to Thursday nights inside the minute window.
- The 2025-03-09 change to daylight saving time is inside the window, so UTC
  offsets change as they do in real data.

## Universe

| ticker | name | notes |
|---|---|---|
| QZSP | QFinZero Synthetic 500 ETF | index ETF; options; dividend; overnight venue |
| ACME | Acme Robotics | options; earnings after the close on 2025-03-24; overnight venue |
| BOLT | Bolt Electric Vehicles | options; earnings before the open on 2025-03-27 |
| NOVA | Nova Semiconductor | 2-for-1 split, ex-date 2025-03-03; overnight venue |
| CRUX, DYNE, EMBR, FERN, GALE, HALO, IRIS, JADE, KITE, LUMA, MESA, NEXA, ORCA, PIKE, QUIL, RIFT | | one sector each; ten pay a quarterly dividend |

Prices follow a factor model: market, sector and stock moves, with jumps at
macro releases and earnings. Stock prices are in cents. Volume follows the
usual intraday U shape and rises around events.

## What is written where

The layout is the production layout, so every service reads it unchanged.

| path | content |
|---|---|
| `upq/stock_daily`, `upq/stock_minute` | bars, raw (as traded); the split is applied on read with `adjust=split` |
| `upq/stock_quote_minute` | minute NBBO for all stocks in the minute window |
| `upq/option_day` | daily bars for every listed contract |
| `upq/option_minute`, `upq/option_quote_minute` | trades and NBBO for contracts within 10% of the money in the first four expiries |
| `upq/corporate_actions`, `upq/dividends` | the NOVA split and ten quarterly dividends |
| `upq/rates` | seven Treasury tenors |
| `esp/benzinga_earnings.sqlite3` | 12 earnings reports with estimates and actuals |
| `esp/nasdaq_econ_events.sqlite3` | 11 US macro releases (payrolls, CPI, FOMC, …) |
| `esp/news.sqlite3` | about 250 articles; read by ESP's SQLite news backend |

Options are listed on QZSP, ACME and BOLT, with weekly and monthly expiries
through 2025-06-20 (Thursday when the Friday is a holiday). Prices come from
Black-Scholes with a volatility smile and an earnings premium that disappears
after the report, so implied volatility falls after earnings as it does in
practice.

## News

Every article is tied to something in the data:

- a preview two trading days before each earnings report, the result one
  minute after the release and the price reaction after the next close;
- each macro release, one minute after it;
- the split and dividend announcements;
- the largest daily move of each stock in each week, when it exceeds 2.5%.

The reaction headline states the move computed from the stored closes, so
"ACME shares rise 6.1%" can be checked against UPQ.

## Point-in-time behaviour

The event stores are complete, but ESP only reveals a result once its time has
passed the query's `now_utc` (or the session clock of a time-locked agent).
Asked at 15:00 ET on 2025-03-24, ACME's EPS is `null`; at 16:05 it is 1.61.
News published later than `now_utc` does not exist yet.

## Code

`qfinzero/sample/`: `universe.py` (tickers, calendar, events), `market.py`
(price paths and the UPQ writers), `events.py` (the ESP databases). The schemas
of the ESP databases are in `qfinzero/esp_schema.py`. `tests/test_sample.py`
checks determinism, the storage contract and consistency between stores.
