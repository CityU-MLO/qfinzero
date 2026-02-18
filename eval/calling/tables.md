# QFinZero Tool Calling Evaluation — Paper-Ready Table Templates

> Fill these tables with actual evaluation results. All scores are percentages [0-100].
> TSA=Tool Selection Accuracy, EC=Endpoint Correctness, PA=Parameter Accuracy,
> TAS=Time Alignment Score, COS=Call Order Score, JV=JSON Validity,
> OCP=Over-Calling Penalty (100=no penalty), FOC=Final Output Completeness.

---

## Table 1: Tool Calling Accuracy — Overall

| Model | TSA | EC | PA | TAS | COS | JV | OCP | FOC | **Overall** |
|:------|----:|---:|---:|----:|----:|---:|----:|----:|------------:|
| GPT-4o | — | — | — | — | — | — | — | — | **—** |
| Claude Sonnet 4.5 | — | — | — | — | — | — | — | — | **—** |
| Qwen2.5-72B | — | — | — | — | — | — | — | — | **—** |
| Llama3.1-70B | — | — | — | — | — | — | — | — | **—** |

*N = 45 benchmark cases per model. Temperature = 0. Single-pass evaluation.*

---

## Table 2: Accuracy by Category

| Model | Price Query | News Query | Calendar | Broker | Multi-Tool |
|:------|:------------|:-----------|:---------|:-------|:-----------|
| GPT-4o | —/—/— | —/—/— | —/—/— | —/—/— | —/—/— |
| Claude Sonnet 4.5 | —/—/— | —/—/— | —/—/— | —/—/— | —/—/— |
| Qwen2.5-72B | —/—/— | —/—/— | —/—/— | —/—/— | —/—/— |
| Llama3.1-70B | —/—/— | —/—/— | —/—/— | —/—/— | —/—/— |

*Format: TSA / PA / Overall per category.*

---

## Table 3: Accuracy by Difficulty

| Model | Easy | Medium | Hard |
|:------|-----:|-------:|-----:|
| GPT-4o | — | — | — |
| Claude Sonnet 4.5 | — | — | — |
| Qwen2.5-72B | — | — | — |
| Llama3.1-70B | — | — | — |

*Values are Overall score (0-100).*

---

## Table 4: Failure Mode Distribution (counts across all cases)

| Failure Mode | GPT-4o | Claude Sonnet 4.5 | Qwen2.5-72B | Llama3.1-70B |
|:-------------|-------:|-------------------:|------------:|-------------:|
| wrong_tool_family | — | — | — | — |
| wrong_tool_action | — | — | — | — |
| wrong_endpoint | — | — | — | — |
| hallucinated_endpoint | — | — | — | — |
| missing_required_param | — | — | — | — |
| wrong_param_value | — | — | — | — |
| wrong_time_value | — | — | — | — |
| wrong_time_format | — | — | — | — |
| wrong_call_order | — | — | — | — |
| redundant_call | — | — | — | — |
| missing_call | — | — | — | — |
| invalid_json | — | — | — | — |
| schema_violation | — | — | — | — |
| false_refusal | — | — | — | — |
| missed_refusal | — | — | — | — |

---

## Table 5: Latency (seconds per call)

| Model | Mean | P50 | P95 | Max |
|:------|-----:|----:|----:|----:|
| GPT-4o | — | — | — | — |
| Claude Sonnet 4.5 | — | — | — | — |
| Qwen2.5-72B | — | — | — | — |
| Llama3.1-70B | — | — | — | — |

---

## Table 6: Negative Test (Refusal) Accuracy

| Model | Correct Refusals | False Refusals | Missed Refusals | Total Negative Cases |
|:------|-----------------:|---------------:|----------------:|---------------------:|
| GPT-4o | — | — | — | 5 |
| Claude Sonnet 4.5 | — | — | — | 5 |
| Qwen2.5-72B | — | — | — | 5 |
| Llama3.1-70B | — | — | — | 5 |

---

## Notes

- **Scoring formula**: `Overall = 0.20*TSA + 0.15*EC + 0.20*PA + 0.15*TAS + 0.10*COS + 0.05*JV + 0.10*OCP + 0.05*FOC`, scaled to [0,100].
- **Tolerance rules**: Intraday times ±5 min, daily dates ±1 day, trading-day conversions ±2 days, horizon_minutes ±30 min.
- **Evaluation mode**: dry-run (gold comparison only, no live API calls).
- **Temperature**: 0.0 for all models. Single pass (no majority voting).
- **Benchmark version**: v1.0, 45 cases (11 price, 8 news, 4 calendar, 14 broker, 8 multi-tool).
