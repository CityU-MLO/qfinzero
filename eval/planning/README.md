# QFinZero Multi-Step Planning Eval

This folder contains the **planning** evaluation — 20 multi-step "episode" benchmarks
that require the agent to chain calls across UPQ (prices), ESP (news/calendar), and
PMB (paper trading broker).

```
eval/
  calling/        ← original single-call tool-routing eval (unchanged)
  planning/       ← THIS folder — multi-step planning eval
    benchmarks/
      qfinzero_multistep_10.jsonl    10 episodes (ms-001–ms-010)
      qfinzero_multistep_10b.jsonl   10 episodes (ms-011–ms-020, local-data focus)
    runner/
      run_multistep.py              Runner (pre-creates PMB account/session)
    eval/
      eval_multistep.py             Evaluator (8 metrics + aggregate)
    config.yaml                     DB connections, service URLs, PMB seed
    models.yaml                     Model endpoint config
    README.md                       This file
```

Outputs land under `../../runs/<model_name>/<timestamp>/`:
```
runs/
  deepseek-chat/
    20250206_120000/
      multistep_results.jsonl   Raw model outputs + step logs
      run_context.json          session_id + account_id used in this run
      eval/
        deepseek-chat/
          summary.json          Aggregate metrics
          table.csv             Per-episode scores
```

---

## Prerequisites

```bash
pip install httpx pyyaml
```

Optionally, to run in **live mode** you need the QFinZero services running:
```bash
# In separate terminals:
python infra/upq/main.py      # UPQ on port 19703
python infra/esp/main.py      # ESP on port 19702
python infra/pmb/main.py      # PMB on port 19701
```

---

## How it works

### Key design choice: pre-created account + session

In **live mode** the runner:
1. Calls `POST /v1/accounts` on PMB → gets `account_id`
2. Calls `POST /v1/sessions` on PMB → gets `session_id`
3. Injects both into every episode's instruction as `{session_id}` / `{account_id}`
4. The model **must not** call `create_account` or `create_session` — those are
   already done. Any such call in the model output is scored as a redundant error.

In **dry-run mode** stable placeholder IDs are used instead.

### Model output format (STRICT)

The model must return exactly one JSON object — no markdown, no extra text:

```json
{
  "plan": ["Step 1: find earnings date", "Step 2: fetch prices", ...],
  "tool_calls": [
    {"step_id": "s1", "tool": "ESP.calendar.earnings", "args": {"start_date": "2025-01-01", "end_date": "2025-03-31", "tickers": ["AAPL"]}},
    {"step_id": "s2", "tool": "UPQ.stock.daily",        "args": {"tickers": "AAPL", "start": "2025-01-22", "end": "2025-01-30"}},
    {"step_id": "s3", "tool": "PMB.order.place",        "args": {"session_id": "sess-xxx", "account_id": "acct-yyy", "order": {...}}}
  ],
  "final_answer": "AAPL reports Jan 30. Prices show uptrend. Placed put order at $4.50."
}
```

---

## Step 1 — Configure models

Edit `models.yaml`:

```yaml
models:
  - model_name: gpt-4o
    base_url: https://api.openai.com/v1
    api_key: sk-...
    provider_type: openai_compatible
```

---

## Step 2 — Run in dry-run mode (no live services needed)

```bash
cd eval/planning/runner/

python run_multistep.py \
    --benchmark ../benchmarks/qfinzero_multistep_10.jsonl \
    --model-config ../models.yaml \
    --config ../config.yaml \
    --mode dry-run
```

Results: `../../../runs/<model_name>/<timestamp>/multistep_results.jsonl`

---

## Step 3 — Evaluate results

```bash
cd eval/planning/eval/

python eval_multistep.py \
    --results ../../../runs/<model_name>/<timestamp>/multistep_results.jsonl \
    --benchmark ../benchmarks/qfinzero_multistep_10.jsonl \
    --output-dir ./<model_name>/
```

Outputs:
- `./<model_name>/summary.json`  — aggregate metrics
- `./<model_name>/table.csv`     — per-episode scores

---

## Step 4 — Run in live mode (optional, requires all services up)

```bash
python run_multistep.py \
    --benchmark ../benchmarks/qfinzero_multistep_10.jsonl \
    --model-config ../models.yaml \
    --config ../config.yaml \
    --mode live
```

