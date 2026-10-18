# Platform guide: time lock, sessions, intraday trading, research and accounts

> 中文: [docs/cn/platform-guide.md](../cn/platform-guide.md)

This guide covers what an agent or a researcher needs beyond the basic APIs:
how QFinZero keeps every query point-in-time, how trading sessions and order
hours work, how options fill against quotes, how to mine intraday factors, and
how to run the server with accounts.

## 1. The time lock

An agent that trades in a simulation must only see what was known at the bar
it is deciding on. QFinZero enforces this on the server, not in the prompt.

**Visibility rules (UPQ `as_of`).** Every UPQ data endpoint accepts `as_of`
(ISO datetime, UTC unless it carries an offset, or nanoseconds). A row is
returned only if it was final at `as_of`:

| Data | Visible when |
|------|--------------|
| Minute bar or minute quote starting at `t` | `t + 60s <= as_of` |
| Stock daily bar for date D | `as_of >= D 16:00 ET` |
| Option daily bar and end-of-day chain for D | `as_of >= D 16:15 ET` |
| Rates, dividends | up to the trading date of `as_of` |

Starting UPQ with `UPQ_AS_OF=<time>` sets a ceiling for every request (a
request may ask for an earlier `as_of`, never a later one). An unparsable
value makes UPQ serve nothing.

**Binding a session.** A PMB session's clock turns into `as_of` automatically.
For minute sessions this is the close of the current bar; for daily sessions
16:00 ET of the current trading date. The session is chosen, in order, by:

1. the `X-QFZ-Session` header of the MCP or HTTP connection (benchmark
   runners set it; the agent cannot change it);
2. the `QFZ_TIME_LOCK_SESSION` environment variable (one MCP server per episode);
3. the `session_id` argument of a data tool.

With a bound session, `upq_*` tools pass `as_of`, ESP tools run with
`now_utc = as_of` and cap their window end at it, and `research_*` tools cap
their date range. Set `QFZ_REQUIRE_SESSION=1` to refuse data queries that are
not bound to any session.

```json
{ "mcpServers": { "qfinzero": {
    "url": "https://your-host/mcp/",
    "headers": { "Authorization": "Bearer qfz_…", "X-QFZ-Session": "sess_3f2a9c1e" } } } }
```

Intraday Greeks also stay point-in-time: they use the underlying's minute close
at the same time, not the end-of-day close.

## 2. Trading sessions and order hours

PMB models the US session in four segments (US/Eastern):

| Segment | Hours | Trading date |
|---------|-------|--------------|
| Overnight | 20:00–04:00 | the next weekday |
| Pre-market | 04:00–09:30 | same day |
| Regular | 09:30–16:00 | same day |
| After-hours | 16:00–20:00 | same day |

Every order has `trading_hours`:

- `REGULAR` (default): fills in the regular session only; any order type.
- `EXTENDED`: pre-market, regular and after-hours; limit orders only.
- `OVERNIGHT`: all four segments (24/5); limit orders only.

Options trade in the regular session only. `time_in_force` is enforced: `DAY`
orders expire at the end of the trading date on which they first became
eligible (a regular-hours order sent after the close waits for the next day),
`GTD` orders expire at `expire_ts`, `GTC` orders stay open.

`execution_config.partial_fill = {"enabled": true, "max_fill_ratio_per_tick":
0.1}` caps each fill at a share of the bar's volume (or the displayed size
when filling against quotes). `enforce_trading_hours: false` restores the old
behaviour where every bar was tradable and orders never expired.

Step responses carry `clock.segment` and `clock.trading_date`.

**Overnight data.** The Databento adapter reads Blue Ocean (`OCEA.MEMOIR`)
files, so overnight minute bars sit beside the daytime bars from any vendor.
Daily bars never include overnight trades.

**Waking an agent only when needed.** Minute sessions have 390 regular bars a
day. `pmb_step_until` (REST `POST /v1/sessions/{id}/step_until`) advances until
the first of: a fill, a price trigger (`{"symbol": "SPY", "op": ">=",
"price": 600}`), a time (`until_ts`), entering a segment (`stop_on_segment:
"REGULAR"` skips to the next open), or `max_steps`. It returns the order and
trade events, the last market tick and the account.

## 3. Quotes and option fills

Two quote stores hold the top of book at the end of each minute:
`stock_quote_minute` and `option_quote_minute` (from Databento `cmbp-1`,
`cbbo-1s/1m`, `bbo-1s/1m`). Minutes without a change are not stored; readers
carry the last quote forward.

| Endpoint | MCP tool | What |
|----------|----------|------|
| `/stock/quote` | `upq_stock_quote` | minute NBBO for stocks |
| `/option/quote` | `upq_option_quote` | minute NBBO for one contract |
| `/option/chain_snapshot` | `upq_chain_snapshot` | the chain at a moment: last trade, volume so far, bid/ask/mid, Greeks off the mid |

