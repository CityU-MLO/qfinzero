# QFinZero MCP Server

Exposes all QFinZero tools as [MCP (Model Context Protocol)](https://modelcontextprotocol.io) tools,
enabling Claude and other LLM systems to directly call the UPQ, NPP, and PMB services.

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
        "QFINZERO_NPP_URL": "http://127.0.0.1:19330",
        "QFINZERO_PMB_URL": "http://127.0.0.1:19320"
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
| `QFINZERO_NPP_URL`   | `http://127.0.0.1:19330` | News/events service |
| `QFINZERO_PMB_URL`   | `http://127.0.0.1:19320` | Trading broker      |

## Available Tools

### UPQ — Market Data (7 tools)

| Tool | Description |
|------|-------------|
| `upq_health` | Check service health |
| `upq_stock_daily` | Daily OHLCV bars for stocks |
| `upq_stock_minute` | Minute-level OHLCV bars |
| `upq_option_chain` | Full option chain for an underlying |
| `upq_option_contract` | Price history for a specific option contract |
| `upq_rates` | US Treasury yield rates |
| `upq_make_opra` | Build an OPRA contract identifier string |

### NPP — News & Events (8 tools)

| Tool | Description |
|------|-------------|
| `npp_health` | Check service health and data freshness |
| `npp_query_events` | Unified event search (news, earnings, macro) |
| `npp_get_event` | Fetch a single event by ID |
| `npp_stream_events` | Incremental polling since a cursor |
| `npp_econ_calendar` | US economic events calendar |
| `npp_earnings_calendar` | Earnings release calendar |
| `npp_next_triggers` | Next high-importance events for agent wakeup |
| `npp_news_body` | Full article body |
| `npp_timeline` | Time-bucketed event summary |

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
   b. npp_query_events  → check news/earnings at current time
   c. upq_stock_daily   → get historical context if needed
   d. pmb_buy_stock / pmb_sell_stock  → place orders
   e. break if not is_running
4. pmb_get_summary      → evaluate performance
```
