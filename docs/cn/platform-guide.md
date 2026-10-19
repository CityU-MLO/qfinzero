# 平台指南：时间锁、交易时段、日内交易、研究与账号

> English: [docs/en/platform-guide.md](../en/platform-guide.md)

本指南介绍基础 API 之外，agent 和研究者需要了解的内容：QFinZero 如何让每次查询都符合时间点，交易时段和委托时间怎么运作，期权如何按报价成交，如何挖掘日内因子，以及如何带账号运行服务器。

## 1. 时间锁

在模拟中交易的 agent 只能看到它决策那根 bar 时已知的信息。QFinZero 在服务器端强制执行这一点，而不是靠提示词。

**可见性规则（UPQ `as_of`）。** 每个 UPQ 数据接口都接受 `as_of`。取值可以是 ISO 时间，不带时区时按 UTC 处理；也可以是纳秒整数。只返回在 `as_of` 时已经确定的数据：

| 数据 | 可见条件 |
|------|----------|
| 从 `t` 开始的分钟线或分钟报价 | `t + 60s <= as_of` |
| D 日股票日线 | `as_of >= D 16:00 ET` |
| D 日期权日线和收盘期权链 | `as_of >= D 16:15 ET` |
| 利率、分红 | 截至 `as_of` 所在交易日 |

用 `UPQ_AS_OF=<时间>` 启动 UPQ 会给所有请求设一个上限。请求只能要求更早的 `as_of`，不能更晚。这个值无法解析时，UPQ 不返回任何数据。

**绑定 session。** PMB session 的时钟会自动转换成 `as_of`：分钟级 session 取当前 bar 的收盘时刻，日级 session 取当前交易日的 16:00 ET。绑定哪个 session 按以下优先级决定：

1. MCP 或 HTTP 连接的 `X-QFZ-Session` header。基准测试的执行器设置它，agent 无法修改；
2. 环境变量 `QFZ_TIME_LOCK_SESSION`，适合每个 episode 起一个 MCP 服务；
3. 数据工具的 `session_id` 参数。

绑定 session 后：
- `upq_*` 工具会带上 `as_of`。
- ESP 工具以 `now_utc = as_of` 运行，并把查询窗口的结束时间截到 `as_of`。
- `research_*` 工具会截断日期范围。

设置 `QFZ_REQUIRE_SESSION=1` 后，没有绑定任何 session 的数据查询一律拒绝。

```json
{ "mcpServers": { "qfinzero": {
    "url": "https://your-host/mcp/",
    "headers": { "Authorization": "Bearer qfz_…", "X-QFZ-Session": "sess_3f2a9c1e" } } } }
```

日内 Greeks 同样符合时间点：使用同一时刻标的的分钟收盘价，而不是当天收盘价。

## 2. 交易时段与委托时间

PMB 把美股交易时间分为四段（美东时间）：

| 时段 | 时间 | 归属交易日 |
|------|------|------------|
| 夜盘 | 20:00–04:00 | 下一个工作日 |
| 盘前 | 04:00–09:30 | 当天 |
| 常规 | 09:30–16:00 | 当天 |
| 盘后 | 16:00–20:00 | 当天 |

每笔委托都有 `trading_hours`：

- `REGULAR`（默认）：只在常规时段成交，任何单型都可以。
- `EXTENDED`：盘前、常规和盘后，只接受限价单。
- `OVERNIGHT`：全部四段（24/5），只接受限价单。

期权只在常规时段交易。`time_in_force` 会被执行：
- `DAY` 单在它首次可成交的那个交易日结束时过期。收盘后才下的常规时段单会等到下一个交易日。
- `GTD` 单在 `expire_ts` 过期。
- `GTC` 单一直有效。

`execution_config.partial_fill = {"enabled": true, "max_fill_ratio_per_tick": 0.1}` 会把每次成交量限制在该 bar 成交量的一定比例内；按报价成交时，改为限制在挂单显示的数量内。`enforce_trading_hours: false` 恢复旧行为：每根 bar 都能成交，委托永不过期。

step 的返回结果会带上 `clock.segment` 和 `clock.trading_date`。

**夜盘数据。** Databento 适配器能读取 Blue Ocean（`OCEA.MEMOIR`）文件，所以夜盘分钟线可以和任何供应商的日盘 bar 并存。日线从不包含夜盘成交。

