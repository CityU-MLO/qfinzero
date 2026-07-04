# QFinZero Console + Data-Update Orchestration — Design

**Date:** 2026-06-29
**Status:** Design — core decisions locked (§1); first slice = orchestration core
**Scope:** (A) a convert-only **data-update orchestration** layer over all QFinZero
data domains, and (B) a new **chat-first web console** — *QFinZero Console* (Chat · Data ·
PMB · Settings · Doc · →Assay). No implementation in this doc.

---

## 0. Context

QFinZero and **Assay** are sibling systems that **share one raw-data root**
(`/data/massive_data`, `/data/tushare_data`, the news drop dir, …). Each has its own
data protocol and its own converters over that shared raw source.

- **Raw acquisition is external to this design.** Downloads/scrapers are owned
  elsewhere: Assay's stock downloader, QFinZero's existing news scrapers
  (`scripts/news_data.sh`, cron @06:00 UTC), and the massive/tushare vendor drops.
- **Division of labour on the shared raw root:**
  - **Assay** updates **stock prices only**.
  - **QFinZero** updates **most** domains: options, stocks, news, econ, Benzinga earnings (optional).
- **What QFinZero's "update" means here (locked):** *convert-only orchestration* —
  detect newly-arrived raw, run the right convert/load step, validate, and report
  freshness. QFinZero **never re-downloads** and **never writes raw**; it only writes
  its own derived stores (UPQ storage, ESP DBs).

This design adds the missing **orchestration + state model** on top of today's
already-built `qfz-data` converter, and a **new console** to drive and observe it.

### What already exists (reused, not rebuilt)

