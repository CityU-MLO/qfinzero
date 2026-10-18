# 数据适配器

> English: [docs/en/data-adapters.md](../en/data-adapters.md)

UPQ 只从一种磁盘格式读价格。每个数据供应商都是 Python 管道
（`qfinzero/pipeline/sources/`）里的一个**适配器**，负责把原始文件转换成这种格式。
UPQ 引擎（`infra/upq`，Rust）并不知道某一行来自哪家供应商，所以新增供应商不需要改引擎。

```
原始供应商文件 ──▶ 适配器 (sources/<vendor>.py) ──▶ UPQ 存储 ──▶ UPQ 引擎 ──▶ MCP / 客户端
  原地读取            归一化 + 转换                    parquet      不改动
```

## 存储契约

适配器的全部产出都在 `STORAGE_ROOT` 下（默认 `$QFZ_DATA_ROOT/upq`）。

| 存储 | 分区 | 列（按此顺序） |
|------|------|----------------|
| `stock_daily` | `trade_date=YYYY-MM-DD/` | `ticker, trade_date, open, high, low, close, volume, transactions` |
| `stock_minute` | `trade_date=YYYY-MM-DD/` | `ticker, window_start, open, high, low, close, volume, transactions, trade_date` |
| `option_day` | `trade_date=YYYY-MM-DD/` | `ticker, contract, underlying, expiry, strike, right, window_start, open, high, low, close, volume, transactions, trade_date` |
| `option_minute` | `trade_date=YYYY-MM-DD/` | 与 `option_day` 相同 |
| `stock_quote_minute` | `trade_date=YYYY-MM-DD/` | `ticker, window_start, bid_price, ask_price, bid_size, ask_size, trade_date` |
| `option_quote_minute` | `trade_date=YYYY-MM-DD/` | `ticker, contract, underlying, expiry, strike, right, window_start, bid_price, ask_price, bid_size, ask_size, trade_date` |
| `future_daily` | `trade_date=YYYY-MM-DD/` | `ticker, root, trade_date, open, high, low, close, settle, volume, transactions` |
| `future_minute` | `trade_date=YYYY-MM-DD/` | `ticker, root, window_start, open, high, low, close, volume, transactions, trade_date` |
| `future_quote_minute` | `trade_date=YYYY-MM-DD/` | `ticker, root, window_start, bid_price, ask_price, bid_size, ask_size, trade_date` |

类型固定在 [`qfinzero/pipeline/schema.py`](../../qfinzero/pipeline/schema.py) 里：
文本是 `VARCHAR`，日期是 `DATE`，价格和行权价是 `DOUBLE`，成交量、成交笔数和时间戳是 `BIGINT`。
文件格式为 ZSTD 压缩的 parquet。

所有适配器遵守的约定：

- `window_start` 是K线开始时间，单位为 UTC 纳秒。`option_day` 上取交易日的美东 00:00。
- 美股的 `trade_date` 是美东日历日。期货的 `trade_date` 是 CME 交易时段：前一天美东 18:00 到当天 17:00。
- 价格为原始成交价。拆股和分红放在 `corporate_actions/`，由 UPQ 在读取时复权。
- 期权代码格式为 `O:{ROOT}{YYMMDD}{C|P}{行权价×1000，8 位}`，例如 `O:SPY250117C00500000`。
- 每家供应商在分区里写自己的文件：massive 是 `part-0000.parquet`，tushare 是
  `part-cn-0000.parquet`，Databento 是 `part-databento-0000.parquet`。

引擎用一个 `read_parquet('<store>/trade_date=*/*.parquet')` 读取整个存储，由此有两条要求：

1. 所有分片的列名、顺序和类型必须一致。测试 `test_parts_match_upq_storage_schema_exactly` 会检查 Databento 适配器。
2. 同一分区里两个分片若有同一代码，它的K线会出现两次。会重叠的适配器必须约定优先级，规则见下文。

## 新增一家供应商

1. 在 `qfinzero/pipeline/sources/<vendor>.py` 写读取器，为每个存储生成符合上述列和类型的 SELECT。
2. 在 `Converter`（`qfinzero/pipeline/convert.py`）加 `convert_<vendor>` 方法，写分区并记入 manifest，使重跑是增量的。
3. 在 `registry.scan_raw` 报告原始文件，在 `registry.scan_storage` 报告转换状态，让 `qfz-data status` 和更新新鲜度能看到它。
4. 在 `qfinzero/update/sources.py` 注册更新源。
5. 如果供应商有 API，在 `qfinzero/admin/` 加原始目录、凭证、scan 和 acquire。

`infra/upq` 下无需改动。只有新**种类**的数据才需要改引擎（新增存储和接口），例如订单簿目前就没有。

## Databento 适配器

代码在 [`qfinzero/pipeline/sources/databento.py`](../../qfinzero/pipeline/sources/databento.py)
和 `Converter.convert_databento`。安装：`pip install -e ".[databento]"`。parquet 导出文件不装 `databento` 包也能转换。

