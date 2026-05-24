# QFinZero Tool Calling Evaluation — Reproducible Protocol

## Overview

This evaluation measures how accurately LLMs select and call QFinZero APIs
given natural language instructions. It tests tool selection, endpoint routing,
parameter correctness, time alignment, and multi-step chaining.

We do NOT evaluate trading profitability. This is purely a tool-calling
accuracy benchmark.

## Prerequisites

- Python 3.10+
- `pip install httpx pyyaml`
- Access to model endpoints (API keys or local vLLM servers)
- (Optional, for live mode) Running QFinZero services (UPQ, ESP, PMB)

## Step-by-step Protocol

### 1. Prepare model config

Edit `models.yaml` to list every model endpoint you want to evaluate.
Each entry needs: `model_name`, `base_url`, `api_key`, `provider_type`.

### 2. Run in dry-run mode (recommended first)

```bash
cd eval/
python runner.py \
    --benchmark benchmark.jsonl \
    --model-config models.yaml \
    --mode dry-run \
    --max-workers 4 \
    --seed 42
```

This calls each model, parses its JSON output, and scores against the gold
standard — without making any QFinZero API calls.

### 3. Run in live mode (optional)

Start QFinZero services first, then:

```bash
python runner.py \
    --benchmark benchmark.jsonl \
    --model-config models.yaml \
    --qfinzero-base-url http://127.0.0.1 \
    --mode live \
    --max-workers 2 \
    --seed 42
```

Live mode additionally executes the model's predicted tool calls against the
real services and logs the HTTP responses. Scores are still computed from gold
comparison (live responses are logged for qualitative analysis only).

### 4. Review outputs

Results land in `./eval_outputs/<run_id>/`:

```
eval_outputs/
  20250118_143022/
    meta.json                  # run metadata
    summary.csv                # aggregated scores across models
    summary.md                 # markdown tables (paper-ready)
    errors.log                 # categorized error log
    gpt-4o_results.csv         # per-case scores for this model
    gpt-4o_raw.jsonl           # raw model outputs + scores
    qwen2.5-72b_results.csv
    qwen2.5-72b_raw.jsonl
    ...
```

### 5. Fill in paper tables

Copy numbers from `summary.md` into `tables.md` for your paper.

## Extending the benchmark

### Adding new test cases

Append lines to `benchmark.jsonl`. Each line is a JSON object with:

```json
{
    "id": "unique-id",
    "category": "price_query|news_query|calendar_query|broker_query|multi_tool_chain",
    "difficulty": "easy|medium|hard",
    "natural_language_instruction": "user query text",
    "expected_tool_calls": [ ... ],
    "grading_notes": "explanation"
}
```

### Design guidelines for new cases

- **Easy**: Single tool, explicit parameters, no ambiguity.
- **Medium**: Single tool but requires inference (trading hours, date math),
  or multiple explicit parameters with type conversion.
- **Hard**: Multi-tool chains, dependency resolution, negative tests,
  ambiguous time references, or option contract formatting.

### Generating the full 80-case set

The provided benchmark.jsonl contains 45 cases. To reach 80:

1. Add more multi-ticker price queries with different field selections.
2. Add timezone-edge cases (e.g., "3 PM London time" requires UTC conversion).
3. Add more option-related cases: OPRA format parsing, mixed stock+option orders.
4. Add more multi-tool chains: "check news -> get price -> decide order".
5. Add more negative tests: unsupported order types, missing session IDs,
   wrong asset classes.
6. Add ambiguous queries where multiple tools could work (test default policy).

## Scoring reference

| Metric | Weight | What it measures |
|--------|--------|------------------|
| TSA    | 0.20   | Correct tool family + action name |
| EC     | 0.15   | Correct HTTP endpoint path |
| PA     | 0.20   | Required parameters present and correct |
| TAS    | 0.15   | Time boundaries within tolerance |
| COS    | 0.10   | Multi-step dependency order preserved |
| JV     | 0.05   | Output is parseable JSON conforming to schema |
| OCP    | 0.10   | No redundant tool calls (penalty for extras) |
| FOC    | 0.05   | Final answer has summary + assumptions |

**Overall = weighted sum * 100**, range [0, 100].

## Tolerance rules

| Context | Tolerance |
|---------|-----------|
| Intraday datetime (minute bars) | ±5 minutes |
| Daily date boundaries | ±1 calendar day |
| "Past N trading days" conversions | ±2 calendar days |
| horizon_minutes for ESP queries | ±30 minutes |
| Exact dates explicitly stated | exact match |
| Numeric param values | relative tolerance 0.01% |
| String params | case-insensitive match |
