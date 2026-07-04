> **English** (below) · [中文](#中文文档) (在下方)

# UPQ (Rust Price Query Service)

UPQ is a Rust implementation of the price query service with API compatibility goals against the Python `price_query_service`.

## Quick Start

```bash
# 1. Sync data from qlib server
scp scripts/sync_from_qlib.sh qlib:~/
ssh qlib "./sync_from_qlib.sh"

# 2. Build
cargo build --release

# 3. Ingest data
cargo run -p upq-ingest -- ingest \
  --raw-root ~/upq_data \
  --storage-root ~/upq_storage \
  --manifest ~/upq_state/manifest.sqlite

# 4. Configure environment
cp .env.example .env
# Edit .env to set your STORAGE_ROOT and PORT

# 5. Run service
cargo run -p upq-service

# 6. Test
curl http://127.0.0.1:19350/health
```

## Configuration

Create a `.env` file from `.env.example`:

```bash
cp .env.example .env
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `STORAGE_ROOT` | Yes | - | Path to ingested parquet data directory |
| `PORT` | No | 19350 | Server port to bind |
| `RUST_LOG` | No | info | Log level (trace, debug, info, warn, error) |

Example `.env`:
```bash
PORT=19350
STORAGE_ROOT=/home/qlib/upq_storage
RUST_LOG=info
```

## Workspace
- `crates/upq-core`: schema/validation/OPRA parser/SQL builders
- `crates/upq-service`: Axum API routes and request validation
- `crates/upq-ingest`: ingest metadata manifest and idempotency utilities
- `crates/upq-bench`: latency/throughput benchmark for CSV.GZ baseline vs DuckDB Parquet

## Docs
- **API usage (human & agent):** `docs/api-usage.md`
- Design: `docs/plans/2026-02-09-upq-design.md`
- Implementation plan: `docs/plans/2026-02-09-upq-implementation-plan.md`
- Schemas: `docs/schemas.md`
- Test strategy: `docs/testing/test-strategy.md`
- Test matrix: `docs/testing/test-matrix.md`
- Benchmark report: `docs/testing/benchmark-report.md`
- Server read-only validation: `docs/testing/server-readonly-validation.md`

## Build and Test
```bash
cargo fmt --all
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

## Sync Data from qlib Server

The service requires data from the qlib server. Run the sync script to copy data to the expected directory structure:

```bash
# Copy sync script to qlib server
scp scripts/sync_from_qlib.sh qlib:~/

# Run sync (creates ~/upq_data with ~30GB of data)
ssh qlib "./sync_from_qlib.sh"

# Or test with dry-run first
ssh qlib "./sync_from_qlib.sh --dry-run"
```

Expected output:
- Stock day files: 1003
- Stock minute files: 1003
- Option day files: 543
- Option minute files: 543
- Treasury yields: 1
- Dividends SQLite: 1

## Run Service
```bash
cargo run -p upq-service
```
Default bind: `127.0.0.1:19350`

API routes:
- `GET /health`
- `GET /stock`
- `GET /stock/daily`
- `GET /option`
- `GET /option/ticker_query`
- `GET /option/chain_query`
- `GET /rates/query`

## Production Deployment (Concise)
1. Build release binaries:
```bash
cargo build --release -p upq-ingest -p upq-service
```

2. Prepare runtime directories:
```bash
sudo mkdir -p /opt/upq/bin /var/lib/upq/storage /var/lib/upq/state
sudo cp target/release/upq-ingest target/release/upq-service /opt/upq/bin/
```

3. Run one-time ingest (using synced data from ~/upq_data):
```bash
/opt/upq/bin/upq-ingest ingest \
  --raw-root /home/qlib/upq_data \
  --storage-root /var/lib/upq/storage \
  --manifest /var/lib/upq/state/manifest.sqlite
```

4. Run service with storage path:
```bash
STORAGE_ROOT=/var/lib/upq/storage /opt/upq/bin/upq-service
```

5. `systemd` service example (`/etc/systemd/system/upq.service`):
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

6. Health check:
```bash
curl -sS http://127.0.0.1:19350/health
```

Notes:
- Service currently binds `127.0.0.1:19350`; expose externally via reverse proxy if needed.
- Rollback: keep previous binary under `/opt/upq/bin` and restart `upq` service.

## Ingest Sample Data
In this workspace, sample data is expected under `./raw_sample`:
- `raw_sample/stock/day/*.csv.gz`
- `raw_sample/stock/minute/*.csv.gz`
- `raw_sample/options/day/*.csv.gz`
- `raw_sample/options/minute/*.csv.gz`
- `raw_sample/assets/treasury_yields.csv`
- `raw_sample/dividends/massive_dividends.sqlite`

Run ingest:
```bash
cargo run -p upq-ingest -- ingest \
  --raw-root ./raw_sample \
  --storage-root ./storage \
  --manifest ./state/manifest.sqlite
```

Compact partition files (merge multiple parquet files in each `trade_date=` partition):
```bash
cargo run -p upq-ingest -- compact --storage-root ./storage
```

## Benchmark
Run stock-minute benchmark against gzip CSV baseline and DuckDB Parquet:
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

## Server Read-Only Validation
```bash
./scripts/validate_server_readonly.sh qlib
```

---

<a id="中文文档"></a>

# 中文文档

# UPQ（Rust 价格查询服务）

UPQ 是价格查询服务的 Rust 实现，目标是在 API 上与 Python 的 `price_query_service` 保持兼容。

## 快速开始

```bash
# 1. Sync data from qlib server
scp scripts/sync_from_qlib.sh qlib:~/
ssh qlib "./sync_from_qlib.sh"

# 2. Build
cargo build --release

# 3. Ingest data
cargo run -p upq-ingest -- ingest \
  --raw-root ~/upq_data \
  --storage-root ~/upq_storage \
  --manifest ~/upq_state/manifest.sqlite

# 4. Configure environment
cp .env.example .env
# Edit .env to set your STORAGE_ROOT and PORT

# 5. Run service
cargo run -p upq-service

# 6. Test
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
- `crates/upq-ingest`：导入元数据清单与幂等性工具
- `crates/upq-bench`：CSV.GZ 基线与 DuckDB Parquet 的延迟/吞吐基准测试

## 文档
- **API 用法（人类与 agent）：** `docs/api-usage.md`
- 设计：`docs/plans/2026-02-09-upq-design.md`
- 实现计划：`docs/plans/2026-02-09-upq-implementation-plan.md`
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

## 从 qlib 服务器同步数据

该服务需要来自 qlib 服务器的数据。运行同步脚本，将数据复制到预期的目录结构中：

```bash
# Copy sync script to qlib server
scp scripts/sync_from_qlib.sh qlib:~/

# Run sync (creates ~/upq_data with ~30GB of data)
ssh qlib "./sync_from_qlib.sh"

# Or test with dry-run first
ssh qlib "./sync_from_qlib.sh --dry-run"
```

预期输出：
- 股票日线文件：1003
- 股票分钟文件：1003
- 期权日线文件：543
- 期权分钟文件：543
- 国债收益率：1
- 分红 SQLite：1

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
cargo build --release -p upq-ingest -p upq-service
```

2. 准备运行时目录：
```bash
sudo mkdir -p /opt/upq/bin /var/lib/upq/storage /var/lib/upq/state
sudo cp target/release/upq-ingest target/release/upq-service /opt/upq/bin/
```

3. 运行一次性导入（使用从 ~/upq_data 同步的数据）：
```bash
/opt/upq/bin/upq-ingest ingest \
  --raw-root /home/qlib/upq_data \
  --storage-root /var/lib/upq/storage \
  --manifest /var/lib/upq/state/manifest.sqlite
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

## 导入示例数据
在本工作区中，示例数据预期位于 `./raw_sample` 下：
- `raw_sample/stock/day/*.csv.gz`
- `raw_sample/stock/minute/*.csv.gz`
- `raw_sample/options/day/*.csv.gz`
- `raw_sample/options/minute/*.csv.gz`
- `raw_sample/assets/treasury_yields.csv`
- `raw_sample/dividends/massive_dividends.sqlite`

运行导入：
```bash
cargo run -p upq-ingest -- ingest \
  --raw-root ./raw_sample \
  --storage-root ./storage \
  --manifest ./state/manifest.sqlite
```

压实分区文件（合并每个 `trade_date=` 分区中的多个 parquet 文件）：
```bash
cargo run -p upq-ingest -- compact --storage-root ./storage
```

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
