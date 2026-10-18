# 样本数据集

> English: [docs/en/sample-data.md](../en/sample-data.md)

`qfz-sample` 会写出一个完整、可自由分发的 QFinZero 数据根目录：价格、报价、期权、公司行动、利率、
财报、宏观数据和新闻。Docker 镜像默认使用它，端到端测试在它上面运行，[Agent 基准测试](bench.md)
也基于它构建。

```bash
qfz-sample generate --out ./qfz-sample       # 约 25 秒，约 22 MB
QFZ_DATA_ROOT=./qfz-sample qfz-server
```

`--no-esp` 跳过事件数据库。该命令会替换目标目录下的 `upq/` 和 `esp/`，并写出记录行数的
`sample_manifest.json`。

## 为什么是合成数据

这些代码在任何交易所都不存在。语言模型无法凭记忆回答关于它们的问题，所以答对说明 agent
确实使用了工具。数据也无需供应商授权即可分享。生成使用固定随机种子，每次运行产出的文件完全相同。

它不是真实行情。请用它来测试软件和 agent，而不是得出关于市场的结论。

## 日历

- 2025-01-02 至 2025-03-31，使用纽交所日历：共 60 个交易日。元旦、马丁·路德·金纪念日、
  总统日以及 2025-01-09 的全国哀悼日休市。
- 每个交易日都有日线。最后 10 个交易日（2025-03-18 至 2025-03-31）有分钟线、股票报价和期权报价。
- 分钟线覆盖美东 04:00 至 20:00（盘前、常规、盘后）。在分钟数据窗口内，ACME、NOVA 和 QZSP
  在周一至周四晚上还在夜盘场所交易（美东 20:00 至 04:00）。
- 2025-03-09 切换夏令时也在窗口内，UTC 偏移的变化与真实数据一致。

## 股票池

| 代码 | 名称 | 说明 |
|---|---|---|
| QZSP | QFinZero Synthetic 500 ETF | 指数 ETF；有期权；有分红；有夜盘 |
| ACME | Acme Robotics | 有期权；2025-03-24 收盘后发布财报；有夜盘 |
| BOLT | Bolt Electric Vehicles | 有期权；2025-03-27 开盘前发布财报 |
| NOVA | Nova Semiconductor | 1 拆 2，除权日 2025-03-03；有夜盘 |
| CRUX、DYNE、EMBR、FERN、GALE、HALO、IRIS、JADE、KITE、LUMA、MESA、NEXA、ORCA、PIKE、QUIL、RIFT | | 各属一个行业；其中十只按季分红 |

价格由因子模型生成：市场、行业和个股波动，在宏观数据发布和财报时有跳跃。股价精确到分。
成交量呈常见的日内 U 形分布，并在事件前后放大。

## 写到哪里

目录结构与生产环境相同，各服务无需改动即可读取。

| 路径 | 内容 |
|---|---|
| `upq/stock_daily`、`upq/stock_minute` | 原始（实际成交）价格的 K 线；拆股在读取时按 `adjust=split` 复权 |
| `upq/stock_quote_minute` | 分钟数据窗口内所有股票的分钟 NBBO |
| `upq/option_day` | 每个上市合约的日线 |
| `upq/option_minute`、`upq/option_quote_minute` | 前四个到期日中价内外 10% 以内合约的成交和 NBBO |
| `upq/corporate_actions`、`upq/dividends` | NOVA 拆股和十笔季度分红 |
| `upq/rates` | 七个期限的美国国债利率 |
| `esp/benzinga_earnings.sqlite3` | 12 份财报，含预期值和实际值 |
| `esp/nasdaq_econ_events.sqlite3` | 11 项美国宏观数据（非农、CPI、FOMC 等） |
| `esp/news.sqlite3` | 约 250 篇新闻，由 ESP 的 SQLite 新闻后端读取 |

QZSP、ACME 和 BOLT 有上市期权，周度和月度到期日一直到 2025-06-20（逢周五假日则为周四）。
期权价格来自带波动率微笑的 Black-Scholes 模型，并含财报溢价，财报发布后溢价消失，
因此隐含波动率在财报后下降，与实际情况一致。

## 新闻

每篇新闻都对应数据中的某件事：

- 每份财报前两个交易日的预告、发布后一分钟的结果，以及下一次收盘后的股价反应；
- 每项宏观数据，在发布后一分钟；
- 拆股和分红公告；
- 每只股票每周最大的单日涨跌，幅度超过 2.5% 时。

股价反应的标题使用由已存收盘价算出的涨跌幅，所以"ACME shares rise 6.1%"可以与 UPQ 的数据核对。

## 时间点行为

事件库是完整的，但只有在事件时间早于查询的 `now_utc`（或被时间锁定的 agent 的会话时钟）后，
ESP 才会给出结果。在 2025-03-24 美东 15:00 查询时，ACME 的 EPS 是 `null`；16:05 时为 1.61。
晚于 `now_utc` 发布的新闻此时还不存在。

## 代码

`qfinzero/sample/`：`universe.py`（代码、日历、事件）、`market.py`（价格路径和 UPQ 写入）、
`events.py`（ESP 数据库）。ESP 数据库的表结构在 `qfinzero/esp_schema.py`。
`tests/test_sample.py` 检查确定性、存储契约以及各存储之间的一致性。
