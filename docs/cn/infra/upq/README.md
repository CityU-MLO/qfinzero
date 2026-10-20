> English: [../../../../infra/upq/README.md](../../../../infra/upq/README.md)

# UPQ（Rust 价格查询服务）

UPQ 通过 HTTP 提供价格、报价和期权分析，数据来自 `STORAGE_ROOT` 下的 parquet 存储。它自己不导入数据：
数据流水线（`qfz-data`）在原地登记供应商的原始文件，并写出 UPQ 读取的存储（见 `docs/plans/2026-10-20-raw-index-design.md`
和数据导入指南）。QFinZero hub 会用正确的 `STORAGE_ROOT` 启动 UPQ。

## 快速开始

```bash
# 1. 登记并转换原始数据（在仓库根目录）
qfz-data index /data/massive_data /data/databento
qfz-data convert --market us --all

# 2. 编译并运行
cd infra/upq
cargo build --release -p upq-service
STORAGE_ROOT=/data/qfinzero/upq cargo run --release -p upq-service

# 3. 测试
curl http://127.0.0.1:19350/health
```

## 配置

从 `.env.example` 创建一个 `.env` 文件：

```bash
cp .env.example .env
```

### 环境变量

| 变量 | 是否必需 | 默认值 | 说明 |
|----------|----------|---------|-------------|
| `STORAGE_ROOT` | 是 | - | 已导入的 parquet 数据目录路径 |
| `PORT` | 否 | 19350 | 服务绑定的端口 |
| `RUST_LOG` | 否 | info | 日志级别（trace、debug、info、warn、error） |

`.env` 示例：
```bash
PORT=19350
STORAGE_ROOT=/home/qlib/upq_storage
RUST_LOG=info
```

## 工作区

- `crates/upq-core`：schema/校验/OPRA 解析器/SQL 构建器
- `crates/upq-service`：Axum API 路由与请求校验
- `crates/upq-bench`：CSV.GZ 基线与 DuckDB Parquet 的延迟/吞吐基准测试

## 文档
- **API 用法（人类与 agent）：** `docs/api-usage.md`
- Schema：`docs/schemas.md`
- 测试策略：`docs/testing/test-strategy.md`
- 测试矩阵：`docs/testing/test-matrix.md`
- 基准测试报告：`docs/testing/benchmark-report.md`
- 服务只读校验：`docs/testing/server-readonly-validation.md`

## 构建与测试
```bash
cargo fmt --all
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

## 运行服务
```bash
cargo run -p upq-service
```
默认绑定：`127.0.0.1:19350`

API 路由：
- `GET /health`
- `GET /stock`
- `GET /stock/daily`
- `GET /option`
- `GET /option/ticker_query`
- `GET /option/chain_query`
- `GET /rates/query`

## 生产部署（简明版）
1. 构建 release 二进制文件：
```bash
cargo build --release -p upq-service
```

2. 准备运行时目录：
```bash
sudo mkdir -p /opt/upq/bin /var/lib/upq/storage /var/lib/upq/state
sudo cp target/release/upq-service /opt/upq/bin/
```

3. 用 `qfz-data` 生成存储（在仓库根目录）：
```bash
qfz-data index /data/massive_data /data/databento
qfz-data convert --market us --all
```

4. 以指定 storage 路径运行服务：
```bash
STORAGE_ROOT=/var/lib/upq/storage /opt/upq/bin/upq-service
```

5. `systemd` 服务示例（`/etc/systemd/system/upq.service`）：
```ini
[Unit]
Description=UPQ Price Query Service
After=network.target

[Service]
Type=simple
Environment=STORAGE_ROOT=/var/lib/upq/storage
ExecStart=/opt/upq/bin/upq-service
Restart=always
RestartSec=3
User=qlib
WorkingDirectory=/opt/upq

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now upq
sudo systemctl status upq
```

6. 健康检查：
```bash
curl -sS http://127.0.0.1:19350/health
```

注意事项：
- 服务当前绑定 `127.0.0.1:19350`；如需对外暴露，请通过反向代理。
- 回滚：在 `/opt/upq/bin` 下保留上一个二进制文件并重启 `upq` 服务。

## 基准测试
针对 gzip CSV 基线与 DuckDB Parquet 运行股票分钟基准测试：
```bash
cargo run -p upq-bench -- \
  --raw-root ./raw_sample \
  --storage-root ./storage \
  --ticker AAPL \
  --start 2025-12-31T09:30:00 \
  --end 2025-12-31T16:00:00 \
  --iterations 20 \
  --warmup 3
```

## 服务只读校验
```bash
./scripts/validate_server_readonly.sh qlib
```