| Capability | Where | Notes |
|---|---|---|
| Price convert pipeline | `qfinzero/pipeline/` (`qfz-data status\|convert\|validate`) | Idempotent, DuckDB; raw→UPQ parquet; corporate actions; on-read adjust. **Convert only — no "detect new + run" loop yet.** |
| Raw/store registry | `qfinzero/pipeline/registry.py` | Scans raw + storage, reports date ranges / partitions / counts. |
| News/econ/earnings ingest | `scripts/news_data.sh` (`init\|update\|status\|deploy-cron`), `infra/esp/` | Scrapers **download** to a news dir and load Mongo/SQLite. For QFinZero this is the *external drop*; we orchestrate the **load/convert** side. |
| Web (to be superseded) | `infra/dashboard-web` (Next.js :19300) | Tabs Status/News/Calendar/Sanity/**Playground (a working chat UI + LLM config + tool-call cards)**. |
| Chat backend | `infra/playground/` (:19390, `agent.py` streaming) + MCP server (`mcp/`, 37 tools, streamable-HTTP) | Reused as the Chat tab's engine. |
| PMB broker terminal | `infra/pmb/static/` (:19380/ui, modern + win98 themes) | Reused as the PMB tab. |

---

## 1. Locked decisions

| Topic | Decision |
|---|---|
| Update semantics | **Convert-only orchestration.** Detect new raw → convert/load → validate → report. No vendor downloaders in QFinZero. |
| First deliverable | **This design doc.** |
| Web | **New chat-first frontend** (*QFinZero Console*), supersedes `dashboard-web` incrementally. |
| Raw root | Shared, **read in place**, never copied/written by QFinZero. |
| Concurrency w/ Assay | Targets are disjoint (Assay writes *raw stock*; QFinZero writes *derived stores*), plus a per-domain advisory lock + idempotent re-runs. |
| Ports | Stay in the 193xx block; new services slot in (see §6). |
| LLM providers | Gemini · Claude · DeepSeek · GPT, each with a **default endpoint** the user can override, **plus user-defined custom providers** (local vLLM, etc.). |
| **data-admin** | **Separate FastAPI service on :19340** (not Next.js routes) — long jobs + SSE logs; also the cron entry point. |
| **Provider strategy** | **OpenAI-compatible first** (GPT/DeepSeek/vLLM native; Gemini via `/v1beta/openai`; Claude via compat endpoint). Native adapters deferred. |
| **First build slice** | **Orchestration core (CLI):** `qfinzero/update/` registry + manifest + `qfz-data update` (prices), dry-run, lock. |
| **Console brand** | **QFinZero Console.** The `Assay ↗` tab links out to Assay as a sibling product. |

---

## 2. Data domains & convert surfaces

The orchestrator treats every updatable thing as a **Source** with a uniform shape
(see §3.1). The v1 source set:

| Source id | Domain | Owner | Raw (read in place) | Convert/Load step | Target store | Freshness key |
|---|---|---|---|---|---|---|
| `us_stock_daily` | price | QFZ (Assay also) | `massive/us_stocks_sip` | `qfz-data convert --market us --asset stock --resolution daily` | `UPQ/stock_daily` | max `trade_date` |
| `us_stock_minute` | price | QFZ (Assay also) | `massive/us_stocks_sip` (minute) | `… --resolution minute` | `UPQ/stock_minute` | max `trade_date` |
| `us_option_day` | price | **QFZ only** | `massive/us_options_opra` | `… --asset option --resolution daily` | `UPQ/option_day` | max `trade_date` |
| `us_option_minute` | price | **QFZ only** | `massive/us_options_opra` (minute) | `… --asset option --resolution minute` | `UPQ/option_minute` | max `trade_date` |
| `rates` | price | QFZ | `massive/economy/treasury_*.jsonl` | `… --asset rates` | `UPQ/rates` | file mtime |
| `corp_actions` | price | QFZ | massive splits/divs + tushare | `… --asset corp` | `UPQ/corporate_actions` | derived |
| `cn_stock_daily` | price | QFZ (Assay also) | `tushare/cn/daily` | `qfz-data convert --market cn --asset stock` | `UPQ/stock_daily` (CN ns) | max `trade_date` |
| `news` | news | QFZ | news drop dir (Mongo source) | ESP news loader | MongoDB `ticker_news` | max published date |
| `econ` | econ | QFZ | NASDAQ econ raw | ESP econ loader | `nasdaq_econ_events.sqlite3` | max event date |
| `earnings` | earnings | QFZ (optional) | Benzinga raw | ESP earnings loader | `benzinga_earnings.sqlite3` | max as-of date |

Notes:
- **Price sources** already have a converter (`qfz-data`); the orchestrator only adds
  *detect-delta + invoke + record*.
- **News/econ/earnings** currently couple download+load inside `news_data.sh`. For
  convert-only we need a **load-only entry point** the orchestrator can call
  (the load half of those scrapers, decoupled from the download half). This is the
  one piece of new ingestion glue — see §3.6.
- `cn` / HK options are out of scope (no raw). Stock prices are the only domain Assay
  also touches; everything else is QFinZero-exclusive.

---

## 3. Update-orchestration design

A new package **`qfinzero/update/`** (sibling to `qfinzero/pipeline/`) plus a
`qfz-data update` subcommand. It composes existing converters; it does **not**
re-implement them.

### 3.1 Source descriptor

```
Source = {
  id:            str            # "us_option_day"
  domain:        "price"|"news"|"econ"|"earnings"
  market:        "us"|"cn"|None
  owner:         "qfz"|"shared" # "shared" = Assay also updates the raw
  detect():      -> Delta       # new/changed raw since last manifest (mtime+range)
  convert(delta) -> RunResult   # shells to qfz-data convert / ESP loader
  freshness():   -> {raw_max, store_max, lag_days}
}
```

Sources are declared in one registry (`qfinzero/update/sources.py`) so the CLI, the
Data-tab API, and the manifest all share a single definition.

### 3.2 CLI: `qfz-data update`

```
qfz-data update --source all                 # everything QFZ owns, convert-only
qfz-data update --source prices              # all price sources
qfz-data update --source news,econ           # selected
qfz-data update --market us --since 2026-06-01
qfz-data update --dry-run                     # show deltas + planned steps, run nothing
qfz-data status   --json                      # existing; extended with freshness + last-run
```

Behaviour: for each selected source → `detect()` deltas → if non-empty (or `--force`)
→ `convert()` → `validate()` → write manifest entry. Skips cleanly when raw is
unchanged (the common cron case). A **lock file** per domain prevents overlap with a
concurrent Assay/cron run.

### 3.3 State manifest (freshness + run history)

A single small store at `STORAGE_ROOT/_state/update_manifest.sqlite` (or JSON), one
row per (source, run):

| col | meaning |
|---|---|
| `source` | source id |
| `raw_max` | latest raw date/mtime seen |
| `store_max` | latest converted date in the target store |
| `lag_days` | `today - store_max` (business-day aware) |
| `last_run_ts` | when convert last ran |
| `status` | `ok` / `skipped` / `error` |
| `rows` / `partitions` | volume converted |
| `duration_s`, `error` | run telemetry |

`status` (freshness view) = derive **per source** a colour: green (lag ≤ 1bd),
amber (≤ 5bd), red (stale/error). This is exactly what the Data tab renders.

### 3.4 Coexistence with Assay (shared raw root)

- **No write contention by construction:** Assay writes *raw stock files*; QFinZero
  writes *derived stores* (UPQ parquet, ESP DBs). Disjoint targets.
- **Read-while-write safety:** `detect()` keys on completed files (mtime + a
  size-stable check), so a half-written raw file is not converted until stable.
- **Idempotency:** re-running over already-converted raw is a no-op (existing
  `qfz-data` `--force`-gated behaviour); cheap to run often.
- **Advisory lock:** `STORAGE_ROOT/_state/locks/<domain>.lock` so two QFinZero
  updates (cron + Data-tab button) don't both convert the same delta.

### 3.5 Data-admin backend API

Long-running conversions + live logs argue for a **thin FastAPI service**
(`infra/data-admin`, proposed **:19340**) rather than Next.js API routes. It wraps
`qfinzero/update/` and the registry:

| Endpoint | Purpose |
|---|---|
| `GET  /data/sources` | source registry + current freshness/lag/status |
| `GET  /data/status` | full manifest (last runs, rows, errors) — feeds the Data tab |
| `POST /data/update` | trigger `{sources[], market?, dry_run?}` → returns `job_id` |
| `GET  /data/jobs/{id}` | job state |
| `GET  /data/jobs/{id}/logs` | **SSE** stream of the running convert log |
| `POST /data/validate` | run `qfz-data validate`, return report |

Jobs run in a background task with a bounded queue (one job per domain lock). This
service is also what a future cron hits, so the manifest is the single source of truth
whether updates come from cron or the UI.

### 3.6 New ingestion glue (the only non-orchestration code)

Decouple the **load** half of the news/econ/earnings scrapers from their **download**
half so the orchestrator can call load-only:

- `qfinzero/update/loaders/news.py`   → load new raw news into MongoDB `ticker_news`.
- `qfinzero/update/loaders/econ.py`   → upsert NASDAQ econ raw into the SQLite DB.
- `qfinzero/update/loaders/earnings.py` (optional) → upsert Benzinga raw.

These reuse ESP's existing schemas/DB paths from `qfinzero/config.py`
(`MONGO_*`, `EARNINGS_DB`, `ECON_EVENTS_DB`). If the current scrapers can't be cleanly
split, v1 wraps `news_data.sh update` in `--detect-only`/load mode and records the
manifest around it.

---

## 4. QFinZero Console (frontend)

A new app — **QFinZero Console** — modeled on ChatGPT/Gemini, chat-first.

### 4.1 Stack & shell

- **Next.js (App Router)**, TypeScript, shadcn/ui, tanstack-query, SSE for chat + job
  logs. (Same stack as `dashboard-web`, so chat/PMB/status code ports over.) New app
  dir, proposed `infra/console`.
- **Top tab bar:** `Chat · Data · PMB · Settings · Doc · Assay ↗`. The `Assay` tab is
  an external link (configurable URL) opening Assay's own web in a new tab.
- Light/dark theme; the PMB tab keeps its modern/win98 toggle.

### 4.2 Chat (home)

- ChatGPT/Gemini-style streaming conversation, **purpose-built**: the agent is wired
  to QFinZero's tools via the **MCP server** (UPQ/ESP/PMB — quotes, news, options,
  broker). Tool calls render as cards (the playground already does this).
- **Load skill or MCP:** a picker to (a) attach MCP tool groups and (b) load a
  **skill** = a named prompt/workflow template (e.g. the MCP `trading_session`
  prompt). Selected skills/tools scope what the agent can do for that thread.
- Uses the **active provider + model** from Settings (§4.5). Backend = the existing
  playground/agent service (extended for multi-provider, §5).

### 4.3 Data

- The orchestration cockpit. **Source cards** (from `GET /data/sources`): domain,
  market, raw_max, store_max, **lag badge** (green/amber/red), last run.
- Actions: **Update** (per source / per domain / all), **Dry-run** (preview deltas),
  **Validate**. A running job streams its log live (SSE from `/data/jobs/{id}/logs`).
- Sub-views migrated from `dashboard-web`: News Browser, Calendar Browser, Sanity —
  as "browse" panels beside the "manage/update" panel.

### 4.4 PMB

- The broker terminal for viewing **agent trading by 10-digit account id**. v1 embeds
  the existing `:19380/ui` page (iframe) so it's available immediately; v2 ports it
  into the console shell for unified theming. Query box: paste an account id → status,
  positions, day-by-day trading history, freeze/next-day state.

### 4.5 Settings — multi-provider LLM config

Generalises today's single OpenAI-compatible config into a provider model:

```
Provider = { id, label, base_url, api_key, models[], enabled, kind: "builtin"|"custom" }
```

- **Builtins with default endpoints** (user-overridable):
  - GPT/OpenAI → `https://api.openai.com/v1`
  - DeepSeek → `https://api.deepseek.com` (OpenAI-compatible)
  - Gemini → `https://generativelanguage.googleapis.com/v1beta/openai` (OpenAI-compat shim) or native
  - Claude → `https://api.anthropic.com` (native; see §5)
- **Custom providers:** "Add provider" with an arbitrary base URL + key for **local
  vLLM** or any OpenAI-compatible server (e.g. `http://localhost:8000/v1`).
- A global **active provider + model** selector drives Chat. Per-provider
  **Test connection** (generalise the existing `/api/playground/test-connection`).
- Storage: localStorage by default (keys never leave the browser), with an optional
  server-side encrypted store later. Keys are write-only in the UI (masked).

### 4.6 Doc

- Renders the repo's markdown docs (`docs/`, service READMEs, agent-guides, OpenAPI)
  in-app. `streamdown` (already a dep) renders MD; a small index lists doc sources.

### 4.7 Assay ↗

- Configurable external URL (env `ASSAY_WEB_URL`) → opens Assay's web in a new tab.

---

## 5. Provider abstraction (chat backend)

Today the chat backend assumes an OpenAI-compatible endpoint. To support **Claude +
Gemini natively** alongside **OpenAI/DeepSeek/vLLM**, add a thin server-side adapter
in the agent service:

- **Path of least resistance (v1):** use OpenAI-compatible endpoints everywhere —
  DeepSeek and vLLM already are; Gemini exposes `/v1beta/openai`; Claude via an
  OpenAI-compat proxy. One code path, fastest to ship.
- **Native adapter (v2):** a `Provider` interface (`stream(messages, tools)`) with
  `openai` / `anthropic` / `gemini` implementations, because tool-calling and
  streaming differ per vendor and skills/MCP need consistent tool semantics.

Recommend shipping v1 (OpenAI-compat) to unblock the console, then the native adapter.
This is the one sub-design that needs its own follow-up.

---

## 6. Ports & services

| Service | Port | Role |
|---|---|---|
| QFinZero Console (new) | **19300** (replaces dashboard-web) or 19310 during migration | the web |
| data-admin (new) | **19340** (proposed) | update orchestration API + SSE job logs |
| Playground/agent | 19390 | chat engine (extended for multi-provider) |
| UPQ / ESP / PMB | 19350 / 19330 / 19380 | unchanged |
| MCP server | stdio + streamable-HTTP | tools/skills for Chat |

---

## 7. Phasing

1. **Orchestration core** — `qfinzero/update/` source registry + manifest + `qfz-data
   update` (prices first: detect-delta → existing converters → validate → manifest).
   Coexistence lock. *Pure backend, testable via CLI.*
2. **News/econ/earnings load-only loaders** (§3.6) folded into the registry.
3. **data-admin API** (:19340) — status/sources/update/jobs/SSE/validate over the core.
4. **Console scaffold** — Next.js app + tab shell; **Chat** ported from playground.
5. **Data tab** on data-admin (cards, update buttons, live logs) + migrated browse views.
6. **Settings** multi-provider; **PMB** tab (iframe); **Doc** tab; **Assay** link.
7. **Provider native adapter** (Claude/Gemini).
8. **Cutover** from `dashboard-web`; docs + tests; optional cron → data-admin.

Phases 1–3 deliver the stated priority ("design qfinzero's update well") as working
software; 4–8 build the console around it.

---

## 8. Testing & validation

- **Orchestration:** unit-test `detect()` delta logic (mtime/size-stable, range math),
  manifest read/write, lag/freshness colouring, lock behaviour; integration test a
  dry-run over the real raw roots (no writes) asserting planned steps.
- **data-admin:** TestClient over status/update/jobs (job lifecycle, SSE smoke).
- **Console:** component tests for source cards / settings provider CRUD (vitest, as
  in dashboard-web); e2e happy path Chat→tool-call.
- **Coexistence:** simulate a concurrent Assay raw-stock write during a price update;
  assert no corruption and correct skip/convert.

---

## 9. Decisions

**Resolved (2026-06-29):** brand = **QFinZero Console**; data-admin = **separate
FastAPI :19340**; providers = **OpenAI-compatible first**; first slice = **orchestration
core (CLI)**. Folded into §1.

**Still open (don't block the first slice):**
1. **`Assay ↗` tab target URL** (env `ASSAY_WEB_URL`).
2. **News/econ/earnings load decoupling** — can the existing scrapers expose a
   load-only path, or should v1 wrap `news_data.sh` and record the manifest around it?
3. **dashboard-web** — migrate-then-retire, or keep running alongside during build?
4. **Does the Data tab ever trigger Assay's stock update**, or strictly QFinZero-owned
   sources (Assay runs its own)? (Assumed: QFZ-owned only.)

---

## 10. Implementation status

**Phase 1 (orchestration core) — done (2026-06-29).** Pure backend, convert-only.

- `qfinzero/update/` package: `sources.py` (10-source registry; 7 price sources wired
  to the existing `Converter`, news/econ/earnings declared `available=False`),
  `freshness.py` (raw-vs-store date math, business-day lag, green/amber/red),
  `manifest.py` (`STORAGE_ROOT/_state/update_manifest.json`), `lock.py` (per-domain
  `flock`), `orchestrator.py` (plan → detect → convert → record; corp-actions
  dependency rule; injectable scan/converter for testing).
- CLI: `qfz-data update [--source all|prices|news|econ|earnings|<id>[,…]]
  [--market us|cn] [--since DATE] [--dry-run] [--force] [--status] [--json]`.
- Tests: `tests/test_update_orchestration.py` — 18 passing (freshness, selection,
  planning, run/skip/force/error, dry-run no-writes, exclusive lock), all with
  injected fakes (no DuckDB/data). Live read-only `--status`/`--dry-run` verified
  against the real `/data/massive_data` + `/data/tushare_data` registry.

**Phase 3 (data-admin service + Data tab) — done (2026-07-01).** The operator
control plane over the Phase-1 core, plus the "Integrated Data Protocol" surface.

*Scope amendment (2026-07-01):* the operator chose **"own it end to end"** —
data-admin also stores vendor credentials, runs the MASSIVE permission scan, and
triggers the download scripts — so acquisition is no longer strictly external. The
convert-only orchestrator is unchanged; acquisition is a thin, dry-run-default
bridge to the existing shell scripts (they still own their write targets).

- `qfinzero/admin/` package:
  - `config_store.py` — masked-secret vendor creds + dirs + schedule at
    `$QFZ_DATA_ROOT/_state/qfz.config.json` (0600), applied to `os.environ`
    (`POLYGON_S3_*`, `TUSHARE_TOKEN`, `RAW_*`, `STORAGE_ROOT`, `MONGO_*`).
  - `scan.py` — MASSIVE S3 dataset/permission listing (boto3 → `aws` CLI fallback),
    REST-key validate, Tushare token validate; never raises (red state, not 500).
  - `acquire.py` — `run_stream` + a target registry that shells `upq_flatfiles.sh` /
    `news_data.sh` (dry-run by default; advertises where each writes).
  - `scheduler.py` — a managed crontab block rendered from the schedule config
    (`apply`/`clear`/`status`, dry-run preview, `croniter` next-run when present).
  - `explore.py` — UPQ store + ESP coverage summaries and per-symbol scans (DuckDB).
  - `setup.py` — first-run setup-state driving the wizard vs. status view.
- CLI: `qfz-data config|scan|acquire|schedule|explore|setup-state` (all `--json`).
- Service: **`infra/data-admin` FastAPI on :19340** — config/setup/scan, sources
  (freshness), update+acquire **jobs with SSE log streaming**, schedule, explorer.
  Wired into `run_all.sh` (`data-admin`) and `qfinzero/config.py`
  (`DATA_ADMIN_PORT=19340`). Verified live (health, jobs, SSE).
- Web (chosen: **extend `dashboard-web/data`**, not a new console app): a setup
  wizard + RAW→Application-layer map (QFinZero + `Assay ↗`), a credentials/scan
  panel, a pipeline manager (status · update · dry-run · download · live logs), a
  schedule panel, and a data explorer. Proxied via `/api/data-admin/[...path]`
  (SSE passthrough). `tsc --noEmit` clean.
- Tests: `tests/test_data_admin.py` — 14 passing (secret masking/preserve, 0600,
  env apply, injected S3 scan + no-cred paths, scheduler render/strip/plan, acquire
  run_stream/guards, setup-state shape).

**Next:** Phase 2 (news/econ/earnings load-only loaders, §3.6) to flip those sources
from `available=False` to wired; then Phase 4+ (chat-first console) if pursued.
```