### 读取哪些文件

`RAW_DATABENTO_DIR`（默认 `/data/databento`）下的每个 `*.dbn`、`*.dbn.zst` 和 Databento 导出的 `*.parquet`，
都按文件自身的头信息或列来识别，所以目录怎么组织都可以。以 `_` 或 `.` 开头的目录会跳过，例如 Databento 批量下载的 `_tmp`。
头信息缓存在 `$STORAGE_ROOT/_state/databento_index.json`。首次扫描约 6,600 个文件大约两分钟，之后约一秒。

### schema 对应关系

| Databento schema | UPQ 存储 | 方式 |
|------------------|----------|------|
| `ohlcv-1m` | 分钟线 + 日线 | 直接复制K线；日线由分钟线聚合 |
| `ohlcv-1s` | 分钟线 + 日线 | 重新聚合为分钟线 |
| `ohlcv-1h`、`ohlcv-1d`、`ohlcv-eod` | 日线 | `ohlcv-1d` 用 Databento 给出的 UTC 日 |
| `trades`、`tbbo`、`tcbbo` | 分钟线 + 日线 | 每条记录都是成交 |
| `mbp-1`、`mbp-10`、`cmbp-1`、`mbo` | 分钟线 + 日线 | 只取 `action == 'T'` 的记录 |
| `cmbp-1`、`cbbo-1s`、`cbbo-1m`、`bbo-1s`、`bbo-1m` | `option_quote_minute`、`stock_quote_minute`、`future_quote_minute` | 每分钟最后的最优买卖价（见下文） |
| 期货交易所的 `mbp-1`、`mbp-10` | `future_quote_minute` | 交易所自身的盘口就是最优买卖价 |
| definition、statistics、status、imbalance | 无 | 参考数据 |

MBO 里 `T` 是成交本身，`F` 是同一笔成交的被动方回报，两者都算会让成交量翻倍。隐藏单的成交也以 `T` 出现。

### 资产类别和代码

- `OPRA.*` 数据集写入 `option_minute` 和 `option_day`。OSI 代码如 `SPY   250117C00500000`
  改写为 `O:SPY250117C00500000`。标的、到期日、行权价和方向用与 massive 适配器相同的正则解析。
- 美股数据集（`XNAS.ITCH`、`EQUS.*`、`DBEQ.*`、`XNYS.PILLAR`、`ARCX.PILLAR` 等）写入
  `stock_minute` 和 `stock_daily`。代码中的空格改为点（`BRK B` → `BRK.B`）。
- 期货交易所数据集（CME Globex 的 `GLBX.MDP3`，以及 `IFUS.*`、`IFEU.*`、`IFLL.*`、`NDEX.*`）写入
  `future_minute`、`future_daily` 和 `future_quote_minute`。单一合约保留原代码（`ZNZ6`）；主力连续代码
  （`ZN.v.0`、`ZN.c.0`、`ZN.n.0`）改为品种代码（`ZN`），`ZN.v.1` 保持不变。跨期价差（`ZNZ6-ZNH7`）和自定义价差丢弃。
  `root` 是品种（`ESZ26` → `ES`，`M2KU6` → `M2K`）。
- 其他数据集跳过。
- parquet 导出文件不带数据集名，路径里有数据集名时用它（如 `…/XNAS.ITCH/…`），否则 OSI 形式的代码当作期权。
- instrument id 按日期从文件自带的 symbology 映射到代码，因为 OPRA 会复用 id。

### 时间规则

- 分钟线按 `ts_event` 切分。
- 交易日按美东时间。
- 股票日线的开高低收取 09:30–16:00（该时段有成交时），成交量和成交笔数取全天，与 massive 日线一致。期权日线用全部成交。
- 定点价格除以 1e9，所以 `56650000000` 精确等于 `56.65`。
- 期货交易时段从美东 18:00 到次日 17:00，所以 18:00 之后的 bar 属于下一个交易日。日线覆盖整个时段；
  `settle` 是时段的最后成交价（交易所 `statistics` schema 中的结算价暂不转换）。Databento 按 UTC 日切文件，
  单独一个文件还会带上下一个时段的前两小时：这些分钟线会保留，但只有该品种 12:00–17:00 的部分也存在时，
  那个时段才会生成日线。

### 报价

报价类 schema 写入两个额外的存储：
- `stock_quote_minute(ticker, window_start, bid_price, ask_price, bid_size, ask_size, trade_date)`。
- `option_quote_minute`，它还带有期权相关的列。

每一行是从 `window_start` 开始的那一分钟结束时的盘口。
- 抽样类 schema（`cbbo-*`、`bbo-*`）的时间戳打在区间结束时，所以要往回移到所属的那一分钟。
- 没有更新的分钟不写入，读取时沿用上一行。
- 同一代码有多个来源时，优先顺序为：全市场合并数据、`cmbp-1`（每次更新）、1 秒抽样、1 分钟抽样。
- `cmbp-1` 文件同时产出成交 K 线和报价。

