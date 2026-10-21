> English: [../../README.md](../../README.md)

# QFinZero

**面向 LLM 智能体的统一交易环境**

QFinZero 将价格数据、事件/新闻检索与券商模拟统一在一致的、时间对齐的 API 之下，使 LLM 智能体能够在一个连贯的环境中查询、推理与交易。

> Haochen Luo1*, Binh Minh An1, Ho Tin Ko2, Junjie Xu5, Pok Hin Tang1, Wang Chak Wong1, Yifan Li1, Yuan Gao1, Zhengzhao Lai4, Yuan Zhang3, Chen Liu1
>
> 1 香港城市大学, 2 元朗商会中学, 3 上海财经大学, 4 中国科学技术大学, 5 香港中文大学（深圳）
>
> 通讯作者: chester.hc.luo@my.cityu.edu.hk, zhang.yuan@sufe.edu.cn, chen.liu@cityu.edu.hk

> [!NOTE]
> **v1.0.0 已归档。** 这个版本固定为我们 ACL 2026 System Demonstrations 论文所描述的版本。我们正在开发功能更强大的下一代 QFinZero；这个分支之后只接受修复。

## 摘要

大语言模型（LLM）智能体正越来越多地被应用于需要与外部工具交互的金融决策任务，例如市场数据、新闻与交易执行。现有系统在各类任务专用 API 之间高度割裂，导致 schema 不一致、集成脆弱以及可复现性差。QFinZero 通过一个统一交易环境来弥补这一空缺，将三项核心能力标准化：多频率市场与衍生品数据访问 (UPQ)、结构化新闻与事件检索 (ESP)，以及具备显式订单生命周期管理的有状态券商模拟器 (PMB)。所有工具都暴露一致的 JSON schema 与时间对齐的接口，使智能体能够在一个连贯的框架内自主检索信息、管理组合状态并执行交易。通过将金融交互抽象为可组合、可被智能体调用的原语，QFinZero 降低了工程开销，并借助确定性重放与全面日志记录支持可复现的评估。

## v1.0 包含什么

- **行情数据（UPQ，Rust）。** 日线、分钟线和分钟级最优买卖价：美股（盘中、盘前、盘后以及 Blue Ocean 夜盘）、A 股、OPRA 期权（含盘中期权链和 Greeks）、按 CME 交易时段划分的期货、加密货币、外汇和美债收益率。价格按成交原样存储，拆股和分红在读取时调整。
- **新闻与事件（ESP）。** Benzinga 和 Tushare 新闻（每篇都标出有全文、摘要还是只有标题）、财报和宏观日历，全部按时点可见。
- **模拟券商（PMB）。** 逐步推进的模拟器：市价、限价、止损单，常规、盘前盘后和夜盘交易时段，保证金，期权按报价成交，期货每日结算，检查点与确定性重放。
- **时间锁。** 把连接绑定到一个交易会话或一个固定时间，所有数据工具都只回答那一刻之前的数据，由服务器强制执行。
- **面向 agent。** 一个端点上的 69 个 MCP 工具，带权限范围的 API key，兼容任意 OpenAI 或 Anthropic 协议模型的对话控制台，因子研究 DSL，以及 104 道任务的基准测试（`qfz-bench`）。
- **控制台。** 带交易时段底色和期权链的 QFZView 图表、交易终端、新闻、日历、数据可用性地图和数据导入。
- **数据平台。** `qfz-data` 下载并转换 massive、Databento 和 Tushare 数据，原地索引原始文件，并自带合成样例数据，没有数据商账号也能跑通全部功能。

## 快速开始

```bash
git clone https://github.com/CityU-MLO/qfinzero && cd qfinzero
export QFZ_ADMIN_PASSWORD='choose-a-long-password'
docker compose up -d          # hub、全部服务、网页和合成样例数据
# 打开 http://localhost:19777，用 admin 登录
```

然后创建一个 API key，就可以用 curl、Python 或 MCP 客户端查询：

```python
from qfinzero.clients.upq import UPQClient       # export QFZ_API_KEY=qfz_…

with UPQClient("http://localhost:19777/svc/upq") as upq:
    print(upq.stock_daily(["ACME"], "2025-03-17", "2025-03-28"))
```

- [快速上手](quickstart.md)：五分钟走完 API key、REST、Python 客户端、MCP 和时间锁。
- [入门指南](getting-started.md)：从源码安装，以及控制台导览。