**只在需要时唤醒 agent。** 分钟级 session 每天有 390 根常规时段 bar。`pmb_step_until`（REST 接口为 `POST /v1/sessions/{id}/step_until`）会一直推进，直到下面任一条件先发生：
- 有成交；
- 价格触发，例如 `{"symbol": "SPY", "op": ">=", "price": 600}`；
- 到达指定时间（`until_ts`）；
- 进入某个时段，例如 `stop_on_segment: "REGULAR"` 会跳到下一次开盘；
- 达到 `max_steps`。

返回委托和成交事件、最后一个行情 tick 和账户状态。

## 3. 报价与期权成交

两个报价存储保存每分钟结束时的最优买卖价：`stock_quote_minute` 和 `option_quote_minute`，来自 Databento 的 `cmbp-1`、`cbbo-1s/1m` 和 `bbo-1s/1m`。没有变化的分钟不存储，读取时沿用上一条报价。

| 接口 | MCP 工具 | 内容 |
|------|----------|------|
| `/stock/quote` | `upq_stock_quote` | 股票分钟 NBBO |
| `/option/quote` | `upq_option_quote` | 单个合约的分钟 NBBO |
| `/option/chain_snapshot` | `upq_chain_snapshot` | 某一时刻的期权链：最近成交、当日累计成交量、买卖价和中间价、按中间价计算的 Greeks |

分钟级 session 会加载每个期权的报价。`execution_config.option_fill_model = "quote"`（默认）时：

- 市价单在 bar 开盘时，买入按卖价成交，卖出按买价成交；
- 能立即成交的限价单按报价成交；挂着的限价单只有在该 bar 内有成交价穿过限价时，才按限价成交；
- 只要有报价，没有成交的分钟也能成交；
- 持仓按中间价估值。

`option_fill_model = "bar"` 保留只看 bar 的旧模型，用 `option_spread_pct` 近似点差。

## 4. 期货与保证金

期货由 Databento 适配器（CME Globex `GLBX.MDP3` 及其他期货交易所）写入 `future_minute`、`future_daily`（带 `settle`）
和 `future_quote_minute`，按 CME 交易时段分区：前一天美东 18:00 到当天 17:00。代码是单一合约（`ZNZ6`），
或主力连续数据的品种代码（`ZN`）。

| 接口 | MCP 工具 | 内容 |
|------|----------|------|
| `/future?tickers=&roots=` | `upq_future_minute` | 分钟线；`roots=ZN` 返回该品种的所有序列 |
| `/future/daily` | `upq_future_daily` | 每个交易时段一根，带 `settle`，美东 17:00 后才可见 |
| `/future/quote` | `upq_future_quote` | 每个保留分钟的最优买卖价 |

用 `universe.futures`（`pmb_create_session` 的 `future_universe`）把期货放进会话，或之后调用
`POST /v1/sessions/{id}/add_futures`；下单时用 `instrument: {"type": "FUTURE", "symbol": "ZN"}`（`pmb_trade_future`）。
期货在交易所有 bar 的每一分钟都可成交，不受委托的 `trading_hours` 限制；载入报价时按盘口成交。

保证金按交易所清算的方式计算：

- **不付权利金。** 成交只扣手续费（`fee_model.future_fee_per_contract`，默认每边 1.50），成交价按合约最小变动价位取整。
- **初始保证金。** 开仓需要 `数量 × 初始保证金` 的可用资金：权益减去已持仓位的初始保证金，不足时以
  `INSUFFICIENT_MARGIN` 拒单。
- **每日结算。** 每个交易时段的最后一根 bar（日线会话为每根 bar）按该时段的 `settle` 结算：
  `数量 × (结算价 − 上次结算价) × 合约乘数` 以 `VARIATION_MARGIN` 事件转入现金。两次结算之间，浮动盈亏计入权益，
  持仓按 bar 收盘价或报价中间价估值。
- **追加保证金。** 权益低于维持保证金时发出带 `call_amount` 的 `RISK_EVENT`，禁止开新仓（`MARGIN_RESTRICTED`），
  平仓单照常成交。权益回到**初始**保证金才算补足。经过 `margin_config.future_margin_call_sessions` 次结算
  （默认 1；0 表示从不强平）仍未补足时，按结算价强制平仓（`LIQUIDATION` 成交）。

