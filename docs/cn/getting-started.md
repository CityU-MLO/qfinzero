# 快速开始

> English: [docs/en/getting-started.md](../en/getting-started.md)

本页带你从零开始，运行一个有数据、能登录控制台、并能让 agent 通过 MCP 接入的 QFinZero。
这里使用自带的合成数据集，不需要任何数据供应商账号。用 Docker 大约需要 10 分钟。

## 1. 运行

### 使用 Docker（推荐）

需要 Docker 24 或更高版本。

```bash
git clone https://github.com/CityU-MLO/qfinzero && cd qfinzero
export QFZ_ADMIN_PASSWORD='设置一个足够长的密码'
docker compose up -d
```

首次构建会编译 UPQ 引擎和网页界面，约需 15 分钟。首次启动时会把合成样本写入 `qfz-data`
数据卷（约 25 秒）。打开 <http://localhost:19777>，用 `admin` 和你设置的密码登录。

### 从源码运行

需要 Python 3.10+、Rust 工具链（stable），如需网页界面还需要 Node 20 和 pnpm 9。

```bash
pip install -e ".[server,pipeline]"
(cd infra/upq && cargo build --release -p upq-service)
(cd infra/dashboard-web && pnpm install && pnpm build)      # 可选：网页界面
qfz-sample generate --out ./qfz-sample
QFZ_DATA_ROOT=./qfz-sample QFZ_ADMIN_PASSWORD='设置一个足够长的密码' qfz-server
```

`qfz-server` 是 hub。它以子进程方式启动 UPQ、ESP、PMB、playground 和网页界面，所有内容都在
19777 端口提供。`curl http://127.0.0.1:19777/health` 会列出各子服务及其是否正常。

`QFZ_ADMIN_PASSWORD` 只在首次启动时创建 `admin` 账户，之后可以去掉。创建首个管理员的其他方式见
[平台指南](platform-guide.md#6-账号角色与-api-key)。

## 2. 浏览控制台

样本是一个虚构市场：20 只代码，使用 2025-01-02 至 2025-03-31 的真实纽交所日历。分钟数据覆盖最后
10 个交易日（2025-03-18 至 2025-03-31）。内容详见 [样本数据集](sample-data.md)。

- **模拟交易**：先开立账户，再以 2025-03-24 为开始日期、自选 `ACME, QZSP, BOLT` 开始会话。
  点 *开盘* 后时钟逐分钟推进，可在下单面板下市价或限价单。ACME 在当天收盘后发布财报，
  次日早盘会出现跳空。
- **新闻** 和 **日历**：搜索 `ACME`，或打开 2025 年 3 月的财报日历。
- **数据可用性**：在连续的日历时间轴上按代码和日期查看有哪些数据（没有数据的日子留空，周末为空白）。
  个股和期货分为两组；期货代码前加斜杠（`/CL`、`/ZN`），因为品种代码会与股票代码重名。展开个股（▸）可分层查看
  股票行情、期权、新闻和公司事件；宏观数据单独一行。拖动地图下方总览中的窗口浏览历史，点击单元格查看当天，
  点击代码查看资产详情（各数据层、收盘价或结算价、期货的其他序列）。
- **对话**：先在 *设置*（齿轮图标）中添加模型分组：选择 OpenAI、Claude 或 Gemini · Antigravity，
  填写 base URL 和密钥，再获取模型列表。也可以直接导入 Claude Code 的 `settings.json`、
  `export ANTHROPIC_*` 环境变量或 Codex 的 `config.toml`。对话 agent 使用的 MCP 工具与外部 agent 相同。
- **文档**：即本文档，未登录也可以访问。

## 3. 接入 agent

1. 打开 **账户** 页创建一个 API 密钥，复制 `qfz_…` 令牌（只显示一次）。
2. 把任意 MCP 客户端指向 hub：

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

3. 要无前视偏差地回放历史，先创建一个 PMB 会话（在控制台中，或用 `pmb_create_session`），
   再在 headers 中加上 `"X-QFZ-Session": "sess_…"`。之后所有数据工具都只返回该会话当前 bar 时已知的信息。

所有工具及参数见 [MCP 工具参考](../en/mcp-tools.md)。

## 4. 检查安装

基准测试的 oracle 会通过公开 API 解答每一道题。安装正常时得分为 100%：

```bash
export QFZ_API_KEY=qfz_…
qfz-bench oracle --hub http://127.0.0.1:19777
```

使用 Docker 时在容器内运行：
`docker compose exec qfinzero qfz-bench oracle --hub http://127.0.0.1:19777 --api-key qfz_…`。
要评测模型，见 [Agent 基准测试](bench.md)。

## 5. 使用自己的数据

打开 **数据导入**（管理员）可导入服务器上已有的 Databento 或 massive 文件，或用你的密钥下载，见
[数据导入工具](data-setup.md)。命令行中 `qfz-data` 可完成同样的工作，`QFZ_DATA_ROOT` 用于指定 hub 的数据根目录。
[数据适配器](data-adapters.md) 介绍 massive、Tushare 和 Databento；[配置](configuration.md)
列出所有设置；[部署与运维](operations.md) 介绍如何为团队运行 QFinZero。
