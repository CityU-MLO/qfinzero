> English: [../../en/pmb/broker-terminal.md](../../en/pmb/broker-terminal.md)

# PMB 券商终端与期权指南

**Broker（券商）** 是由统一服务器在 **`/broker`**（导航：*Broker*）提供的独立的、
拟真券商风格的交易站点。它驱动 PMB 会话引擎——基于历史行情数据、由 UPQ 真实定价成交，
逐分钟推进，时钟由你掌控。本指南同时覆盖面向人的终端，以及面向 agent 的对应
REST/MCP 接口，包括**期权与期权策略**。

---

## 1. 进入交易大厅

落地页有两个入口：

- **Allocate Account（开户）** — 开立一个模拟账户：初始资金、市场、杠杆
  （1× / 2× / 4×）、维持保证金阈值。
- **Enter Account（进入账户）** — 选择账户、一个**交易日**和初始**自选股清单**，
  然后 *Open the market*。这会基于当天的真实行情数据创建一个分钟频率的会话。

## 2. 交易大厅

| 区域 | 作用 |
|---|---|
| **Watchlist（自选）** | 实时报价，含**相对开盘的涨跌幅 %**。在底部输入框添加标的（会把其行情加载进当前会话）；点垃圾桶图标移除。 |
| **Chart（图表）** | 切换 **Candles**（K 线，逐分钟生成）或 **Line**（折线）。K 线叠加 **MA5/MA20** 均线与**成交量**柱，含价格轴、最新价标记、ET 时间轴。 |
| **Option chain（期权链）** | 从 *Chart* 切换。见 §4。 |
| **Order ticket（下单）** | BUY/SELL、数量、**MARKET**/**LIMIT**。显示预计成本/收入，以及下单后的**剩余购买力**。 |
| **Blotter（记录）** | *Positions*（一键 **Flatten** 平仓）、*Orders*（**Cancel all** 撤单）、*Trades*。**Close all** 平掉全部持仓。 |
| **Account（账户）** | 完整详情浮层——账户明细、持仓（市值 / 权重 / 盈亏）、历史（实时**净值曲线** + 成交记录）。 |

## 3. 回放与时间旅行

底部状态栏就是市场时钟：

- **Open market** — 定位到常规交易时段开盘（09:30 ET）并开始走时。
- **Play / Pause**、单步 **step**，以及**速度滑块**（1×–60× = 每秒推进多少个市场分钟）。
- **时间轴拖块** — 拖动它。向**后拖会回退时间，并撤销该时刻之后下达的所有订单**
  （确定性重放）。向前拖则快进。

## 4. 期权与期权链

将中间面板切换到 **Option chain** —— 一个**双边、实时、分钟级**的期权链
（calls | 行权价 | puts），如同真实券商：

- 每个行权价在 call 与 put 两侧都显示 **bid / ask / last / volume**，
  **平值（ATM）** 行权价高亮，并显示标的**现价（spot）**。
- 它会**随时钟跳动而闪烁**——近平值的腿逐分钟更新（上涨/下跌以绿/红显示）。
  流动性差的行权价回退到当日的标记价。
- 选择**到期日（expiry）**；点击任一侧的 **B** / **S** 交易该合约
  （券商会把它加载进会话并提交市价单）。

性能：当日期权链骨架（行权价 + 希腊字母）只获取一次，近平值合约的分钟 bar 也只加载一次
（`GET /v1/sessions/{id}/option_chain`）；之后每一步都是快速的缓存读取，因此闪烁保持流畅。

底层的期权链来自 UPQ `/option/chain_query`（Black–Scholes 欧式希腊字母）。合约 id
为 OPRA 格式，例如 `O:AAPL240328C00170000`（标的 `AAPL`、到期 `2024-03-28`、
`C`all、行权价 `170.000`）。

> **成交需要当前分钟有数据。** 期权订单只有在该合约于当前模拟分钟存在 bar 时才会成交；
> 否则会作为挂单等待，直到出现成交 bar。

## 5. 期权策略

引擎将任意组合都表示为一组单腿期权持仓，因此策略通过下达（或持有）各腿来构建。常见策略：

| 策略 | 腿 | 观点 |
|---|---|---|
| **Long call / put（买入看涨/看跌）** | 买 1 张 call（或 put） | 方向性，风险有限 |
| **Covered call（备兑看涨）** | 持有 100 股 + 卖出 1 张 call | 对持仓收租 |
| **Protective put（保护性看跌）** | 持有 100 股 + 买入 1 张 put | 下行有保险 |
| **Vertical spread（垂直价差）** | 同类型不同行权价的多头 + 空头 | 风险有限的方向性 |
| **Straddle / strangle（跨式/宽跨式）** | 买 call + 买 put（同/异行权价） | 波动率 |
| **Iron condor（铁鹰）** | 卖出 call 价差 + 卖出 put 价差 | 区间震荡收租 |

**在终端中：** 从期权链逐腿下单（买入多头腿、卖出空头腿）——例如牛市看涨价差 =
在同一到期日 **B** 较低行权价、**S** 较高行权价。Account → Holdings 视图会显示合并后的
持仓、含希腊字母调整的盈亏与权重。

**通过 API（一次调用多腿）：** 订单模型也接受 `SpreadOrderSpec`（`legs` + `spread_type`，
例如 `PUT_DEBIT_SPREAD`、`PUT_CREDIT_SPREAD`），用于保证金感知的两腿价差。先添加合约，
再提交价差单。

## 6. Agent API（REST + MCP）

终端能做的一切对 agent 都可用。基础 URL 为 PMB 服务（或经 Web BFF 的 `…/api/pmb/v1`、
经 hub 的 `…/svc/pmb`）。

| REST | MCP 工具 | 用途 |
|---|---|---|
| `POST /v1/accounts` | `pmb_create_account` | 开立账户 |
| `GET /v1/accounts` | — | 列出账户 |
| `POST /v1/sessions` | `pmb_create_session` | 开启日内会话（universe = 股票/期权） |
| `POST /v1/sessions/{id}/step` | `pmb_step_session` | 推进 N 分钟 |
| `GET /v1/sessions/{id}/state` | `pmb_session_state` | **一次调用快照**：时钟、账户、持仓、订单、成交、行情 |
| `GET /v1/sessions/{id}/timeline` | — | 全部 bar 时间戳（可拖动的时钟） |
| `POST /v1/sessions/{id}/rewind` | `pmb_rewind` | **时间旅行**回到 `target_ts`，撤销之后的订单 |
| `POST /v1/sessions/{id}/add_stocks` | `pmb_add_stocks` | 实时扩充自选/交易范围 |
| `POST /v1/sessions/{id}/add_contracts` | `pmb_add_contracts` | 加载期权合约以便交易 |
| `GET /v1/sessions/{id}/option_chain` | — | 当前 bar 的实时双边分钟期权链 |
| `POST /v1/orders` | `pmb_buy_stock` / `pmb_sell_stock` / `pmb_buy_option` / `pmb_sell_option` | 下单（股票或 `OPTION:<contract>`） |
| `POST /v1/orders/{id}/cancel` | `pmb_cancel_order` | 撤销挂单 |
| `GET /option/chain_query`（UPQ） | `upq_option_chain` | 发现期权合约 + 希腊字母 |

**典型 agent 循环：** `pmb_create_account` → `pmb_create_session` → 循环
（`pmb_step_session` → `pmb_session_state` → 决策 → `pmb_buy_stock` /
`upq_option_chain` + `pmb_add_contracts` + `pmb_buy_option`）→ `pmb_get_summary`。
用 `pmb_rewind` 从更早的 bar 分叉。

## 7. Windows 98 皮肤

券商在 **`/legacy/broker`** 提供复古皮肤——经典灰色立体边框（标题栏、下沉状态栏、
凸起按钮）。用角落的 **Win98 UI ⇄ Modern UI** 按钮切换。
