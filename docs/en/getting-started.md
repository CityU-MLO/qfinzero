# Getting started

> 中文: [docs/cn/getting-started.md](../cn/getting-started.md)

This page takes you from nothing to a running QFinZero with data, a signed-in
console and an agent connected over MCP. It uses the bundled synthetic dataset,
so no data vendor account is needed. Plan for 10 minutes with Docker.

## 1. Run it

### With Docker (recommended)

Requirements: Docker 24 or newer.

```bash
git clone https://github.com/CityU-MLO/qfinzero && cd qfinzero
export QFZ_ADMIN_PASSWORD='choose-a-long-password'
docker compose up -d
```

The first build compiles the UPQ engine and the web UI and takes about 15
minutes. The first start writes the synthetic sample into the `qfz-data`
volume (about 25 seconds). Open <http://localhost:19777> and sign in as
`admin` with the password you exported.

### From source

Requirements: Python 3.10+, a Rust toolchain (stable), and Node 20 with pnpm 9
if you want the web UI.

```bash
pip install -e ".[server,pipeline]"
(cd infra/upq && cargo build --release -p upq-service)
(cd infra/dashboard-web && pnpm install && pnpm build)      # optional: the web UI
qfz-sample generate --out ./qfz-sample
QFZ_DATA_ROOT=./qfz-sample QFZ_ADMIN_PASSWORD='choose-a-long-password' qfz-server
```

`qfz-server` is the hub. It starts UPQ, ESP, PMB, the playground and the web UI
as child processes and serves everything on port 19777. `curl
http://127.0.0.1:19777/health` lists the children and whether each one is up.

`QFZ_ADMIN_PASSWORD` creates the `admin` account on the first start only. You
can drop it afterwards. Other ways to create the first admin are listed in the
[platform guide](platform-guide.md#6-accounts-roles-and-api-keys).

## 2. Look around the console

The sample is a fictional market: 20 tickers on the real NYSE calendar for
2025-01-02 to 2025-03-31. Minute data covers the last ten trading days
(2025-03-18 to 2025-03-31). See [Sample dataset](sample-data.md) for what is in it.

- **Broker**: open an account, then start a session on 2025-03-24 with the
  watchlist `ACME, QZSP, BOLT`. Press *Open market* and the clock steps minute
  by minute; place market or limit orders from the ticket. ACME reports
  earnings after that day's close, so its price gaps the next morning.
- **News** and **Calendar**: search `ACME`, or open the earnings calendar for
  March 2025.
- **Data availability**: which data exists per ticker and day on a continuous
  calendar (days without data stay empty, weekends are blank). Stocks and
  futures are two groups; write a future with a slash (`/CL`, `/ZN`), since roots
  clash with stock tickers. Expand a stock (▸) for its layers: stock data,
  options, news and company events; macro releases have their own lane. Drag
  the window in the overview below the map to move through the history, click
  a cell for that day and a ticker for the asset (levels, closes or settles,
  other series of a future).
- **Chat**: first add a model group under *Settings* (gear icon): choose
  OpenAI, Claude or Gemini · Antigravity, enter the base URL and key, and fetch
  the models. A Claude Code `settings.json`, `export ANTHROPIC_*` lines or a
  Codex `config.toml` can be imported directly. The chat agent uses the same
  MCP tools as external agents.
- **Docs**: this documentation, also available without signing in.

## 3. Connect an agent

1. Open **Account** and create an API key. Copy the `qfz_…` token (**Show** in the key list brings it back later).
2. Point any MCP client at the hub:

```json
{
  "mcpServers": {
    "qfinzero": {
      "url": "http://localhost:19777/mcp/",
      "headers": { "Authorization": "Bearer qfz_…" }
    }
  }
}
```

3. To replay the past without look-ahead, create a PMB session (in the
   console, or with `pmb_create_session`) and add `"X-QFZ-Session": "sess_…"`
   to the headers. Every data tool then answers as of that session's current bar.

The [MCP tool reference](mcp-tools.md) lists all tools and their parameters.

## 4. Check the installation

The benchmark's oracle solves every task through the public APIs. On a healthy
installation it scores 100%:

```bash
export QFZ_API_KEY=qfz_…
qfz-bench oracle --hub http://127.0.0.1:19777
```

With Docker, run it inside the container:
`docker compose exec qfinzero qfz-bench oracle --hub http://127.0.0.1:19777 --api-key qfz_…`.
To evaluate a model instead, see [Agent benchmark](bench.md).

## 5. Use your own data

Open **Data setup** (admins) to import Databento or massive files already on
the server, or to download with your key; see [Data setup utility](data-setup.md).
From the command line, `qfz-data` does the same, and `QFZ_DATA_ROOT` points the
hub at a data root. [Data adapters](data-adapters.md) covers
massive, Tushare and Databento. [Configuration](configuration.md) lists every
setting, and [Deployment and operations](operations.md) covers running
QFinZero for a team.
