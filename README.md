> 中文: [docs/cn/README.md](docs/cn/README.md)

# QFinZero

**A Unified Trading Environment for LLM Agents**

QFinZero unifies price data, event/news retrieval, and brokerage simulation behind consistent, time-aligned APIs so LLM agents can query, reason, and trade in a coherent environment.

> Haochen Luo1*, Binh Minh An1, Ho Tin Ko2, Junjie Xu5, Pok Hin Tang1, Wang Chak Wong1, Yifan Li1, Yuan Gao1, Zhengzhao Lai4, Yuan Zhang3, Chen Liu1
>
> 1 City University of Hong Kong, 2 Yuen Long Merchants Association Secondary School, 3 Shanghai University of Finance and Economics, 4 University of Science and Technology of China, 5 The Chinese University of Hong Kong (Shenzhen)
>
> Correspondence: chester.hc.luo@my.cityu.edu.hk, zhang.yuan@sufe.edu.cn, chen.liu@cityu.edu.hk

> [!NOTE]
> **v1.0.0 is archived.** This release is frozen as the version described in
> our ACL 2026 System Demonstrations paper. We are building the next version
> of QFinZero with more powerful functions; this branch receives fixes only.

## Abstract

Large language model (LLM) agents are increasingly applied to financial decision-making tasks that require interaction with external tools such as market data, news, and trade execution. Existing systems are fragmented across task-specific APIs, which introduces inconsistent schemas, brittle integration, and weak reproducibility. QFinZero addresses this gap with a unified trading environment that standardizes three core capabilities: multi-frequency market and derivatives data access (UPQ), structured news and event retrieval (ESP), and a stateful brokerage simulator with explicit order lifecycle management (PMB). All tools expose consistent JSON schemas and time-aligned interfaces, enabling agents to autonomously retrieve information, manage portfolio state, and execute trades within a coherent framework. By abstracting financial interaction into composable, agent-invokable primitives, QFinZero reduces engineering overhead and supports reproducible evaluation with deterministic replay and comprehensive logging.

## What is in v1.0

- **Market data (UPQ, Rust).** Daily and minute bars and minute BBO for US
  stocks (regular, pre-market, after-hours and the Blue Ocean overnight
  session), China A-shares, OPRA options with intraday chains and Greeks,
  futures on CME session dates, crypto, FX and Treasury yields. Prices are
  stored as traded; splits and dividends are applied on read.
- **News and events (ESP).** Benzinga and Tushare news (each article says
  whether it has the full text, a summary or only a headline), earnings and
  macro calendars, all point-in-time.
- **Paper broker (PMB).** A step-driven simulator: market, limit and stop
  orders with regular, extended and overnight hours, margin, options filled
  against the quote, futures with daily settlement, checkpoints and
  deterministic replay.
- **Time lock.** Bind a connection to a trading session or a fixed time and
  every data tool answers as of that moment, enforced by the server.
- **For agents.** 69 MCP tools on one endpoint, API keys with scopes, a chat
  console that works with any OpenAI- or Anthropic-compatible model, a factor
  research DSL and a benchmark of 104 tasks (`qfz-bench`).
- **Console.** QFZView charts with session shading and option chains, a broker
  terminal, news, calendars, a data-availability map and data setup.
- **Data platform.** `qfz-data` downloads and converts massive, Databento and
  Tushare data, indexes raw files in place, and ships a synthetic sample so
  everything runs without a vendor account.

## Quick start

```bash
git clone https://github.com/CityU-MLO/qfinzero && cd qfinzero
export QFZ_ADMIN_PASSWORD='choose-a-long-password'
docker compose up -d          # hub, all services, web UI and the synthetic sample
# open http://localhost:19777 and sign in as admin
```

Then create an API key and query it from curl, Python or an MCP client:

```python
from qfinzero.clients.upq import UPQClient       # export QFZ_API_KEY=qfz_…

with UPQClient("http://localhost:19777/svc/upq") as upq:
    print(upq.stock_daily(["ACME"], "2025-03-17", "2025-03-28"))
```

- [Quick start](docs/en/quickstart.md): API key, REST, Python clients, MCP and time lock in five minutes.
- [Getting started](docs/en/getting-started.md): installing from source and a tour of the console.

## Architecture

QFinZero runs as one server on one port (`19777`). The hub supervises the
services on localhost and serves the web UI, the raw service APIs and the MCP
endpoint:

