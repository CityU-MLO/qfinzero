> English: [../../../../demos/upq/README.md](../../../../demos/upq/README.md)

# UPQ 演示

通过 `UPQClient` 查询股票、期权和国债利率数据的演示。

## 前置条件

UPQ 服务已运行且数据已加载：

```bash
cd infra/upq
STORAGE_ROOT=~/upq_storage cargo run -p upq-service
# Verify: curl http://127.0.0.1:19350/health
```

## 演示

```bash
cd qfinzero  # run from project root

python demos/upq/stock_query.py    # Daily + minute stock bars
python demos/upq/option_query.py   # Option chain + contract queries
python demos/upq/rates_query.py    # Treasury yield curve data
```

### stock_query.py

- 获取 AAPL 和 MSFT 的每日 OHLCV 数据
- 选择特定字段以减小载荷大小
- 获取分钟级日内 K 线
- 将纳秒时间戳转换为 datetime

### option_query.py

- 使用行权价/到期日/类型筛选查询期权链
- 使用 `UPQClient.make_opra()` 构建 OPRA 合约 ID
- 获取特定合约的每日和分钟 K 线
- 期权链发现 → 合约详情的工作流

### rates_query.py

- 获取完整的收益率曲线（所有期限）
- 筛选特定期限（1M、10Y）
- 计算收益率利差

## 结构

```
demos/upq/
├── README.md           # This file
├── stock_query.py      # Stock price queries
├── option_query.py     # Option chain + contract queries
└── rates_query.py      # Treasury yield queries
```
