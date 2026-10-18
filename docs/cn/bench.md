# Agent 基准测试

> English: [docs/en/bench.md](../en/bench.md)

`qfz-bench` 衡量一个会调用工具的模型使用 QFinZero 的能力：查找数据、基于数据计算、遵守时间锁以及下单。
它针对提供 [样本数据集](sample-data.md) 的 hub 运行，所以每个答案都确切已知，也不可能来自模型的记忆。

```bash
qfz-bench oracle --hub http://127.0.0.1:19777 --api-key qfz_…      # 平台自检，应为 100%
qfz-bench run --hub http://127.0.0.1:19777 --api-key qfz_… \
    --model gpt-4.1 --base-url https://api.openai.com/v1 --llm-key sk-… \
    --out runs/gpt-4.1.jsonl
qfz-bench score runs/gpt-4.1.jsonl
```

## 题目

1.0 版共 104 道题，随包提供，位于 `qfinzero/bench/data/tasks-v1.0.jsonl`。

| 类别 | 题数 | 考查内容 |
|---|---:|---|
| `daily` | 25 | 收盘价、成交量、拆股复权收益率、月内最高收盘价的日期 |
| `intraday` | 21 | 指定分钟的收盘价、常规时段 VWAP、盘前成交量、夜盘最高价 |
| `quotes` | 5 | 指定分钟的股票买卖价差 |
| `options` | 13 | 期权在指定分钟的中间价、最活跃合约、某到期日有成交的合约数 |
| `events` | 21 | EPS 超预期幅度、是否超预期、宏观数据实际值、财报后的股价反应、新闻数量 |
| `corporate` | 4 | 分红金额、从价格推断拆股除权日 |
| `time_lock` | 11 | 在过去某一时刻提问，包括结果尚未公布的情况 |
| `trading` | 4 | 在 PMB 会话中交易，按券商记录评分 |

难度从 1（一次查询）到 3（多次调用加计算）。例如：

- *What was the closing price of QUIL on 2025-02-27? (as traded, not adjusted)* → 17.06
- *How much did PIKE move, in percent, from the last close before its earnings
  report of 2025-02-21 to the first close after it?* → 7.39
- 在 2025-03-24 美东 15:00 提问：*What EPS did ACME report in its earnings release
  of 2025-03-24? If it is not known yet, answer null.* → null
- *BOLT reports earnings at 7:00 a.m. ET on 2025-03-27. Buy 100 shares of BOLT
  now, then make sure you hold no BOLT shares when the report comes out.*

题目本身为英文，便于不同模型之间比较。

## 题目格式

每行一个 JSON 对象：

| 字段 | 含义 |
|---|---|
| `id`、`category`、`difficulty` | 标识 |
| `question` | 交给模型的题目文本 |
| `kind` | `number`、`integer`、`text`、`date`、`bool`、`none`（正确答案是"尚不可知"）、`episode` |
| `answer`、`tolerance` | 标准答案；数值误差不超过 `tolerance` 即算正确 |
| `as_of` | 提问时刻（ISO UTC），或 null |
| `op`、`args` | 标准答案的计算方式（见下文） |
| `episode` | 交易题：会话设置、oracle 的脚本和检查项 |

## 模型如何运行

`qfz-bench run` 连接任意兼容 OpenAI 的 chat-completions API（OpenAI、vLLM、SGLang、LiteLLM、
OpenRouter 等），并通过 hub 的 MCP 端点调用工具，与外部 agent 使用的接口相同。

1. 对带 `as_of` 的题目，运行器先创建一个时钟对应该时刻的 PMB 会话（提前一根 bar 的分钟级会话；
   美东 16:00 则用日级会话），并把会话 id 作为 `X-QFZ-Session` header 发送。时间锁由服务器强制执行，
   提示词里也会写明当前时间。
2. 模型可以调用提供给它的任意工具（`--tools`，默认 `upq_,esp_,pmb_,research_`），
   最多 `--max-turns` 轮（默认 30）。工具输出超过 12,000 字符会被截断。
3. 模型必须以一行 `ANSWER: <json>` 结束：数字、带引号的字符串、`true`/`false` 或 `null`。

交易题由运行器创建账户和会话，在提示词中给出它们的 id 并绑定会话 header。模型结束后，
根据会话的成交记录和账户持仓执行检查：

| 检查 | 通过条件 |
|---|---|
| `position` | 账户恰好持有该代码 `qty` 数量 |
| `filled` | 该方向的成交合计为 `qty`，可限定时间窗口 |
| `flat_by` | 指定时刻之前的成交净头寸为零 |

## 评分

- `number`：绝对误差不超过 `tolerance`（价格 0.005，百分比 0.02 个百分点；忽略单位和 `%`）。
- `integer`：四舍五入后等于标准答案。
- `text`：去掉空格并忽略大小写后相等；期权代码带不带 `O:` 都可以。
- `date`：答案中的第一个 `YYYY-MM-DD` 等于标准答案。
- `bool`：`true`/`false` 或 yes/no。
- `none`：`null`，或类似"not yet released"的表述。
- `episode`：所有检查都通过。

没有 `ANSWER:` 行、运行出错或超时的题目记零分。`score` 输出各类别和总体的正确率以及平均工具调用次数；
`--out` 还会写出包含 token 统计的 `<name>.summary.json`。

## Oracle

每种题型（`op`）在 `qfinzero/bench/ops.py` 中都有两份实现：`gold` 用 SQL 从样本文件算出答案，
`solve` 通过公开的 UPQ、ESP 和 PMB API 作答。`qfz-bench oracle` 对每道题运行 `solve`，
对每个交易题运行交易脚本。得分 100% 说明每道题都能通过平台作答，并且各服务返回的数据与文件一致。
`tests/test_e2e.py` 在 CI 中对新启动的整套服务运行这一检查。

## 可复现性与结果报告

题目文件由 `qfz-bench build --data <root> --out <file>` 从样本重新生成；如果随包的文件与重新生成的不同，
`tests/test_bench.py` 会失败。发布结果时请注明基准版本（1.0）、模型及其版本、temperature、
`--max-turns`、提供的工具前缀，以及是否使用了时间锁 header（`qfz-bench run` 总是使用）。

## 添加题目

1. 在 `qfinzero/bench/ops.py` 中添加一个 op，实现 `gold(store, args)` 和 `solve(api, args, as_of)`。
2. 在 `qfinzero/bench/tasks.py` 中生成题目实例（使用 builder 的带种子随机数生成器，不要用 `random`）。
3. 重新生成题目文件并运行 oracle，必须保持 100%。
4. 修改已有题目时提升 `BENCH_VERSION`。