```
        LLM agent / user / MCP client
                     │
                     v
   ┌──────────────────────────────────────────┐
   │       qfinzero-server  :19777            │
   │  /  web UI     /mcp  MCP tools            │
   │  /auth  sign-in, keys    /svc/*  REST     │
   └───┬─────┬─────┬──────┬──────────┬────────┘
       v     v     v      v          v       (localhost, supervised)
     UPQ   ESP   PMB   playground  data-admin
    (Rust)   │     │
       ▲     v     │
       │  MongoDB  │
       │  + SQLite │
       └───────────┘  PMB reads market data from UPQ
```

| Path | Serves |
|------|--------|
| `/` | landing page, `/login`, the console and `/docs` |
| `/auth/*` | sign-in, API keys, users |
| `/svc/upq/*`, `/svc/esp/*`, `/svc/pmb/*` | market data, news and events, paper broker (REST) |
| `/svc/playground/*`, `/svc/data-admin/*` | chat backend, data administration |
| `/mcp` | MCP server (streamable HTTP) |
| `/health` | hub and every child |

The console, `/svc/*` and `/mcp` need a signed-in user or an API key; roles
are viewer, researcher and admin. See the
[platform guide](docs/en/platform-guide.md) for the time lock, trading
sessions, quotes, research and accounts.

## Documentation

The web UI serves all of it as a searchable, bilingual doc hub at `/docs`.

- **Start:** [Quick start](docs/en/quickstart.md) · [Getting started](docs/en/getting-started.md) · [Platform guide](docs/en/platform-guide.md)
- **Guides:** [Chat](docs/en/chat.md) · [Market data for agents](docs/en/upq/agent-guide.md) · [Trading for agents](docs/en/pmb/agent-guide.md) · [QFZView](docs/en/qfzview.md) · [Broker terminal](docs/en/pmb/broker-terminal.md) · [Agent benchmark](docs/en/bench.md) · [Sample dataset](docs/en/sample-data.md)
- **Data:** [Data setup](docs/en/data-setup.md) · [Data adapters](docs/en/data-adapters.md) (massive, Databento, Tushare)
- **Reference:** [MCP tools](docs/en/mcp-tools.md) · [UPQ](docs/en/upq/README.md) ([OpenAPI](docs/upq/openapi.yaml)) · [ESP](docs/en/esp/README.md) ([OpenAPI](docs/esp/openapi.yaml)) · [PMB](docs/en/pmb/README.md) ([OpenAPI](docs/pmb/openapi.yaml)) · [Configuration](docs/en/configuration.md) · [Time zones](docs/en/conventions/timezone.md)
- **Operations:** [Deployment and operations](docs/en/operations.md) · [Changelog](CHANGELOG.md)

## Project structure

```
qfinzero/          Python package: hub (server/), auth, data pipeline (pipeline/, index/, admin/),
                   research, benchmark (bench/), sample data (sample/), clients
clients/           UPQ, ESP and PMB Python clients (qfinzero.clients.*)
mcp/               the MCP server
infra/upq/         UPQ, the market-data service (Rust workspace)
infra/esp/         ESP, news and events (FastAPI)
infra/pmb/         PMB, the paper broker (FastAPI)
infra/playground/  chat backend (FastAPI, LangGraph)
infra/data-admin/  data administration service
infra/dashboard-web/  web UI (Next.js)
docs/              documentation (en, cn) and OpenAPI documents
scripts/, docker/  service scripts, container entry point
```

Data lives outside the repository under `QFZ_DATA_ROOT` (default
`/data/qfinzero`): UPQ storage in `upq/`, ESP databases in `esp/`, state in
`_state/`.

## Citation

If you use QFinZero, please cite:

```bibtex
@inproceedings{luo2026qfinzero,
  title={QFinZero: A Unified Financial Toolchain for LLM-Based Trading Agents},
  author={Luo, Haochen and Yifan, LI and Ko, Ho Tin and Minh, An Binh and Xu, Junjie and Hin, Tang Pok and Wong, Wang Chak and Yuan, Gao and Lai, Zhengzhao and Zhang, Yuan and others},
  booktitle={Proceedings of the 64th Annual Meeting of the Association for Computational Linguistics (Volume 3: System Demonstrations)},
  pages={68--77},
  year={2026}
}
```

## License

MIT License
