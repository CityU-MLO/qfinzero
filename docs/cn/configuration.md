# 配置

> English: [docs/en/configuration.md](../en/configuration.md)

QFinZero 通过环境变量配置。每个进程按以下优先级读取：

1. 进程环境变量；
2. 仓库根目录的 `.env`（从 `.env.example` 复制，不提交）；
3. `config/qfinzero.env`（已提交的默认值）。

先读到的值不会被后面的来源覆盖。hub 会把自己的环境变量传给它启动的服务，所以给 `qfz-server`
设置的变量对所有服务都生效。数据供应商凭证也可以通过数据控制台保存到
`$QFZ_DATA_ROOT/_state/qfz.config.json`（可用 `QFZ_CONFIG_FILE` 改变位置）。

## Hub 与端口

| 变量 | 默认值 | 含义 |
|---|---|---|
| `QFZ_SERVER_PORT` | `19777` | hub 端口：网页界面、`/svc/*`、`/mcp`、`/auth` |
| `QFZ_SERVER_HOST` | `0.0.0.0` | hub 监听地址 |
| `QFZ_HOST` | `127.0.0.1` | 各服务监听及被访问的地址 |
| `UPQ_PORT`、`ESP_PORT`、`PMB_PORT` | `19350`、`19330`、`19380` | 内部服务端口 |
| `PLAYGROUND_PORT`、`DATA_ADMIN_PORT`、`DASHBOARD_PORT` | `19390`、`19340`、`19300` | 对话后端、数据控制台和网页界面的内部端口 |
| `QFZ_SUPERVISE` | `1` | 设为 `0` 时 hub 不启动服务，只代理到你自行运行的服务 |
| `QFZ_SERVE_UI` | `auto` | 存在 `infra/dashboard-web/.next` 时启动网页界面；`0` 表示不启动 |
| `UPQ_BIN` | 仓库内的构建产物 | `upq-service` 可执行文件路径 |
| `UPQ_HOST` | `127.0.0.1` | UPQ 监听地址；仅在不经 hub 直接暴露 UPQ 时设为 `0.0.0.0` |

如果某个服务的端口已有程序在监听，hub 会沿用它而不是再启动一个。

## 数据

| 变量 | 默认值 | 含义 |
|---|---|---|
| `QFZ_DATA_ROOT` | `/data/qfinzero` | QFinZero 所有数据的根目录：`upq/`、`esp/`、`_state/` |
| `STORAGE_ROOT` | `$QFZ_DATA_ROOT/upq` | UPQ 价格存储 |
| `EARNINGS_DB` | `$QFZ_DATA_ROOT/esp/benzinga_earnings.sqlite3` | 财报日历 |
| `ECON_EVENTS_DB` | `$QFZ_DATA_ROOT/esp/nasdaq_econ_events.sqlite3` | 宏观日历 |
| `NEWS_DB` | `$QFZ_DATA_ROOT/esp/news.sqlite3` | SQLite 新闻库 |
| `RAW_MASSIVE_DIR`、`RAW_TUSHARE_DIR`、`RAW_DATABENTO_DIR` | `/data/massive_data`、`/data/tushare_data`、`/data/databento` | 供应商原始文件，由 `qfz-data` 原地读取 |
| `QFZ_DATABENTO_JOBS` | `1` | `qfz-data convert --vendor databento` 的默认并行度 |
| `QFZ_BROWSE_ROOTS` | 各原始目录、`QFZ_DATA_ROOT`、`/data` | 数据导入工具的文件浏览器可显示的目录，以 `:` 分隔 |
| `QFZ_STOCK_QUOTE_INTERVAL`、`QFZ_OPTION_QUOTE_INTERVAL`、`QFZ_FUTURE_QUOTE_INTERVAL` | *BBO 采样* 设置，否则为 `1` | 报价存储中保留盘口的间隔分钟数：1、5、15、30 或 60 |

除非某个存储不在数据根目录下，否则不要设置这些派生路径。

## 账号与登录

| 变量 | 默认值 | 含义 |
|---|---|---|
| `QFZ_AUTH_MODE` | `required` | `off` 关闭所有检查（仅限本地开发） |
| `QFZ_ADMIN_USERNAME`、`QFZ_ADMIN_PASSWORD` | `admin`、未设置 | 首次启动且没有任何用户时创建该管理员 |
| `QFZ_SECRET_KEY` | 自动生成到 `_state/auth_secret` | 签名 session cookie 的密钥；多个 hub 共用用户库时需要设置 |
| `QFZ_SESSION_DAYS` | `7` | 浏览器 session 有效期 |
| `QFZ_COOKIE_SECURE` | `auto` | 请求经 HTTPS 时使用 `Secure` cookie；`1`/`0` 强制开关 |
| `QFZ_STATE_DIR` | `$QFZ_DATA_ROOT/_state` | 账号数据库、密钥和初始化令牌所在目录 |
| `QFZ_AUTH_DB` | `$QFZ_STATE_DIR/auth.sqlite3` | 用户与 API 密钥 |
| `QFZ_PUBLIC_HOSTS` | 未设置 | 允许访问 `/mcp` 的公网主机名，逗号分隔（MCP 的 DNS 重绑定防护） |