**采样间隔。** 每个报价存储可以每 1、5、15、30 或 60 分钟只保留一条盘口，而不是每分钟一条：保留每个区间的最后一条
（区间按美东钟点对齐，15 分钟即 09:30、09:45……）。间隔越大，全市场 OPRA 一天的数据越小；无论哪种间隔，读取时都沿用上一行。
在 *数据导入*（*BBO 采样*）中按资产类别设置，或用 `qfz-data convert --quote-interval N`（以及 `--stock-quote-interval`、
`--option-quote-interval`、`--future-quote-interval`），或用环境变量 `QFZ_STOCK_QUOTE_INTERVAL`、`QFZ_OPTION_QUOTE_INTERVAL`、
`QFZ_FUTURE_QUOTE_INTERVAL`。设置保存在数据配置（`quotes.<asset>_interval_min`）中，计划更新会沿用；修改后受影响的分区会重建。

### 夜盘

`OCEA.MEMOIR`（Blue Ocean ATS）在美东 20:00–04:00 交易。即使其他供应商已经写了该代码的日盘 bar，它的分钟线也会加入 `stock_minute`；夜盘时段只跳过完全相同的（代码，分钟）。夜盘成交从不计入日线。分区仍按美东日历日；PMB 把夜盘归到下一个交易日。

### 选源与避免重复计量

- 一个*来源*是一个（数据集，schema）组合，同一来源的所有文件会合并。Databento 按 UTC 日切文件，
  美东 19:00–20:00 的盘后成交在下一天的文件里，合并后不会丢。重叠下载造成的重复K线只保留一份。
- 同一代码同一天有多个来源时，按代码选一个来源：先选全市场合并数据（`EQUS`、`DBEQ`、`OPRA`），
  再选成交量大的。日线的顺序是 `ohlcv-eod`、由分钟线聚合、`ohlcv-1d`、`ohlcv-1h`。
- **补齐优先级：** Databento 只写其他供应商在该分区没写的代码。massive 之后重新转换某分区时，
  会重新过滤 Databento 分片。如果要让 Databento 在某些日期作为主数据源，请把它转换到一个这些日期没有 massive 数据的存储根目录。

### 增量运行

- **阶段 1：** 每个原始文件只抽取一次，结果存为 `$STORAGE_ROOT/_staging/databento/` 下的中间 parquet。
  缓存以文件大小、修改时间和抽取器版本为键，所以改变K线结果的代码更新会让缓存重建。`--jobs N` 并行抽取。
- **阶段 2：** 每个（存储，日期）分区只在其输入指纹变化时重建。输入包括中间文件和其他供应商的分片。
- 原始文件删除后，相关分区会重建，失去全部输入的分片会被删除。
- 当前读不了或抽取失败的文件，沿用它上一次成功的结果，并且本次跳过清理，所以缺包或下载损坏不会删掉数据。

在参考服务器上，转换全部 3,816 个可转换文件（SPY/QQQ/SOXX 的 Nasdaq MBO、OPRA `tcbbo` 和 `cmbp-1`），
`--jobs 12` 用时 28.5 分钟，产出 4,500 万行。无改动重跑用时一秒。

### 命令

```bash
qfz-data status                                  # 按数据集/schema 列出文件，标明是否可转换
qfz-data convert --vendor databento --jobs 8     # 只转换 Databento
qfz-data convert --all                           # 先 massive，再 Databento（补齐），最后公司行动
qfz-data update --source us_databento            # 按新鲜度运行

qfz-data config --set databento.api_key=db-…
qfz-data scan databento                          # 该 key 可查询的数据集（免费调用）
qfz-data acquire databento --dataset OPRA.PILLAR --schema tcbbo \
    --symbols SPY.OPT --stype-in parent --start 2026-09-01 --end 2026-09-05
qfz-data acquire databento --dataset EQUS.MINI --schema ohlcv-1m \
    --symbols SPY,QQQ --start 2026-01-02 --end 2026-01-31 --max-cost 5 --run
```

`acquire` 不加 `--run` 时只做演练，先打印报价。报价超过 `--max-cost` 的请求会被拒绝，`--max-cost` 默认为 0，
所以不给上限时只会下载免费数据。磁盘上已有的文件不会再报价或下载。下载文件存为
`<dataset>/<schema>/<symbol>/<date>.dbn.zst`：tick 类 schema 每个工作日一个文件，OHLCV 每个区间一个文件。

### 已知限制

- 单一交易所的数据只含该交易所的成交量。`XNAS.ITCH` 的 SPY 成交量约为全市场的 17%，全市场成交量请用 `EQUS.*`。
- 供应商之间可能不一致。某个 OPRA 交易日，Databento 的成交笔数比 massive 自己的逐笔文件多约 5%。
  `tcbbo` 与 `cmbp-1` 两个适配器结果完全一致，另一个交易日两家供应商也完全一致。
- 一档以外的盘口深度不转换，因为 UPQ 没有对应的存储。
