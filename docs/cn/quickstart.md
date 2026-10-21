# 快速上手

> English: [docs/en/quickstart.md](../en/quickstart.md)

五分钟从零到一个能读行情、新闻和期权链，并在模拟券商上交易的 agent。下面的一切都跑在 Docker 镜像自带的合成样例数据上（代码 `QZSP`、`ACME`、`BOLT` 等，2025-01-02 到 2025-03-31），不需要任何数据商账号。想完整逛一遍控制台，看[入门指南](getting-started.md)。

## 1. 启动 QFinZero

```bash
git clone https://github.com/CityU-MLO/qfinzero && cd qfinzero
export QFZ_ADMIN_PASSWORD='choose-a-long-password'
docker compose up -d                 # 第一次构建大约 15 分钟
curl http://localhost:19777/health   # 所有子服务都是 "up"
```

打开 <http://localhost:19777>，用 `admin` 登录。

## 2. 拿一个 API key

agent 和脚本用 key 签名请求。在 **账户** 页面创建，或者用命令行（token 只显示一次）：

```bash
docker compose exec qfinzero qfz-auth create-key admin --name quickstart
export QFZ_API_KEY=qfz_…
```

## 3. 调 REST 接口

每个服务都在 hub 的 `/svc/<服务>` 下面：

```bash
H="Authorization: Bearer $QFZ_API_KEY"
curl -H "$H" "http://localhost:19777/svc/upq/stock/daily?tickers=ACME&start=2025-03-17&end=2025-03-28"
curl -H "$H" "http://localhost:19777/svc/upq/option/chain_snapshot?underlying=ACME&at=2025-03-24T19:30:00Z&expiry_max=2025-04-04&include_greeks=true"
curl -H "$H" -X POST http://localhost:19777/svc/esp/esp/news/search \
     -H 'content-type: application/json' \
     -d '{"tickers": ["ACME"], "start_utc": "2025-03-24T00:00:00Z", "end_utc": "2025-03-26T00:00:00Z"}'
```

## 4. 用 Python 客户端

在仓库里 `pip install -e .` 会装上 `qfinzero` 和它的客户端。设置了 `QFZ_API_KEY` 后，客户端会自动签名每个请求（也可以传 `api_key=`）：

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
    pmb.step(sid)                                   # 美东 09:30 那根 K 线
    pmb.buy(sid, acct["account_id"], "ACME", 100)   # 市价单在下一根 K 线成交
    pmb.step(sid, 5)
    print(pmb.get_session_state(sid)["positions"])
    print(pmb.get_summary(sid))
```

会拿到：十根日线；2025-03-24 的期权链，每个合约带买卖价、IV 和 Delta；当晚 ACME 财报相关的新闻（每篇都标出有 `full` 全文、`summary` 摘要还是只有 `headline` 标题）；一条财报记录；以及 100 股的持仓。

## 5. 用 MCP 接入 agent

hub 在 `/mcp/` 提供 69 个 MCP 工具。Claude Code 里：

```bash
claude mcp add --transport http qfinzero http://localhost:19777/mcp/ \
  --header "Authorization: Bearer $QFZ_API_KEY"
```

或者在任意 MCP 客户端的配置里：

```json
{ "mcpServers": { "qfinzero": {
    "url": "http://localhost:19777/mcp/",
    "headers": { "Authorization": "Bearer qfz_…" } } } }
```

可以这样问它：*"ACME 在 2025-03-24 财报前后走势如何？财报发布前期权链是什么样的？"* 全部工具见 [MCP 工具参考](../en/mcp-tools.md)。

## 6. 无前视地回放

加一个 header，所有数据工具都只回答那个时刻之前的数据，由服务器强制执行，agent 怎么问都一样：

```json
"headers": { "Authorization": "Bearer qfz_…", "X-QFZ-As-Of": "2025-03-24T14:00:00Z" }
```

在 2025-03-24 美东 10:00，agent 只能看到截至 2025-03-21 的日线。想按交易会话锁定，就创建一个 PMB 会话并发送 `"X-QFZ-Session": "sess_…"`：锁会跟着会话的时钟走。控制台里的对话用的是同一个机制（*截止时间*）。详见[平台指南：时间锁](platform-guide.md)。

## 下一步

- [QFZView](qfzview.md)：带交易时段的图表、期权链、跳转到任意日期。
- [交易终端](pmb/broker-terminal.md)：逐分钟交易一天，包括夜盘。
- [Agent 基准测试](bench.md)：`qfz-bench oracle` 检查安装，`qfz-bench run` 给模型打分。
- [数据导入](data-setup.md) 和 [数据适配器](data-adapters.md)：接入自己的 massive、Databento 或 Tushare 数据。
- [配置](configuration.md) 和 [部署与运维](operations.md)。