## 时间锁与研究

| 变量 | 默认值 | 含义 |
|---|---|---|
| `QFZ_REQUIRE_SESSION` | 未设置 | 设为 `1` 时拒绝任何未绑定 PMB 会话的 MCP 数据查询 |
| `QFZ_TIME_LOCK_SESSION` | 未设置 | 把本进程的所有 MCP 调用绑定到同一个会话 |
| `UPQ_AS_OF` | 未设置 | 所有 UPQ 查询的硬上限（ISO 时间或纳秒）；无法解析时不返回任何数据 |
| `UPQ_IN_PLACE` | 未设置 | 直接读取 `qfz-data index` 登记的原始文件、而不读转换后分区的存储：`option_minute`、`option_day`、`stock_daily` 或 `all`（其他供应商的 part 仍会读取） |
| `QFZ_RESEARCH_MAX_DAYS` | `40` | 一次 `research_*` 调用最多覆盖的交易日数 |
| `QFZ_RESEARCH_MAX_UNIVERSE` | `1000` | 一次 `research_*` 调用最多排序的股票数 |

## ESP（新闻与事件）

ESP 读取带 `ESP_` 前缀的设置。

| 变量 | 默认值 | 含义 |
|---|---|---|
| `ESP_NEWS_BACKEND` | `auto` | `auto` 在 `NEWS_DB` 文件存在时使用它，否则用 MongoDB；`sqlite` 或 `mongo` 强制指定 |
| `ESP_MONGO_URI` 或 `MONGO_URI` | `mongodb://localhost:27018` | 存放新闻集合的 MongoDB |
| `ESP_MONGO_DB` 或 `MONGO_DB` | `market_news` | 数据库 |
| `ESP_MONGO_COLLECTION` 或 `MONGO_COLLECTION` | `ticker_news` | 共享集合 |

设置 → 新闻存储 会覆盖 `MONGO_*`，并选择读取共享集合还是每个数据商一个集合（见 [ESP](esp/README.md#新闻存储)）；显式设置的 `ESP_MONGO_*` 仍然优先。
| `ESP_DEFAULT_PAGE_SIZE`、`ESP_MAX_PAGE_SIZE` | `50`、`500` | 分页限制 |
| `ESP_LOG_LEVEL` | `INFO` | 日志级别 |

## PMB（模拟券商）

| 变量 | 默认值 | 含义 |
|---|---|---|
| `PMB_UPQ_BASE_URL` | UPQ 服务 | PMB 加载价格的地址（由 hub 设置） |
| `PMB_LOG_LEVEL` | `INFO` | 日志级别 |

券商默认参数（初始资金、费用、滑点、保证金、成交模型）在 *模拟交易 → 交易设置* 中修改，
或用 `pmb_get_config`/`PUT /v1/config`，保存在服务器上。

## 在 hub 之外运行 MCP 服务器

`python mcp/server.py` 单独运行这些工具，供本地客户端使用。

| 变量 | 默认值 | 含义 |
|---|---|---|
| `QFINZERO_MCP_TRANSPORT` | `stdio` | `stdio`、`streamable-http` 或 `sse` |
| `QFINZERO_MCP_HOST`、`QFINZERO_MCP_PORT` | `127.0.0.1`、`19360` | HTTP 传输的地址 |
| `QFINZERO_UPQ_URL`、`QFINZERO_ESP_URL`、`QFINZERO_PMB_URL` | 本地服务 | 各服务地址 |

## 对话、模型与数据供应商

| 变量 | 含义 |
|---|---|
| `OPENAI_API_KEY`、`OPENAI_BASE_URL` | 对话和 `qfz-bench run` 的默认模型服务 |
| `ANTHROPIC_API_KEY`、`DEEPSEEK_API_KEY`、`GEMINI_API_KEY` | 对话设置页会自动识别 |
| `LLM_PROXY` | 只用于访问模型服务的 HTTP 代理（未设置时回退到 `HTTPS_PROXY`/`HTTP_PROXY`） |
| `PLAYGROUND_TIMEOUT_S` | 对话后端请求模型的超时时间，默认 120 |
| `PLAYGROUND_DB` | 对话历史数据库，默认 `$QFZ_STATE_DIR/playground.sqlite3` |
| `MASSIVE_REST_API_KEY`、`POLYGON_S3_ACCESS_KEY_ID`、`POLYGON_S3_SECRET_ACCESS_KEY` | massive（Polygon）REST 与 flat files |
| `DATABENTO_API_KEY` | Databento 历史 API（`qfz-data acquire databento`） |
| `TUSHARE_TOKEN` | Tushare |
| `BENZINGA_API_KEY` | Benzinga 财报采集 |

## 网页界面

| 变量 | 含义 |
|---|---|
| `NEXT_PUBLIC_REPO_URL` | 网站和文档"查看源文件"链接指向的仓库 |
| `NEXT_PUBLIC_STATUS_REFRESH_MS` | 服务状态卡片的刷新间隔 |

界面语言由 EN / 中文 切换按钮写入的 `qfz_lang` cookie 决定；首次访问时跟随浏览器语言。
