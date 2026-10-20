# QFZ 行情数据索引格式（v0.3，2026-10-20）

目标：用户指定一个或多个数据目录，QFZ 自动扫描并建立索引，**不做格式转换**，直接读原生文件。支持 massive 和 Databento 的原生格式，也让用户按一套标准字段提供自定义数据。

这份文档定义四件事：

1. 目录怎么被识别；
2. 索引里存什么；
3. 对外的标准字段；
4. 自定义数据要满足什么条件。

依据的测试结果见 [VSTORE_TEST.md](VSTORE_TEST.md) 和 [BENCH.md](BENCH.md)。

---

## 1. 三层结构

```
数据目录（用户的，只读）        索引（QFZ 的）                逻辑数据集（对外不变）
/data/massive_data      ─┐   _state/index/catalog.parquet   stock_minute
/data/databento         ─┼─► _state/index/symbols.parquet ─► option_minute
/data/my_custom_bars    ─┤   _state/index/pidx/…  (sidecar) stock_quote_minute
                         ┘   _state/index/views/…           option_day …
```

- **数据目录**：QFZ 只读，不在用户目录里写任何东西。
- **索引**：放在 QFZ 自己的 `_state/index/`，可以随时删掉重建。
- **逻辑数据集**：名字和字段就是现在的 store（`qfinzero/pipeline/schema.py`）。UPQ、MCP、PMB、回测只认这一层，所以都不用改。

## 2. 识别：扫描时怎么知道每个文件是什么

扫描时**按内容判断，不靠目录名**（目录名只当作提示）。每个文件交给第一个认得它的 *adapter*：

| adapter | 认得的文件 | 判断依据 |
|---|---|---|
| `massive.aggs` | `*/minute_aggs_v1/YYYY/MM/YYYY-MM-DD.parquet`、`day_aggs_v1` | parquet schema 是 `ticker, volume, open, close, high, low, window_start, transactions` |
| `massive.quotes` | `quotes_v1/…parquet` | 有 `sip_timestamp, bid_price, ask_price` |
| `massive.global` | `global_crypto|global_forex/…csv.gz` | CSV 表头 + 路径 |
| `databento.dbn` | `*.dbn`、`*.dbn.zst` | DBN header（dataset、schema、时间范围、symbology） |
| `databento.parquet` | Databento 导出的 parquet | 有 `rtype, ts_event, symbol` |
| `qfz.standard` | 带 `qfz.dataset.yaml` 的目录里的 parquet | 清单文件（§5） |

认不出的文件会列在扫描报告里（例如"未识别 12 个文件"），**不会静默忽略**。Databento 的 `cmbp-1` 和非 Blue Ocean 的 `mbo` 会被识别并登记，但标记为"不在范围内"（已经这样实现了）。

## 3. 索引里存什么

### 3.1 文件目录 `catalog.parquet`（每个文件或 row group 一行）

| 字段 | 说明 |
|---|---|
| `path`, `size`, `mtime_ns`, `head_hash` | 指纹。大小或 mtime 变了就重建这一行；`head_hash` 是前 64 KB 的哈希，用来识别"文件被替换但 mtime 没变"的情况 |
| `adapter`, `vendor`, `dataset`, `schema` | 例如 `databento.dbn` / `databento` / `OPRA.PILLAR` / `cbbo-1m` |
| `kind` | `bar` / `quote` / `trade` / `book` / `reference` |
| `asset_class`, `market` | `stock|option|future|crypto|fx|index`，`us|cn|global` |
| `resolution` | `1m` / `1d` / `tick` / `1s` … |
| `trade_date_min`, `trade_date_max` | 按 §4.3 的日期规则算出来的 |
| `ts_min`, `ts_max` | UTC 纳秒 |
| `rows`, `row_group`, `rg_symbol_min`, `rg_symbol_max` | parquet 的 row group 统计（只读 footer 得到） |
| `access` | `seek` / `scan` / `whole`，文件内部能不能跳着读（见 §6） |
| `level` | 合规等级 L0/L1/L2（§5.4） |
| `scope` | `in` / `out`（例如 cmbp-1）/ `error` |

实测规模：146 GB 的 massive 分钟 K，目录只有 290 KB，扫一遍 footer 约 30 秒。