每手保证金来自合约规格：固定的 `maintenance_margin`（美元，即交易所公布的数值），或按上次结算价名义价值的
`margin_rate` 计算；`初始 = 维持 × initial_ratio`（1.10）。内置规格覆盖常见 CME 合约（ES、NQ、YM、RTY 及其微型合约，
CL、NG、RB、HO、GC、SI、HG、PL、ZT、ZF、ZN、TN、ZB、UB、6E、6J、6B、6A、6C、ZC、ZS、ZW），费率为近似值。
请在开户时（*模拟交易 → 开立账户 → 期货保证金*）或在 `margin_config.future_specs` 中按品种设置真实数值：
只替换给出的字段，例如 `{"ZN": {"maintenance_margin": 2100}}`（不在内置列表中的品种至少要给出 `multiplier`）。
没有规格的品种会被拒单。`GET /v1/futures/specs` 列出内置规格；`GET /v1/sessions/{id}/state` 的 `futures_specs`
列出会话中各合约的规格和按当前价格计算的每手保证金。账户的股票杠杆决定购买力：`权益 / stock_initial − 初始保证金`（Reg-T 50% 即 2 倍）。

**换月。** 主力连续序列（`ZN`）会不时切换到下一个合约，它的 bar 带有背后合约的 `instrument_id`。合约变化时，持仓按新合约的
第一个价格随之移仓（`FUTURE_ROLL` 事件）：开仓价和结算基准平移同样的价差，浮动盈亏延续，两个合约之间的价差不计为盈亏。
**结算价**在数据中有交易所结算价时使用它（Databento `statistics`，`settle_source = 'exchange'`），否则用时段最后成交价。
交易终端显示每个期货持仓的保证金和上次结算以来的浮动盈亏、每日结算记录、换月记录，并在追加保证金未补足时显示提示条。

暂未模拟：单一合约的到期（请交易连续序列，或在最后交易日前平仓）以及跨品种价差的保证金减免。

## 5. 日内研究

`qfinzero.research` 用 DuckDB 直接读取 UPQ 存储。一个因子就是一个表达式：

```bash
qfz-research fields                                   # 字段和函数列表
qfz-research eval "cs_rank(-pct(close, 15))" --start 2026-08-10 --end 2026-08-21 \
    --universe 500 --horizons 5,15,30
qfz-research backtest "cs_rank(-pct(close, 15))" --start 2026-08-10 --end 2026-08-21 \
    --rebalance 30 --fraction 0.1 --cost-bps 0.5
```

| 元素 | 含义 |
|------|------|
| 字段 | `open high low close volume transactions vwap ret minute`；有股票报价时还有 `bid ask mid spread imbalance` |
| 时间序列 | `ts_mean ts_sum ts_std ts_min ts_max ts_zscore (x, n)`、`ts_corr ts_cov (x, y, n)`、`delay delta pct (x, n)` |
| 截面 | `cs_rank cs_zscore cs_demean (x)` |
| 标量 | `abs log sign sqrt`、`max min (a, b)`、`+ - * /` |

时间点规则内置在语言里：

- 窗口在当前 bar 结束，必须填满，每个交易日重置（除非加 `--cross-day`）；
- `delay`、`delta`、`pct` 要求 `n >= 1`；
- `t` 时刻的信号在 `t+1` 开盘入场；
- 股票池按前一交易日成交额取前 N 名。

**评估**输出 IC、Rank IC、ICIR、t 值、分层收益、多空价差、最高层换手率和按小时分组的 IC。各个预测周期互不重叠。

**回测**规则如下：
- 每 k 根 bar 再平衡一次。
- 等权持有排名最高的一部分股票；做多空时同时做空最低的一部分。
- 收盘前平仓。
- 成本按 `cost_bps` 加上报价的半个点差计算。

在参考服务器上，500 只股票、10 天分钟数据的评估约需 4 秒。

agent 通过 `research_eval_factor` 和 `research_backtest` 使用同一个引擎。这两个工具受 `QFZ_RESEARCH_MAX_DAYS`（默认 40 个交易日）和 `QFZ_RESEARCH_MAX_UNIVERSE`（默认 1000）限制，并遵守时间锁。

## 6. 账号、角色与 API key

hub 对网站、`/svc/*` 和 `/mcp` 的每个请求做身份认证。

| 角色 | 权限 |
|------|------|
| viewer | 查看数据、session 和控制台 |
| researcher | 另外可以交易、做研究、使用 MCP |
| admin | 另外可以管理数据源、用户和 key |

浏览器在 `/login` 登录，得到 HttpOnly 的 session cookie。agent 和脚本使用 API key（`Authorization: Bearer qfz_…` 或 `X-API-Key`），可以在账号页或用 `qfz-auth create-key` 创建。key 以其所有者的角色行事，也可以更窄（见下文 *分发 API key*）。