## 架构

QFinZero 作为一个服务器运行在一个端口（`19777`）上。hub 在本机托管各个服务，并统一提供网页、各服务的原始 API 和 MCP 端点：

```
        LLM agent / 用户 / MCP 客户端
                     │
                     v
   ┌──────────────────────────────────────────┐
   │       qfinzero-server  :19777            │
   │  /  网页        /mcp  MCP 工具             │
   │  /auth  登录、key     /svc/*  REST        │
   └───┬─────┬─────┬──────┬──────────┬────────┘
       v     v     v      v          v       （本机，由 hub 托管）
     UPQ   ESP   PMB   playground  data-admin
    (Rust)   │     │
       ▲     v     │
       │  MongoDB  │
       │  + SQLite │
       └───────────┘  PMB 从 UPQ 读取行情
```

| 路径 | 提供内容 |
|------|--------|
| `/` | 首页、`/login`、控制台和 `/docs` |
| `/auth/*` | 登录、API key、用户 |
| `/svc/upq/*`、`/svc/esp/*`、`/svc/pmb/*` | 行情、新闻与事件、模拟券商（REST） |
| `/svc/playground/*`、`/svc/data-admin/*` | 对话后端、数据管理 |
| `/mcp` | MCP 服务器（streamable HTTP） |
| `/health` | hub 和所有子服务状态 |

控制台、`/svc/*` 和 `/mcp` 需要登录或 API key；角色分为 viewer、researcher 和 admin。时间锁、交易时段、报价、研究和账号见[平台指南](platform-guide.md)。

## 文档

网页的 `/docs` 提供全部文档，可搜索，中英双语。

- **入门：** [快速上手](quickstart.md) · [入门指南](getting-started.md) · [平台指南](platform-guide.md)
- **指南：** [对话](chat.md) · [Agent 行情工具](upq/agent-guide.md) · [Agent 交易工具](pmb/agent-guide.md) · [QFZView](qfzview.md) · [交易终端](pmb/broker-terminal.md) · [Agent 基准测试](bench.md) · [样例数据](sample-data.md)
- **数据：** [数据导入](data-setup.md) · [数据适配器](data-adapters.md)（massive、Databento、Tushare）
- **参考：** [MCP 工具](../en/mcp-tools.md) · [UPQ](upq/README.md)（[OpenAPI](../upq/openapi.yaml)） · [ESP](esp/README.md)（[OpenAPI](../esp/openapi.yaml)） · [PMB](pmb/README.md)（[OpenAPI](../pmb/openapi.yaml)） · [配置](configuration.md) · [时区](conventions/timezone.md)
- **运维：** [部署与运维](operations.md) · [更新日志](../../CHANGELOG.md)

## 项目结构

```
qfinzero/          Python 包：hub（server/）、认证、数据管道（pipeline/、index/、admin/）、
                   研究、基准测试（bench/）、样例数据（sample/）、客户端
clients/           UPQ、ESP、PMB 的 Python 客户端（qfinzero.clients.*）
mcp/               MCP 服务器
infra/upq/         UPQ 行情服务（Rust 工作区）
infra/esp/         ESP 新闻与事件（FastAPI）
infra/pmb/         PMB 模拟券商（FastAPI）
infra/playground/  对话后端（FastAPI、LangGraph）
infra/data-admin/  数据管理服务
infra/dashboard-web/  网页（Next.js）
docs/              文档（en、cn）和 OpenAPI 文档
scripts/、docker/  服务脚本、容器入口
```

数据放在仓库之外的 `QFZ_DATA_ROOT`（默认 `/data/qfinzero`）下：UPQ 存储在 `upq/`，ESP 数据库在 `esp/`，状态在 `_state/`。

## 引用

如果你使用了 QFinZero，请引用：

```bibtex
@inproceedings{luo2026qfinzero,
  title={QFinZero: A Unified Financial Toolchain for LLM-Based Trading Agents},
  author={Luo, Haochen and Yifan, LI and Ko, Ho Tin and Minh, An Binh and Xu, Junjie and Hin, Tang Pok and Wong, Wang Chak and Yuan, Gao and Lai, Zhengzhao and Zhang, Yuan and others},
  booktitle={Proceedings of the 64th Annual Meeting of the Association for Computational Linguistics (Volume 3: System Demonstrations)},
  pages={68--77},
  year={2026}
}
```

## 许可证

MIT License
