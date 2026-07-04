> 中文: [../docs/cn/mcp/README.md](../docs/cn/mcp/README.md)


# QFinZero MCP Server

Exposes all QFinZero tools as [MCP (Model Context Protocol)](https://modelcontextprotocol.io) tools,
enabling Claude and other LLM systems to directly call the UPQ, ESP, and PMB services.

## Prerequisites

1. QFinZero services must be running (`scripts/run_all.sh`)
2. Python 3.10+
3. Install MCP dependencies:

```bash
pip install -r mcp/requirements.txt
# or if using the project's existing venv:
pip install "mcp[cli]>=1.0.0"
```

## Running the Server

```bash
# Stdio transport (default — used by Claude Desktop and most MCP clients)
python mcp/server.py

# Or via the MCP CLI
mcp run mcp/server.py
```

### Transports

The server selects its transport from `QFINZERO_MCP_TRANSPORT`:

| Value | Description |
|-------|-------------|
| `stdio` (default) | Local clients (Claude Desktop / Claude Code) |
| `streamable-http` | Modern HTTP transport for remote / multi-client use; listens on `QFINZERO_MCP_HOST:QFINZERO_MCP_PORT` (default `127.0.0.1:19360`) |
| `sse` | Legacy HTTP + SSE transport |

```bash
# Run over modern streamable HTTP
QFINZERO_MCP_TRANSPORT=streamable-http QFINZERO_MCP_PORT=19360 python mcp/server.py
```

### Resources & Prompts

Beyond the 37 tools, the server exposes MCP **resources** and a **prompt**:

| Kind | Name | Description |
|------|------|-------------|
| resource | `qfinzero://ports` | Canonical service port map (193xx) + service URLs |
| resource | `qfinzero://data/freshness` | Live UPQ data freshness (latest dates, record counts) |
| resource | `qfinzero://health` | Combined UPQ/ESP/PMB health |
| prompt | `trading_session` | Scaffolds a full paper-trading session loop |

## Connecting to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "qfinzero": {
      "command": "python",
      "args": ["/path/to/qfinzero/mcp/server.py"],
      "env": {
        "QFINZERO_UPQ_URL": "http://127.0.0.1:19350",
        "QFINZERO_ESP_URL": "http://127.0.0.1:19330",
        "QFINZERO_PMB_URL": "http://127.0.0.1:19380"
      }
    }
  }
}
```

## Connecting to Claude Code (CLI)

```bash
claude mcp add qfinzero python /path/to/qfinzero/mcp/server.py
```

## Configuration

Service URLs can be set via environment variables:

| Variable              | Default                   | Description         |
|-----------------------|---------------------------|---------------------|
| `QFINZERO_UPQ_URL`   | `http://127.0.0.1:19350` | Market data service |
| `QFINZERO_ESP_URL`   | `http://127.0.0.1:19330` | News/events service |
| `QFINZERO_PMB_URL`   | `http://127.0.0.1:19380` | Trading broker      |

## Available Tools

### UPQ — Market Data (7 tools)

| Tool | Description |
|------|-------------|
| `upq_health` | Check service health |
| `upq_stock_daily` | Daily OHLCV bars for stocks |
| `upq_stock_minute` | Minute-level OHLCV bars |
| `upq_option_chain` | Full option chain for an underlying (supports `include_greeks`; exact-expiry miss auto-fallbacks to nearest expiry) |
| `upq_option_contract` | Price history for a specific option contract (supports `include_greeks`) |
| `upq_rates` | US Treasury yield rates |
| `upq_make_opra` | Build an OPRA contract identifier string |

### ESP — News & Events (8 tools)

| Tool | Description |
|------|-------------|
| `esp_health` | Check service health and data freshness |
| `esp_query_events` | Unified event search (news, earnings, macro) |
| `esp_get_event` | Fetch a single event by ID |
| `esp_stream_events` | Incremental polling since a cursor |
| `esp_econ_calendar` | US economic events calendar |
| `esp_earnings_calendar` | Earnings release calendar |
| `esp_next_triggers` | Next high-importance events for agent wakeup |
| `esp_news_body` | Full article body |
| `esp_timeline` | Time-bucketed event summary |

### PMB — Paper Trading Broker (13 tools)

| Tool | Description |
|------|-------------|
| `pmb_health` | Check service health |
| `pmb_create_account` | Create a paper trading account |
| `pmb_get_account` | Get account state (cash, equity, margin) |
| `pmb_get_positions` | List open positions |
| `pmb_get_orders` | Query orders |
| `pmb_get_trades` | Query executed trades |
| `pmb_create_session` | Start a backtesting session |
| `pmb_step_session` | Advance simulation by N steps |
| `pmb_get_market` | Current market prices for session universe |
| `pmb_stop_session` | Stop session early |
| `pmb_get_summary` | Backtest performance metrics |
| `pmb_export_session` | Export session data (JSON/CSV) |
| `pmb_buy_stock` | Place stock buy order |
| `pmb_sell_stock` | Place stock sell order |
| `pmb_buy_option` | Place option buy order |
| `pmb_sell_option` | Place option sell order |
| `pmb_cancel_order` | Cancel an open order |

## Typical Agent Workflow

```
1. pmb_create_account   → get account_id
2. pmb_create_session   → get session_id
3. loop:
   a. pmb_step_session  → advance clock, get market data + events
   b. esp_query_events  → check news/earnings at current time
   c. upq_stock_daily   → get historical context if needed
   d. pmb_buy_stock / pmb_sell_stock  → place orders
   e. break if not is_running
4. pmb_get_summary      → evaluate performance
```