PMB 按创建者隔离账户和 session：其他人访问返回 404，admin 能看到全部。hub 会剥除客户端发来的身份 header，只把验证过的 `x-qfz-user` 和 `x-qfz-role` 转发给各服务。

### 分发 API key

key 的权限可以比所有者更窄。在账号页创建 key，或由管理员在 *用户* 页面发给他人时，可以设置：

| 设置 | 作用 |
|---|---|
| scopes | key 能访问的服务；访问其他服务返回 `403` |
| 只读 | 只能查询：不能下单、建 session、对话，也不能调用会改变状态的 MCP 工具 |
| 到期 | 过了这个日期 key 失效（`401`） |
| 速率限制 | 每分钟请求数；超过时返回 `429` 并带 `Retry-After` |
| 备注 | 给谁用、在哪里运行 |

| scope | 可访问 | 所有者最低角色 |
|---|---|---|
| `market-data` | UPQ（`/svc/upq`、`/api/upq`、`/api/coverage`） | viewer |
| `events` | ESP（`/svc/esp`、`/api/esp`） | viewer |
| `trading` | PMB（`/svc/pmb`、`/api/pmb`） | researcher |
| `mcp` | `/mcp`；其中的工具取决于其他 scope（`upq_*`/`research_*` 需要 `market-data`，`esp_*` 需要 `events`，`pmb_*` 需要 `trading`） | researcher |
| `chat` | 对话助手 | researcher |
| `admin` | 数据管理、用户和 key | admin |

key 的权限永远不超过所有者的角色：viewer 不能持有 `trading`，所有者被降级后，他名下所有 key 的权限也随之收窄。预设覆盖常见情况（*只读数据*：行情和事件，只读；*MCP agent*：MCP、数据、事件和交易；*完整权限*：所有者拥有的全部 scope，即 scope 出现之前创建的 key 的行为）。token 只显示一次，并附带环境变量、curl、Python 和 MCP 客户端配置的代码片段。

key 列表显示最近 14 天每天的请求数（以及被拒绝的次数）、最近一次使用时间和发放人。scopes、只读、到期和速率限制之后都可以修改，不需要换 token；吊销在下一个请求时生效。

```bash
qfz-auth create-key bob --name class-feed --scopes market-data,events \
    --read-only --expires-days 30 --rate 600
```

HTTP 接口：`GET /auth/scopes`、`POST /auth/keys`（自己的）、`POST /auth/users/{id}/keys`（管理员）、`PATCH /auth/keys/{id}`、`DELETE /auth/keys/{id}`，字段为 `scopes`（列表，`null` 表示全部）、`read_only`、`expires_in_days` 或 `expires_at`（`YYYY-MM-DD`）、`rate_per_min` 和 `note`。只有带 `admin` scope 的 key 才能管理 key。

**首次启动。** 以下方式任选其一：

- 启动前设置 `QFZ_ADMIN_PASSWORD`（可选 `QFZ_ADMIN_USERNAME`）；
- 执行 `qfz-auth create-user <name> --role admin`；
- 打开 `/setup`，输入 hub 日志里打印的一次性 token。这个 token 同时保存在 `$QFZ_DATA_ROOT/_state/setup_token`。

```bash
qfz-auth list
qfz-auth create-user alice --role researcher
qfz-auth create-key alice --name eval-runner      # key 只打印一次
qfz-auth set-role alice viewer
qfz-auth disable alice
```

| 变量 | 默认值 | 作用 |
|------|--------|------|
| `QFZ_AUTH_MODE` | `required` | 设为 `off` 关闭检查，用于本地开发 |
| `QFZ_SECRET_KEY` | 自动生成到 `_state/auth_secret` | cookie 签名密钥 |
| `QFZ_SESSION_DAYS` | `7` | 浏览器 session 有效期 |
| `QFZ_COOKIE_SECURE` | `auto` | 经 HTTPS 访问时使用 `Secure` cookie |
| `QFZ_AUTH_DB` | `_state/auth.sqlite3` | 用户和 key 的存储 |
| `QFZ_PUBLIC_HOSTS` | （无） | 允许访问 `/mcp` 的公网主机名 |

放在反向代理后面时，在代理上终止 TLS，并转发 `X-Forwarded-Proto` 和 `X-Forwarded-For`。UPQ 和 Next.js 子进程默认只监听 127.0.0.1（可用 `UPQ_HOST` 覆盖），hub 是唯一的公网入口。

其他安全措施：
- 密码用 scrypt 哈希。
- API key 只保存 SHA-256 摘要。
- 登录失败次数会被限流。
- 修改密码后，其他所有浏览器会被登出。
