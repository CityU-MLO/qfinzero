# Data Platform Frontend Monitoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Next.js + shadcn/ui monitoring frontend for core data-platform operations: service status/freshness, news browser, calendar browser, and sanity checks.

**Architecture:** Use Next.js App Router with server components for initial data fetch and lightweight client components for query interactions/tables/charts. Keep API contract-safe typed fetchers in a single lib module and map backend payloads to UI-focused view models. Reuse shadcn-style primitives and Recharts for core trend/coverage visualizations.

**Tech Stack:** Next.js 15, React 19, TypeScript, Tailwind CSS, shadcn/ui component patterns, TanStack Query, Recharts, Vitest + Testing Library.

---

### Task 1: Bootstrap Frontend Workspace

**Files:**
- Create: `infra/dashboard-web/package.json`
- Create: `infra/dashboard-web/tsconfig.json`
- Create: `infra/dashboard-web/next.config.ts`
- Create: `infra/dashboard-web/postcss.config.mjs`
- Create: `infra/dashboard-web/components.json`
- Create: `infra/dashboard-web/src/app/layout.tsx`
- Create: `infra/dashboard-web/src/app/globals.css`
- Modify: `.gitignore`

**Step 1: Write failing validation command**

Run: `cd infra/dashboard-web && pnpm typecheck`
Expected: FAIL because project files do not exist yet.

**Step 2: Add minimal Next.js + Tailwind + scripts setup**

Define build/dev/test/typecheck scripts and base compiler config.

**Step 3: Re-run typecheck**

Run: `cd infra/dashboard-web && pnpm typecheck`
Expected: PASS with zero TS errors.

### Task 2: Implement Typed API Layer + Freshness Logic

**Files:**
- Create: `infra/dashboard-web/src/lib/types.ts`
- Create: `infra/dashboard-web/src/lib/config.ts`
- Create: `infra/dashboard-web/src/lib/time.ts`
- Create: `infra/dashboard-web/src/lib/status.ts`
- Create: `infra/dashboard-web/src/lib/api.ts`
- Create: `infra/dashboard-web/src/lib/status.test.ts`

**Step 1: Write failing tests**

Add tests for:
- stale/running/down classification
- freshness timestamp normalization (ISO and epoch ns)
- 5-minute request/error aggregation from stats payload

**Step 2: Run tests to verify fail**

Run: `cd infra/dashboard-web && pnpm test`
Expected: FAIL due missing implementation.

**Step 3: Add minimal implementations**

Implement typed endpoint fetchers and status derivation helpers.

**Step 4: Re-run tests**

Run: `cd infra/dashboard-web && pnpm test`
Expected: PASS.

### Task 3: Build Core Monitoring Dashboard (Status + Freshness)

**Files:**
- Create: `infra/dashboard-web/src/app/page.tsx`
- Create: `infra/dashboard-web/src/components/status/status-grid.tsx`
- Create: `infra/dashboard-web/src/components/status/service-card.tsx`
- Create: `infra/dashboard-web/src/components/charts/freshness-trend-chart.tsx`
- Create: `infra/dashboard-web/src/components/ui/*` (button/card/input/table/tabs/badge/etc.)

**Step 1: Write failing component test**

Add tests asserting stale badge and freshness rendering with mock data.

**Step 2: Run targeted test**

Run: `cd infra/dashboard-web && pnpm test src/components/status/status-grid.test.tsx`
Expected: FAIL.

**Step 3: Implement status cards + summary widgets**

Add Running/Down/Stale chip, uptime/request/error metrics, freshness table.

**Step 4: Re-run targeted test**

Expected: PASS.

### Task 4: Build News Browser (Query + Table + Detail + Export)

**Files:**
- Create: `infra/dashboard-web/src/app/news/page.tsx`
- Create: `infra/dashboard-web/src/components/news/news-search-panel.tsx`
- Create: `infra/dashboard-web/src/components/news/news-table.tsx`
- Create: `infra/dashboard-web/src/components/news/news-detail-drawer.tsx`
- Create: `infra/dashboard-web/src/components/news/news-stats-charts.tsx`

**Step 1: Write failing tests for query-state and row selection**

Cover:
- preset quick query generation
- details drawer receives full payload

**Step 2: Run tests and verify fail**

Run: `cd infra/dashboard-web && pnpm test src/components/news/*.test.tsx`
Expected: FAIL.

**Step 3: Implement UI with API integration**

Implement filters (ticker/date/publisher/keyword), paginated table, export URL actions, row detail JSON panel.

**Step 4: Re-run tests**

Expected: PASS.

### Task 5: Build Calendar Browser + Coverage Visualization

**Files:**
- Create: `infra/dashboard-web/src/app/calendar/page.tsx`
- Create: `infra/dashboard-web/src/components/calendar/calendar-filters.tsx`
- Create: `infra/dashboard-web/src/components/calendar/calendar-table.tsx`
- Create: `infra/dashboard-web/src/components/calendar/coverage-heatmap.tsx`

**Step 1: Write failing tests**

Cover:
- date-range filter serialization
- coverage matrix generation from daily_counts

**Step 2: Run tests to fail**

Run: `cd infra/dashboard-web && pnpm test src/components/calendar/*.test.tsx`
Expected: FAIL.

**Step 3: Implement earnings/econ data explorer + coverage chart**

Include row JSON detail and export controls.

**Step 4: Re-run tests**

Expected: PASS.

### Task 6: Build Sanity Check Page + Final Verification

**Files:**
- Create: `infra/dashboard-web/src/app/sanity/page.tsx`
- Create: `infra/dashboard-web/src/components/sanity/sanity-report.tsx`
- Modify: `infra/dashboard-web/src/app/page.tsx`
- Modify: `README.md`

**Step 1: Write failing test for status badge mapping**

Verify pass/warn/fail display and sample rendering.

**Step 2: Run test to fail**

Run: `cd infra/dashboard-web && pnpm test src/components/sanity/*.test.tsx`
Expected: FAIL.

**Step 3: Implement report UI**

Render summary counters, check list, samples JSON snippets.

**Step 4: Final verification**

Run:
- `cd infra/dashboard-web && pnpm typecheck`
- `cd infra/dashboard-web && pnpm test`
- `cd infra/dashboard-web && pnpm lint`
- `cd infra/dashboard-web && pnpm build`

Expected: all PASS.
