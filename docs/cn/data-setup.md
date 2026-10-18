# 数据导入工具

> English: [docs/en/data-setup.md](../en/data-setup.md)

*数据导入*（仅管理员，位于控制台顶栏）用于把 Databento 和 massive 的数据导入 QFinZero。每个供应商都支持两种方式：

- **本地文件**：用文件浏览器选择服务器上已有的目录或文件并导入。
- **下载**：保存密钥，填写下载内容，查看报价后下载。

两种方式最后都执行与 `qfz-data convert` 相同的增量转换，导入的数据会出现在 *数据可用性*、UPQ 以及所有 MCP 工具中。

## 数据存放位置

| 路径 | 作用 |
|---|---|
| `RAW_DATABENTO_DIR`、`RAW_MASSIVE_DIR` | 各供应商的*原始库*；下载的文件存放在这里，导入的文件以链接方式加入这里 |
| `STORAGE_ROOT`（默认 `$QFZ_DATA_ROOT/upq`） | 转换后的 QFinZero 存储，由 UPQ 提供服务 |

页面顶部显示这三个路径以及各供应商是否已设置密钥。

## 导入本地文件

1. 选择 **Databento** 或 **massive**，再选 **本地文件** 标签。
2. 浏览服务器。浏览器只显示允许的根目录：各原始库、`QFZ_DATA_ROOT` 和 `/data`，或 `QFZ_BROWSE_ROOTS`
   中列出的目录（以 `:` 分隔）。路径会被解析，符号链接和 `..` 都无法越出这些目录。标签标出识别到的内容
   （DBN、massive parquet、massive csv.gz、Databento 数据集目录）。
3. 勾选目录或文件（或点 *选择此目录*），再点 **检查**：
   - massive：识别到的数据集（`us_stocks_sip/day_aggs_v1`、`…/minute_aggs_v1`、`us_options_opra/…`）、天数、日期范围，
     以及有多少 `.csv.gz` 文件会转换为 parquet；
   - Databento：每个（数据集，schema）的日期范围，以及能否转换为 K 线或报价（definition、statistics、status 文件是参考数据）。
4. 点 **导入并转换**，会启动一个任务，可在 *任务* 中查看日志。

导入的具体行为：

- massive 的日文件以链接方式加入 `RAW_MASSIVE_DIR/<dataset>/YYYY/MM/`；`.csv.gz` 文件会在这里转换为 zstd parquet。
  之后按导入的日期范围转换每个数据集。
- Databento 的选择以链接方式加入 `RAW_DATABENTO_DIR/imports/`，然后对整个原始库执行 Databento 转换。
  因为每次导入都保留在原始库中，后续导入不会丢失之前导入的数据。文件是链接而不是复制，请保留原文件。
- 再次导入相同内容不会新增链接，转换也会跳过输入未变化的分区。

## 报价（BBO）与采样间隔

两家供应商都可以写入分钟报价存储。PMB 按它成交，期权链快照也从中读取买卖价：

- Databento：`cbbo-1m`、`cbbo-1s`、`bbo-*`、`cmbp-1`（股票和 OPRA），以及期货交易所的 `mbp-1` / `mbp-10`。
- massive：`us_options_opra/quotes_v1` 和 `us_stocks_sip/quotes_v1` flat files（逐笔，数据量很大）、
  REST 报价样本（`*.jsonl.gz`）和 30 分钟快照 parquet。检查时会显示每类文件各有多少。

*BBO 采样* 按资产类别（股票、期权、期货）设置：保留每分钟的盘口，还是只保留每 5、15、30 或 60 分钟的最后一条。
15 分钟可以让全市场 OPRA 一天的数据小到笔记本也放得下；中间的时间，券商和期权链快照沿用上一条盘口。
设置会保存，之后的转换和计划更新都会使用；修改后，下次转换的报价分区会重建。

## 期货

CME Globex（`GLBX.MDP3`）以及 ICE、Nodal 交易所的 Databento 文件会转换为 `future_minute`、`future_daily` 和
`future_quote_minute`。`mbo`、`trades`、`ohlcv-1m` 或 `mbp-1` 目录和其他 Databento 数据一样导入即可。
连续代码（`CL.v.0`）改为品种代码（`CL`），单一合约保留原代码。交易日按 CME 时段划分（前一天美东 18:00 到当天 17:00）。
*数据可用性* 中有三个期货数据层，券商按交易所方式计算保证金进行期货交易（见 PMB 指南）。

## 下载

1. 选择供应商和 **下载** 标签。
2. 填写一次凭证；凭证由数据服务保存在 `$QFZ_DATA_ROOT/_state/qfz.config.json`，之后不再显示。
   - Databento：Databento 门户中的 API 密钥。
   - massive：massive 控制台中 flat files 的 S3 Access Key ID 和 Secret，以及端点
     （`https://files.massive.com`；默认的 `https://files.polygon.io` 也可用）。
3. 填写请求：
   - Databento：数据集（例如 `EQUS.MINI`、`XNAS.ITCH`、`OPRA.PILLAR`、`OCEA.MEMOIR`）、schema、代码
     （`SPY,QQQ`；整条期权链用 `SPY.OPT` 并把代码类型设为 *parent*）、日期和费用上限（美元）。
   - massive：聚合或报价数据集之一，以及日期。
4. **报价** / **预览** 显示将要下载的内容：Databento 的费用和计费数据量（报价免费），或 massive 缺少的天数和数据量。
   磁盘上已有的文件不计入。
5. **下载并转换** 会启动任务。报价超过上限的 Databento 请求会被拒绝；上限默认为 0，所以不填金额时只会下载免费数据。

下载使用与命令行（`qfz-data acquire databento …`）相同的目录结构，两者可以接着对方的进度继续。

## 存储状态

**存储状态** 标签即原来的 *数据* 页面：按数据源对照原始数据与已转换的存储，可对计划的转换执行 *预演* 和 *更新*。
事件库的数据检查也从这里进入。

## 依赖与限制

- Databento 下载需要 `pip install -e ".[databento]"`；massive 下载需要 `pip install -e ".[massive]"`（boto3）。Docker 镜像已包含两者。
- massive 的 trades flat files 暂不转换（还没有适配器）。OPRA 的 quotes flat files 每天几十到几百 GB，下载前请先预览。
- 任务在服务器上运行；离开页面不会中断任务，日志保留在 *任务* 中。
