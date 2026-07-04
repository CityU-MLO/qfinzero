> **English** (below) · [中文](#中文文档) (在下方)

# QFinZero Dashboard Web (Next.js)

Monitoring frontend for QFinZero data platform operations.

## Features

- Health & status cards for UPQ / ESP / PMB
- Freshness lag signals and stale detection
- MongoDB news browser (query, detail JSON, export)
- SQLite calendar browser (earnings/economic query, heatmap, export)
- Sanity check report view

## Quick Start

```bash
cd infra/dashboard-web
pnpm install --no-frozen-lockfile
pnpm dev
```

Open `http://127.0.0.1:19400`.

## Backend Endpoints

By default this app connects to:

- `UPQ_BASE_URL=http://127.0.0.1:19350`
- `ESP_BASE_URL=http://127.0.0.1:19330`
- `PMB_BASE_URL=http://127.0.0.1:19380`

Override with env vars:

```bash
UPQ_BASE_URL=http://127.0.0.1:19350 \
ESP_BASE_URL=http://127.0.0.1:19330 \
PMB_BASE_URL=http://127.0.0.1:19380 \
pnpm dev
```

## Verification

```bash
pnpm typecheck
pnpm test
pnpm lint
pnpm build
```

---

<a id="中文文档"></a>

# 中文文档

# QFinZero Dashboard Web (Next.js)

QFinZero 数据平台运维的监控前端。

## 功能特性

- UPQ / ESP / PMB 的健康与状态卡片
- 新鲜度延迟信号与陈旧检测
- MongoDB 新闻浏览器（查询、详情 JSON、导出）
- SQLite 日历浏览器（财报/经济日历查询、热力图、导出）
- 完整性检查（sanity check）报告视图

## 快速开始

```bash
cd infra/dashboard-web
pnpm install --no-frozen-lockfile
pnpm dev
```

打开 `http://127.0.0.1:19400`。

## 后端端点

默认情况下，本应用连接到：

- `UPQ_BASE_URL=http://127.0.0.1:19350`
- `ESP_BASE_URL=http://127.0.0.1:19330`
- `PMB_BASE_URL=http://127.0.0.1:19380`

可通过环境变量覆盖：

```bash
UPQ_BASE_URL=http://127.0.0.1:19350 \
ESP_BASE_URL=http://127.0.0.1:19330 \
PMB_BASE_URL=http://127.0.0.1:19380 \
pnpm dev
```

## 校验

```bash
pnpm typecheck
pnpm test
pnpm lint
pnpm build
```
