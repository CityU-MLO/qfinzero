> English: [../../../mcp/README.md](../../../mcp/README.md)

# QFinZero MCP 服务器

将所有 QFinZero 工具暴露为 [MCP (Model Context Protocol)](https://modelcontextprotocol.io) 工具，
使 Claude 及其他 LLM 系统能够直接调用 UPQ、ESP 和 PMB 服务。

## 前置条件

1. QFinZero 服务必须处于运行状态（`scripts/run_all.sh`）
2. Python 3.10+
3. 安装 MCP 依赖：

```bash
pip install -r mcp/requirements.txt
# or if using the project's existing venv:
pip install "mcp[cli]>=1.0.0"
```

## 运行服务器

```bash
# Stdio transport (default — used by Claude Desktop and most MCP clients)
python mcp/server.py

# Or via the MCP CLI
mcp run mcp/server.py
```

### 传输方式

服务器根据 `QFINZERO_MCP_TRANSPORT` 选择其传输方式：

| 值 | 说明 |
|-------|-------------|
| `stdio`（默认） | 本地客户端（Claude Desktop / Claude Code） |
| `streamable-http` | 用于远程 / 多客户端场景的现代 HTTP 传输；监听 `QFINZERO_MCP_HOST:QFINZERO_MCP_PORT`（默认 `127.0.0.1:19360`） |
| `sse` | 旧版 HTTP + SSE 传输 |

```bash
# Run over modern streamable HTTP
QFINZERO_MCP_TRANSPORT=streamable-http QFINZERO_MCP_PORT=19360 python mcp/server.py
```

### 资源与提示词

除了 37 个工具之外，服务器还暴露了 MCP **资源**和一个**提示词**：

| 类型 | 名称 | 说明 |
|------|------|-------------|
| resource | `qfinzero://ports` | 规范的服务端口映射（193xx）+ 服务 URL |
| resource | `qfinzero://data/freshness` | 实时 UPQ 数据新鲜度（最新日期、记录数） |
| resource | `qfinzero://health` | 合并的 UPQ/ESP/PMB 健康状态 |
| prompt | `trading_session` | 搭建完整的模拟交易会话循环 |

## 连接到 Claude Desktop

添加到 `~/Library/Application Support/Claude/claude_desktop_config.json`：

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

## 连接到 Claude Code (CLI)

```bash
claude mcp add qfinzero python /path/to/qfinzero/mcp/server.py
```

## 配置

服务 URL 可通过环境变量设置：

| 变量              | 默认值                   | 说明         |
|-----------------------|---------------------------|---------------------|
| `QFINZERO_UPQ_URL`   | `http://127.0.0.1:19350` | 市场数据服务 |
| `QFINZERO_ESP_URL`   | `http://127.0.0.1:19330` | 新闻/事件服务 |
| `QFINZERO_PMB_URL`   | `http://127.0.0.1:19380` | 交易经纪商      |

## 可用工具

### UPQ — 市场数据（7 个工具）

| 工具 | 说明 |
|------|-------------|
| `upq_health` | 检查服务健康状态 |
| `upq_stock_daily` | 股票日线 OHLCV 数据 |
| `upq_stock_minute` | 分钟级 OHLCV 数据 |
| `upq_option_chain` | 标的的完整期权链（支持 `include_greeks`；精确到期日未命中时自动回退到最近到期日） |
| `upq_option_contract` | 特定期权合约的价格历史（支持 `include_greeks`） |
| `upq_rates` | 美国国债收益率 |
| `upq_make_opra` | 构建 OPRA 合约标识符字符串 |

### ESP — 新闻与事件（8 个工具）

| 工具 | 说明 |
|------|-------------|
| `esp_health` | 检查服务健康状态及数据新鲜度 |
| `esp_query_events` | 统一事件搜索（新闻、财报、宏观） |
| `esp_get_event` | 按 ID 获取单个事件 |
| `esp_stream_events` | 自游标以来的增量轮询 |
| `esp_econ_calendar` | 美国经济事件日历 |
| `esp_earnings_calendar` | 财报发布日历 |
| `esp_next_triggers` | 供 agent 唤醒的下一批高重要性事件 |
| `esp_news_body` | 完整文章正文 |
| `esp_timeline` | 按时间分桶的事件摘要 |

### PMB — 模拟交易经纪商（13 个工具）

| 工具 | 说明 |
|------|-------------|
| `pmb_health` | 检查服务健康状态 |
| `pmb_create_account` | 创建模拟交易账户 |
| `pmb_get_account` | 获取账户状态（现金、权益、保证金） |
| `pmb_get_positions` | 列出持仓 |
| `pmb_get_orders` | 查询订单 |
| `pmb_get_trades` | 查询已成交交易 |
| `pmb_create_session` | 启动回测会话 |
| `pmb_step_session` | 将模拟推进 N 步 |
| `pmb_get_market` | 会话标的池的当前市场价格 |
| `pmb_stop_session` | 提前停止会话 |
| `pmb_get_summary` | 回测绩效指标 |
| `pmb_export_session` | 导出会话数据（JSON/CSV） |
| `pmb_buy_stock` | 提交股票买入订单 |
| `pmb_sell_stock` | 提交股票卖出订单 |
| `pmb_buy_option` | 提交期权买入订单 |
| `pmb_sell_option` | 提交期权卖出订单 |
| `pmb_cancel_order` | 取消未成交订单 |

## 典型 Agent 工作流

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