### 3.2 代码目录 `symbols.parquet`

每行是 `(symbol, file, trade_date_min, trade_date_max, rows)`。

- 用途：查"这个代码在哪些文件、哪几天有数据"时，不必打开文件。
- Databento 需要每天一份 `instrument_id → symbol` 对照表，因为 OPRA 会重复使用同一个 `instrument_id`。

### 3.3 定位 sidecar `pidx/…`（可选，按文件）

- **parquet**：
  - 每个 data page 的位置，从 page header 读出来；
  - 每 8,192 行记一个 ticker 标记。
  - 大小约为原数据的 0.075%，146 GB 约 110 MB。
  - 期权查询比转换后的 store 还快：2,124 对 1,659 QPS。
- **DBN**：
  - 每个合约的行数和时间范围；
  - 如果文件有多个 zstd frame，再记 frame 偏移。Databento 原档只有一个 frame，记不了。

### 3.4 派生数据 `derived/…`（实体化，不是转换）

只有满足下面任一条件，才写一份实体文件：

| 条件 | 例子 | 原因 |
|---|---|---|
| 结果比原始数据小很多（低于原始的 10%） | MBO 重放成分钟 BBO、逐笔成交聚合成分钟 K、分钟 K 聚合成日 K、夜盘日 K | 每次现算太慢，存下来又很小 |
| 原始格式不能跳着读，而且常被查 | Databento 单 frame 的 `cbbo-1m`、massive 的 `csv.gz` | 一次查询要解压整个文件（0.1–0.6 秒） |
| 原始格式查得太慢 | massive 股票分钟 K（字典页很大） | 实测只有 store 的三分之一速度，见 §6 |

派生文件带来源指纹：原始文件变了，派生结果自动失效并重算。

## 4. 标准字段（逻辑数据集）

对外的字段**就是现在的 store schema**，下面是摘要。完整定义以 `qfinzero/pipeline/schema.py` 为准，新字段只能加，不能改名。

### 4.1 每种数据的必备字段

| kind | 必备 | 可选 |
|---|---|---|
| bar | `ticker`, `window_start`（分钟 K）或 `trade_date`（日 K）, `open`, `high`, `low`, `close` | `volume`, `transactions`, `vwap` |
| quote | `ticker`, `window_start`, `bid_price`, `ask_price` | `bid_size`, `ask_size`, `venue` |
| trade | `ticker`, `ts`, `price`, `size` | `side`, `venue`, `conditions`（QFZ 会聚合成分钟 K，属于派生数据） |

各资产类别的附加字段：

- **期权**：`contract, underlying, expiry, strike, right`（可以从 OCC 代码解析）。
- **期货**：`root, instrument_id`（`instrument_id` 只有连续合约需要）；日 K 另有 `settle, settle_source`。
- **加密货币和外汇**：`base, quote`。

### 4.2 时间

- **存储一律用 UTC 纳秒**（`window_start BIGINT`）。
- **分钟 K 的时间戳表示区间开始**。在区间结束时打时间戳的来源（例如 Databento 的 sampled schema）由 adapter 往回移一分钟。
- **自定义数据**可以用整数 epoch（单位要声明：s、ms、us、ns），或带时区偏移的 ISO-8601 字符串。
  - **没有时区的时间必须在清单里声明 `timezone`，QFZ 不猜**。这次就踩过这个坑：DuckDB 把 Tiingo 的时间当成服务器的本地时区（UTC+8），整整偏了 8 小时。
- **价格用小数**。定点整数价格要声明 `price_scale`，例如 Databento 是 1e-9。

### 4.3 日期归属（`trade_date`）

| 市场 / 时段 | 规则 |
|---|---|
| 美股日盘和盘前盘后（04:00–20:00 ET） | 美东日历日 |
| 美股夜盘（20:00–04:00 ET） | 分钟分区按美东日历日；日 K 归到下一个交易日（NYSE 日历，`market_calendar.py`） |
| 期货 | CME session：前一天 18:00 ET 到当天 17:00 ET |
| 加密货币、外汇 | UTC 日 |
| A 股（下一步） | 北京时间日；交易时段 09:30–11:30、13:00–15:00；沪深交易所日历；只有日期的公告按收盘后可见处理（见 §8） |