In live mode:
- PMB account + session pre-created automatically
- Each tool call executed sequentially; results logged per step
- Step logs written to `multistep_results.jsonl` (SS/ER metrics become meaningful)

---

## Metrics reference

| Metric | Weight | Description |
|--------|--------|-------------|
| TM  | 0.20 | Tool Match — correct tool name + endpoint + method per expected step |
| PA  | 0.20 | Param Accuracy — required params present and correct (with tolerance) |
| DC  | 0.15 | Dependency Consistency — correct call order; session/account IDs present |
| SS  | 0.10 | Step Success — fraction of executed steps that returned HTTP 2xx (live only) |
| ER  | 0.10 | Execution Reliability — PMB state matches expected_final_state (live only) |
| RS  | 0.10 | Recovery Score — for recovery episodes (ms-005, ms-009): agent fixes bad attempt |
| TA  | 0.10 | Time Alignment — date/time fields within tolerance |
| EF  | 0.05 | Efficiency — penalty -0.15 per extra step beyond expected |

**Overall = Σ(weight × metric) × 100**, range [0, 100].

**Episode Success Rate (ESR)**: fraction of episodes with overall ≥ 70.

### Tolerance rules

| Context | Tolerance |
|---------|-----------|
| Intraday datetime (minute bars) | ±5 minutes |
| Daily date boundaries | ±1 calendar day |
| "N trading days" conversions | ±2 calendar days |
| ESP horizon_minutes | ±60 minutes |
| Exact dates (explicitly stated) | exact match |
| Numeric param values | relative ±0.01% |
| String params | case-insensitive |

---

## Episode overview

| ID | Title | Difficulty | Pipelines | Recovery? |
|----|-------|------------|-----------|-----------|
| ms-001 | Earnings-Aware Put Protection (AAPL) | medium | ESP + UPQ + PMB | — |
| ms-002 | NVDA Momentum Scan + Limit Entry | hard | ESP + UPQ price + UPQ rates + PMB | — |
| ms-003 | Live Portfolio Price Refresh | medium | PMB × 2 + UPQ + ESP | — |
| ms-004 | Covered Call Writing on AAPL | hard | UPQ price + UPQ options + PMB × 2 | — |
| ms-005 | TSLA Weekend Date Recovery | hard | UPQ + ESP + PMB | ✓ |
| ms-006 | MSFT Earnings Straddle Setup | hard | ESP + UPQ + PMB × 2 | — |
| ms-007 | Cancel-Replace NVDA Limit Order | hard | PMB × 3 + UPQ | — |
| ms-008 | Rate-Sensitive Macro Context | medium | UPQ rates + UPQ daily + ESP + PMB | — |
| ms-009 | FOMC Event via Econ Calendar | hard | ESP × 3 + UPQ + PMB | ✓ |
| ms-010 | Session Tick + Near-Expiry Options | hard | PMB × 3 + UPQ options + UPQ daily | — |

### qfinzero_multistep_10b.jsonl — Local-data focus (ms-011–ms-020)

New endpoints introduced: `UPQ.option.ticker_query`, `ESP.timeline`, `ESP.triggers.next`,
`ESP.events.stream`, `ESP.news.body`, `PMB.account.trades`, `PMB.order.modify`,
`PMB.session.export`. New tickers: `JPM`, `BAC`, `GS`.

| ID | Title | Difficulty | New Endpoints | Recovery? |
|----|-------|------------|---------------|-----------|
| ms-011 | JPM Q4 Earnings — News Body Read + Buy | medium | ESP.news.body | — |
| ms-012 | GS Near-Expiry Option Ticker Query | hard | UPQ.option.ticker_query | — |
| ms-013 | TSLA News Timeline + Protective Put | hard | ESP.timeline | — |
| ms-014 | MSFT Order Modify Workflow | hard | PMB.order.modify | — |
| ms-015 | Banking Sector Earnings Sweep (JPM/BAC/GS) | hard | — | — |
| ms-016 | CPI Release Day — Post-CPI MSFT Hedge | hard | — | — |
| ms-017 | AAPL Trades Audit + Trigger Alert | hard | PMB.account.trades, ESP.triggers.next | — |
| ms-018 | BAC Intraday Market Order + Fill Verify | medium | PMB order MARKET type | — |
| ms-019 | Session Export + NVDA Put Protection | hard | PMB.session.export | — |
| ms-020 | Events Stream Recovery + News Article | hard | ESP.events.stream | ✓ |
