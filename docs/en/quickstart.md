# Quick start

> 中文: [docs/cn/quickstart.md](../cn/quickstart.md)

Five minutes from nothing to an agent that reads prices, news and an option
chain and trades on the paper broker. Everything below runs on the synthetic
sample that the Docker image starts with (tickers `QZSP`, `ACME`, `BOLT`, …,
2025-01-02 to 2025-03-31), so no data vendor account is needed. For the longer
tour of the console, see [Getting started](getting-started.md).

## 1. Start QFinZero

```bash
git clone https://github.com/CityU-MLO/qfinzero && cd qfinzero
export QFZ_ADMIN_PASSWORD='choose-a-long-password'
docker compose up -d                 # first build about 15 minutes
curl http://localhost:19777/health   # every child "up"
```

Open <http://localhost:19777> and sign in as `admin`.

## 2. Get an API key

Agents and scripts sign their requests with a key. Create one on the
**Account** page, or from the command line (`qfz-auth show-key <id>` prints it again later):

```bash
docker compose exec qfinzero qfz-auth create-key admin --name quickstart
export QFZ_API_KEY=qfz_…
```

## 3. Call the REST APIs

Every service sits behind the hub under `/svc/<service>`:

```bash
H="Authorization: Bearer $QFZ_API_KEY"
curl -H "$H" "http://localhost:19777/svc/upq/stock/daily?tickers=ACME&start=2025-03-17&end=2025-03-28"
curl -H "$H" "http://localhost:19777/svc/upq/option/chain_snapshot?underlying=ACME&at=2025-03-24T19:30:00Z&expiry_max=2025-04-04&include_greeks=true"
curl -H "$H" -X POST http://localhost:19777/svc/esp/esp/news/search \
     -H 'content-type: application/json' \
     -d '{"tickers": ["ACME"], "start_utc": "2025-03-24T00:00:00Z", "end_utc": "2025-03-26T00:00:00Z"}'
```

## 4. Use the Python clients

`pip install -e .` in the checkout installs `qfinzero` with its clients. With
`QFZ_API_KEY` set they sign every request (or pass `api_key=`):

```python
from qfinzero.clients.upq import UPQClient
from qfinzero.clients.esp import ESPClient
from qfinzero.clients.pmb import PMBClient

HUB = "http://localhost:19777"

with UPQClient(f"{HUB}/svc/upq") as upq:
    bars = upq.stock_daily(["ACME"], "2025-03-17", "2025-03-28")
    chain = upq.chain_snapshot("ACME", "2025-03-24T19:30:00Z", expiry_max="2025-04-04", include_greeks=True)

with ESPClient(f"{HUB}/svc/esp") as esp:
    news = esp.search_news(tickers=["ACME"], start_utc="2025-03-24T00:00:00Z", end_utc="2025-03-26T00:00:00Z")
    earnings = esp.earnings_calendar(tickers=["ACME"], start_date="2025-03-01", end_date="2025-03-31")

with PMBClient(f"{HUB}/svc/pmb") as pmb:
    acct = pmb.create_account(initial_cash=100_000, start_date="2025-03-24")
    sess = pmb.create_session(acct["account_id"], "1m", "2025-03-24T13:30:00", "2025-03-24T20:00:00",
                              universe={"stocks": ["ACME"]})
    sid = sess["session_id"]
    pmb.step(sid)                                   # the 09:30 ET bar
    pmb.buy(sid, acct["account_id"], "ACME", 100)   # market orders fill on the next bar
    pmb.step(sid, 5)
    print(pmb.get_session_state(sid)["positions"])
    print(pmb.get_summary(sid))
```

What comes back: ten daily bars; the 2025-03-24 chain with bid, ask, IV and
delta per contract; the ACME earnings story of that evening (each article says
whether it carries the `full` text, a `summary` or only the `headline`); one
earnings report; and a 100-share position.

## 5. Connect an agent over MCP

The hub serves 69 MCP tools at `/mcp/`. For Claude Code:

```bash
claude mcp add --transport http qfinzero http://localhost:19777/mcp/ \
  --header "Authorization: Bearer $QFZ_API_KEY"
```

or in any MCP client configuration:

```json
{ "mcpServers": { "qfinzero": {
    "url": "http://localhost:19777/mcp/",
    "headers": { "Authorization": "Bearer qfz_…" } } } }
```

Ask it, for example, *"How did ACME trade around its 2025-03-24 earnings, and
what did the option chain look like before the report?"* The
[MCP tool reference](mcp-tools.md) lists every tool.

## 6. Replay without look-ahead

Add one header and every data tool answers as of that moment, enforced by the
server whatever the agent asks for:

```json
"headers": { "Authorization": "Bearer qfz_…", "X-QFZ-As-Of": "2025-03-24T14:00:00Z" }
```

At 10:00 ET on 2025-03-24 the agent sees daily bars up to 2025-03-21 only. To
lock to a trading session instead, create a PMB session and send
`"X-QFZ-Session": "sess_…"`: the lock then moves with the session's clock. The
chat in the console does the same with its *cutoff* time. Details:
[Platform guide, time lock](platform-guide.md#1-the-time-lock).

## Next

- [QFZView](qfzview.md): charts with trading sessions, option chains, any date.
- [Broker terminal](pmb/broker-terminal.md): trade a day minute by minute, overnight included.
- [Agent benchmark](bench.md): `qfz-bench oracle` checks an installation, `qfz-bench run` scores a model.
- [Data setup](data-setup.md) and [Data adapters](data-adapters.md): your own massive, Databento or Tushare data.
- [Configuration](configuration.md) and [Deployment and operations](operations.md).