`as_of` 时间锁按这张表决定每种数据何时定稿，所有数据源共用一份规则。

### 4.4 代码写法（symbology）

| 资产 | 标准写法 | 例子 |
|---|---|---|
| 美股 | 交易所代码，类别股用 `.` | `AAPL`, `BRK.B` |
| 期权 | `O:` + OCC 21 位（去掉空格） | `O:SPY250117C00500000` |
| 期货 | 合约或 root；连续合约用 root | `ZNZ6`, `ZN` |
| 加密货币、外汇 | `BASE-QUOTE`（API 加前缀 `X:` / `C:`） | `BTC-USD`, `EUR-USD` |
| A 股 | 交易所前缀 + 6 位代码（`SH` 上交所、`SZ` 深交所、`BJ` 北交所） | `SH600519`, `SZ000001`, `BJ430047` |

各 adapter 负责把原生代码转成这套写法：Databento OSI 转 `O:`，`ZN.v.0` 转 `ZN`，Tushare 的 `600519.SH` 转 `SH600519`。store 里已有的 A 股数据还是 Tushare 写法，接 A 股时要重转一次。

## 5. 自定义数据

### 5.1 清单文件 `qfz.dataset.yaml`

放在数据目录的根部。QFZ 看到它，就按 `qfz.standard` adapter 读这个目录：

```yaml
qfz_dataset: 1                 # 清单格式版本
name: my_vendor_cn_minute
vendor: my_vendor              # 用来排优先级、显示来源
kind: bar                      # bar | quote | trade
resolution: 1m
asset_class: stock
market: cn
files: "**/*.parquet"          # 只支持 parquet
time:
  column: dt                   # 原始列名
  unit: iso                    # s | ms | us | ns | iso
  timezone: Asia/Shanghai      # 没有偏移的时间必须写
  convention: start            # start | end（K 线时间戳在区间开始还是结束）
columns:                       # 原始列名 -> 标准字段（同名的可以不写）
  code: ticker
  vol: volume
price_scale: 1                 # 定点整数价格才需要
symbol_format: "{exchange}{code}"    # 可选：代码怎么转成标准写法，例如 SH600519
priority: 50                   # 同一数据集有多个来源时的排序，越大越优先
license: "internal use only"   # 只做显示
```

### 5.2 检查工具

`qfz-data check <dir>` 会读清单、抽样文件，然后报告下面几项：

- 缺了哪些必备字段，类型对不对；
- 时间是否落在声明的时段内，有没有重复的（代码，时间）；
- 价格是否为正，`high ≥ max(open, close)`，`low ≤ min(open, close)`；
- 能达到的合规等级，以及怎么升级（§5.4）。

### 5.3 推荐的文件布局（不强制）

- 只支持 parquet（建议 zstd 压缩），一天一个文件（或 `trade_date=YYYY-MM-DD/` 分区）；
- 按 `(ticker, 时间)` 排序；
- row group 约 12 万行，打开 page index（pyarrow `write_page_index=True`）。

按这样写，QFZ 不用转换，速度也和 store 一样。

### 5.4 合规等级

| 等级 | 条件 | 查询方式 |
|---|---|---|
| **L0 可读** | adapter 读得出来，时间可以解析 | 每次扫描整个文件 |
| **L1 已索引** | 目录有时间范围和代码范围（parquet footer 统计，或扫描一次后建的代码目录） | 先挑文件再扫，默认就是这一级 |
| **L2 快速** | 按代码排序，并且 row group 不大于约 13 万行或有 page index（或 QFZ 建的 sidecar） | 只解码需要的 page，和 store 一样快 |

massive 期权分钟 K 原档是 L1，加上 sidecar 后到 L2。Databento 原档最高只能到 L1，因为单 frame 不能跳着读，所以它的分钟数据走派生（§3.4）。

## 6. 各原生来源的实际处理（依据实测）

