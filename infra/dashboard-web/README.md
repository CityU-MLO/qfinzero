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
