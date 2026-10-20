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
`stock_quote_minute` and `option_quote_minute` (from Databento
`cbbo-1s/1m` and `bbo-1s/1m`, Blue Ocean's overnight book included, and massive quotes). Minutes without a change are not stored; readers
carry the last quote forward.

| Endpoint | MCP tool | What |
|----------|----------|------|
| `/stock/quote` | `upq_stock_quote` | minute NBBO for stocks |
| `/option/quote` | `upq_option_quote` | minute NBBO for one contract |
| `/option/chain_snapshot` | `upq_chain_snapshot` | the chain at a moment: last trade, volume so far, bid/ask/mid, Greeks off the mid |

**What the store holds.** Before choosing dates, an agent can ask:
`data_extent` gives the date range of every data level, `data_coverage` the
runs of trading days a symbol has each level (stock minutes also by session:
overnight, pre-market, regular, after-hours), `data_day` one symbol-day in
detail, and `upq_option_expiries` the expiries traded on a day with their
strike range. `market_calendar` lists trading days, early closes and each
day's session hours in ET and UTC, the hours PMB's `trading_hours` refer to.
Admins also get `admin_data_catalog`, the raw-data index (datasets, levels,
scope).

Minute sessions load each option's quotes. With
`execution_config.option_fill_model = "quote"` (the default):

- market orders take the ask (buy) or the bid (sell) in force at the bar's open;
- a marketable limit fills at the quote, a resting limit fills at its own price
  only if a trade printed through it during the bar;
- orders can fill in minutes with no trade, as long as there is a quote;
- positions are marked at the mid.

`option_fill_model = "bar"` keeps the bar-only model, where
`option_spread_pct` approximates the spread.

## 4. Futures and margin

Futures come from the Databento adapter (CME Globex `GLBX.MDP3` and other
futures venues) into `future_minute`, `future_daily` (with `settle`) and
`future_quote_minute`, partitioned by CME session: 18:00 ET the evening before
to 17:00 ET. A ticker is a contract (`ZNZ6`) or, for front-month continuous
data, the root (`ZN`).

| Endpoint | MCP tool | What |
|----------|----------|------|
| `/future?tickers=&roots=` | `upq_future_minute` | minute bars; `roots=ZN` returns every series of a product |
| `/future/daily` | `upq_future_daily` | one bar per session with `settle`, final at 17:00 ET |
| `/future/quote` | `upq_future_quote` | top of book per kept minute |

Put futures in a session with `universe.futures` (`future_universe` in
`pmb_create_session`), or later with `POST /v1/sessions/{id}/add_futures`, and
trade them with `instrument: {"type": "FUTURE", "symbol": "ZN"}`
(`pmb_trade_future`). They trade on every bar their venue prints, whatever the
order's `trading_hours`, and fill against their book when quotes are loaded.

Margin works the way an exchange clears it:

- **No premium.** A fill costs only fees (`fee_model.future_fee_per_contract`,
  default 1.50 per side). Fill prices are rounded to the contract's tick.
- **Initial margin.** Opening contracts need `qty × initial` free: equity minus
  the initial margin of everything already held. Otherwise the order is
  rejected with `INSUFFICIENT_MARGIN`.
- **Daily settlement.** At the last bar of each session (every bar in daily
  sessions) each position is settled at the session's `settle`:
  `qty × (settle − previous settle) × multiplier` moves into cash as a
  `VARIATION_MARGIN` event. Between settlements the open trade equity counts
  toward equity, and positions are marked at the bar close or the quote mid.
- **Margin call.** When equity falls below the maintenance margin, a
  `RISK_EVENT` with `call_amount` is raised and new positions are refused
  (`MARGIN_RESTRICTED`); closing orders still execute. The call is met only
  when equity is back at the **initial** margin. A call still open after
  `margin_config.future_margin_call_sessions` settlements (default 1; 0 never
  liquidates) is liquidated at the settlement price (`LIQUIDATION` fills).

Margin per contract comes from the contract spec: either a fixed
`maintenance_margin` in USD (what the exchange publishes) or `margin_rate` of
the notional at the last settlement, with `initial = maintenance ×
initial_ratio` (1.10). Built-in specs cover the common CME contracts (ES, NQ,
YM, RTY and their micros, CL, NG, RB, HO, GC, SI, HG, PL, ZT, ZF, ZN, TN, ZB,
UB, 6E, 6J, 6B, 6A, 6C, ZC, ZS, ZW) with approximate rates. Set the real
numbers per root when opening the account (*Broker → Open an account →
Futures margin*) or in `margin_config.future_specs`: only the fields given
replace the built-in ones, for example `{"ZN": {"maintenance_margin": 2100}}`
(a root that is not built in needs at least `multiplier`). An order on a root
without a spec is refused. `GET /v1/futures/specs` lists the built-in specs;
`GET /v1/sessions/{id}/state` lists the session's specs with the margin per
contract at the current price (`futures_specs`). The account's stock leverage
sets buying power: `equity / stock_initial − initial margin` (Reg-T 50% is 2×).

**Rolls.** A front-month continuous series (`ZN`) moves to the next contract
from time to time; its bars carry the `instrument_id` of the contract behind
them. When it changes, the position moves with it at the new contract's first
price (a `FUTURE_ROLL` event): entry and basis shift by the gap, so open P&L
carries over and the spread between the two contracts is not booked as a gain
or loss. **Settlement prices** are the exchange's when the data has them
(Databento `statistics`, `settle_source = 'exchange'`), else the session's last
trade. The terminal shows each futures position's margin and open P&L since
the last settlement, the daily settlements, rolls, and a banner while a margin
call is open.

Not modelled yet: expiry of outright contracts (trade the continuous series,
or close an outright before its last trading day) and spread (inter-commodity)
margin credits.

## 5. Intraday research

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

## 6. Accounts, roles and API keys

The hub authenticates every request to the website, `/svc/*` and `/mcp`.

| Role | Can |
|------|-----|
| viewer | read data, sessions and the console |
| researcher | also trade, run research and use MCP |
| admin | also manage data sources, users and keys |

Browsers sign in at `/login` and get an HttpOnly session cookie. Agents and
scripts use API keys (`Authorization: Bearer qfz_…` or `X-API-Key`), created
on the account page or with `qfz-auth create-key`. A key acts with its owner's
role, or less (see *Handing out API keys* below).

PMB scopes accounts and sessions to the user who created them. Others get 404,
and admins see everything. The hub strips any identity headers a client sends
and forwards the verified `x-qfz-user` and `x-qfz-role` to the services.

### Handing out API keys

A key can be narrower than its owner. When you create one (account page) or
issue one to someone else (admins, *Users* page), choose:

| setting | effect |
|---|---|
| scopes | the services the key reaches; requests elsewhere get `403` |
| read-only | queries only: no orders, sessions, chat or state-changing MCP tools |
| expiry | after this date the key stops working (`401`) |
| rate limit | requests per minute; beyond it `429` with `Retry-After` |
| note | who it is for, where it runs |

| scope | reaches | least owner role |
|---|---|---|
| `market-data` | UPQ (`/svc/upq`, `/api/upq`, `/api/coverage`) | viewer |
| `events` | ESP (`/svc/esp`, `/api/esp`) | viewer |
| `trading` | PMB (`/svc/pmb`, `/api/pmb`) | researcher |
| `mcp` | `/mcp`; its tools follow the other scopes (`upq_*`/`research_*`/`data_*` need `market-data`, `esp_*` need `events`, `pmb_*` need `trading`, `admin_*` need `admin`; `market_calendar` needs none) | researcher |
| `chat` | the chat assistant | researcher |
| `admin` | data administration, users and keys | admin |

A key never exceeds its owner's role: a viewer cannot hold `trading`, and
demoting the owner narrows every key they have. Presets cover the usual cases
(*Data reader*: market data and events, read-only; *MCP agent*: MCP, data,
events and trading; *Full access*: every scope the owner has, the behaviour of
keys made before scopes existed). The token is shown once, with snippets for
the environment, curl, Python and an MCP client configuration.

The key list shows requests per day for the last 14 days (and how many were
refused), when the key was last used, and who issued it. Scopes, read-only,
expiry and the rate limit can be changed later without a new token; revoking
takes effect on the next request.

```bash
qfz-auth create-key bob --name class-feed --scopes market-data,events \
    --read-only --expires-days 30 --rate 600
```

Over HTTP: `GET /auth/scopes`, `POST /auth/keys` (own),
`POST /auth/users/{id}/keys` (admins), `PATCH /auth/keys/{id}`,
`DELETE /auth/keys/{id}`, with the fields `scopes` (list, or `null` for all),
`read_only`, `expires_in_days` or `expires_at` (`YYYY-MM-DD`), `rate_per_min`
and `note`. A key can manage keys only with the `admin` scope.

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