| 来源 | 文件内部 | 处理方式 | 实测 |
|---|---|---|---|
| massive 期权分钟 K | 已排序，page 每 2 万行一个，字典小（约 40 KB） | **原地读 + sidecar** | 2,124 QPS，store 1,659 QPS |
| massive 股票分钟 K | 已排序，但字典页 0.7–0.9 MB（碎股成交量） | **继续实体化**，或字典缓存（还没测） | 原地读 237 QPS，store 747 QPS |
| massive 日 K | 很小 | 原地读 | — |
| massive `csv.gz`（加密货币、外汇） | gzip 不能跳读，要解析文本 | 实体化 | — |
| Databento `ohlcv-1m`、`cbbo-1m`、`tcbbo` | 单 zstd frame | 实体化成分钟数据 | 一次查询要解压整个文件 0.1–0.6 秒 |
| Databento Blue Ocean `mbo` | 单 frame，逐笔委托 | 派生：分钟 BBO、夜盘 K（已实现） | 417 个文件 31 秒 |
| `qfz.standard` 自定义数据 | 看用户写法 | L2 原地读；L0/L1 可选实体化 | — |

另外有两个已知的原生格式问题，扫描时会登记，读取时修正：

- massive 2020–2022 年有 776 个期权文件，row group 之间没有按 ticker 排序。sidecar 会记成"未排序"，这些文件退回读整个 row group。
- massive 2026 年有 165 个股票文件 `volume` 是小数（碎股）。标准字段 `volume` 维持整数（已决定），这些文件读取时四舍五入，扫描报告会标出受影响的文件。

## 7. 来源优先级和合并

- 同一逻辑数据集有多个来源时，**每个（代码，交易日，时段）只用一个来源**，不逐行混用。
- 来源由高到低：清单里的 `priority`；内置默认值是"交易所原始 > 全市场合并 > 聚合商"。
- 现在的实现已经是这样：Databento 补 massive 没有的代码。
- 冲突和被替换的来源会写进目录，UI 可以显示"这一格的数据来自哪里"。

**写入位置**：索引和 sidecar 都只写在 QFZ 的 `_state/index/`（已决定）。

## 8. 时间对齐的统一规则（A 股之前要定下来）

- 所有来源进来就转成 UTC，日期归属用 §4.3 那张表，规则只写一份。现在分散在 converter 和 UPQ 两处，要收拢。
- 新闻、公告这类只有日期的事件（`time_precision = day`）一律视为**当天收盘后才可见**，避免回测时看到未来。
  - Tushare 公告现在存成北京时间零点，会提早约 15 小时可见。
- 价格数据和事件数据用同一个 `as_of`。

## 9. 实施顺序（每一步都先做等价测试）

1. **目录 + adapter 框架**（已完成，2026-10-20，分支 `feature/raw-index`）：`qfz-data index <dir>` 建 `catalog.parquet` 和 `symbols.parquet`；UI 的"本地文件"改成选目录、扫描、看报告。这一步不改读取路径。
2. **massive 期权分钟 K 改成原地读**：UPQ 用目录提供的文件清单加 view 读取，点查走 Rust 的 page-index 读取器。验收标准：抽样几十天逐行相同，速度不低于 store。
3. **`qfz.standard` 自定义数据**：清单、`qfz-data check`、L0 到 L2。
4. 其他来源按 §6 逐类迁移。股票分钟 K 先测字典缓存，再决定要不要继续实体化。
5. 统一时间规则，然后接 A 股（§8）。

## 10. 已定（2026-10-20）

1. 索引和 sidecar 放在 QFZ 的 `_state/index/`，不写进用户的数据目录。
2. `volume` 维持整数，碎股成交量四舍五入。
3. 自定义数据只支持 parquet。
4. A 股代码写成 `SH600519` / `SZ000001` / `BJ430047`。
5. **范围**：数据来源是 massive 和 Databento 混合，同一个（代码、交易日、时段）只用一个来源；最高级别是分钟 K、BBO 和日 K，不支持 MBO、MBP（Blue Ocean 也一样，之后重新下载它的 K 线和 BBO）；不接 Tiingo。
6. **不转存**：行情只有一套索引，本地不再写转换后的 store；派生数据只保留查询时现算的部分。
7. **massive 统一成 parquet**：`global_crypto`、`global_forex` 的 csv.gz 在原始库里转成 parquet（按代码和时间排序、row group 12 万行、带 page index，也就是 L2），之后下载器下载完就转；原本的 csv.gz 经确认后删除。