Minute sessions load each option's quotes. With
`execution_config.option_fill_model = "quote"` (the default):

- market orders take the ask (buy) or the bid (sell) in force at the bar's open;
- a marketable limit fills at the quote, a resting limit fills at its own price
  only if a trade printed through it during the bar;
- orders can fill in minutes with no trade, as long as there is a quote;
- positions are marked at the mid.

`option_fill_model = "bar"` keeps the bar-only model, where
`option_spread_pct` approximates the spread.

## 4. Intraday research

`qfinzero.research` reads the UPQ stores directly with DuckDB. Factors are one
expression:

```bash
qfz-research fields                                   # fields and functions
qfz-research eval "cs_rank(-pct(close, 15))" --start 2026-08-10 --end 2026-08-21 \
    --universe 500 --horizons 5,15,30
qfz-research backtest "cs_rank(-pct(close, 15))" --start 2026-08-10 --end 2026-08-21 \
    --rebalance 30 --fraction 0.1 --cost-bps 0.5
```

| Element | Meaning |
|---------|---------|
| Fields | `open high low close volume transactions vwap ret minute`, plus `bid ask mid spread imbalance` when stock quotes exist |
| Time series | `ts_mean ts_sum ts_std ts_min ts_max ts_zscore (x, n)`, `ts_corr ts_cov (x, y, n)`, `delay delta pct (x, n)` |
| Cross section | `cs_rank cs_zscore cs_demean (x)` |
| Scalar | `abs log sign sqrt`, `max min (a, b)`, `+ - * /` |

Point-in-time rules are part of the language:

- windows end at the current bar, must be full, and reset each trading day
  (unless `--cross-day`);
- `delay`, `delta` and `pct` need `n >= 1`;
- a signal at bar `t` enters at the open of `t+1`;
- the universe is the top N by the previous day's dollar volume.

Evaluation reports IC, rank IC, ICIR, t-statistics, quantile returns, the
long-short spread, top-quantile turnover and IC by hour, for non-overlapping
horizons. The backtest rebalances every k bars, holds the top (and shorts the
bottom) fraction equal-weighted, goes flat at the close, and charges
`cost_bps` plus half the quoted spread. On the reference server, 500 names
over 10 days of minute data take about 4 seconds.

Agents use the same engine through `research_eval_factor` and
`research_backtest`. These tools are limited by `QFZ_RESEARCH_MAX_DAYS`
(default 40 trading days) and `QFZ_RESEARCH_MAX_UNIVERSE` (default 1000), and
they honour the time lock.

## 5. Accounts, roles and API keys

The hub authenticates every request to the website, `/svc/*` and `/mcp`.

| Role | Can |
|------|-----|
| viewer | read data, sessions and the console |
| researcher | also trade, run research and use MCP |
| admin | also manage data sources, users and keys |

Browsers sign in at `/login` and get an HttpOnly session cookie. Agents and
scripts use API keys (`Authorization: Bearer qfz_…` or `X-API-Key`), created
on the account page or with `qfz-auth create-key`. A key acts with its owner's
role.

PMB scopes accounts and sessions to the user who created them. Others get 404,
and admins see everything. The hub strips any identity headers a client sends
and forwards the verified `x-qfz-user` and `x-qfz-role` to the services.

**First run.** Use one of:

- set `QFZ_ADMIN_PASSWORD` (and optionally `QFZ_ADMIN_USERNAME`) before starting;
- run `qfz-auth create-user <name> --role admin`;
- open `/setup` and enter the one-time token the hub prints in its log, which
  is also stored in `$QFZ_DATA_ROOT/_state/setup_token`.

```bash
qfz-auth list
qfz-auth create-user alice --role researcher
qfz-auth create-key alice --name eval-runner      # prints the key once
qfz-auth set-role alice viewer
qfz-auth disable alice
```

| Variable | Default | Effect |
|----------|---------|--------|
| `QFZ_AUTH_MODE` | `required` | `off` disables checks for local development |
| `QFZ_SECRET_KEY` | generated into `_state/auth_secret` | cookie signing key |
| `QFZ_SESSION_DAYS` | `7` | browser session lifetime |
| `QFZ_COOKIE_SECURE` | `auto` | `Secure` cookies when served over HTTPS |
| `QFZ_AUTH_DB` | `_state/auth.sqlite3` | user and key store |
| `QFZ_PUBLIC_HOSTS` | (none) | public host names allowed to reach `/mcp` |

Behind a reverse proxy, terminate TLS there and forward `X-Forwarded-Proto` and
`X-Forwarded-For`. UPQ and the Next.js child listen on 127.0.0.1 by default
(`UPQ_HOST` overrides), so the hub is the only public entry point.
Passwords are hashed with scrypt, API keys are stored as SHA-256 digests,
failed sign-ins are throttled, and changing a password signs out every other
browser.
