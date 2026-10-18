# Agent benchmark

> 中文: [docs/cn/bench.md](../cn/bench.md)

`qfz-bench` measures how well a tool-calling model works with QFinZero: finding
data, computing from it, respecting the time lock and placing orders. It runs
against a hub serving the [sample dataset](sample-data.md), so every answer is
known exactly and no answer can come from the model's memory.

```bash
qfz-bench oracle --hub http://127.0.0.1:19777 --api-key qfz_…      # platform check, expect 100%
qfz-bench run --hub http://127.0.0.1:19777 --api-key qfz_… \
    --model gpt-4.1 --base-url https://api.openai.com/v1 --llm-key sk-… \
    --out runs/gpt-4.1.jsonl
qfz-bench score runs/gpt-4.1.jsonl
```

## Tasks

Version 1.0 has 104 tasks, shipped in `qfinzero/bench/data/tasks-v1.0.jsonl`.

| category | n | what it tests |
|---|---:|---|
| `daily` | 25 | closes, volumes, split-adjusted returns, the date of a monthly high |
| `intraday` | 21 | a given minute's close, regular-hours VWAP, pre-market volume, overnight highs |
| `quotes` | 5 | the stock bid-ask spread at a given minute |
| `options` | 13 | an option's mid price at a minute, the most active contract, contracts traded per expiry |
| `events` | 21 | EPS surprise, beat or miss, macro actuals, the price reaction to earnings, news counts |
| `corporate` | 4 | dividend amounts, a split's ex-date found from prices |
| `time_lock` | 11 | questions asked at a past moment, including results that are not yet released |
| `trading` | 4 | episodes in a PMB session, scored on what the broker recorded |

Difficulty runs from 1 (one lookup) to 3 (several calls and a computation).
Examples:

- *What was the closing price of QUIL on 2025-02-27? (as traded, not adjusted)* → 17.06
- *How much did PIKE move, in percent, from the last close before its earnings
  report of 2025-02-21 to the first close after it?* → 7.39
- At 15:00 ET on 2025-03-24: *What EPS did ACME report in its earnings release
  of 2025-03-24? If it is not known yet, answer null.* → null
- *BOLT reports earnings at 7:00 a.m. ET on 2025-03-27. Buy 100 shares of BOLT
  now, then make sure you hold no BOLT shares when the report comes out.*

## Task format

One JSON object per line:

| field | meaning |
|---|---|
| `id`, `category`, `difficulty` | identification |
| `question` | the text given to the model |
| `kind` | `number`, `integer`, `text`, `date`, `bool`, `none` (the right answer is "not known yet"), `episode` |
| `answer`, `tolerance` | the reference answer; numbers may differ by at most `tolerance` |
| `as_of` | ISO UTC time the question is asked at, or null |
| `op`, `args` | how the reference answer is computed (see below) |
| `episode` | for trading tasks: session settings, the oracle's script and the checks |

## How a model is run

`qfz-bench run` talks to any OpenAI-compatible chat-completions API (OpenAI,
vLLM, SGLang, LiteLLM, OpenRouter, …) and to the hub's MCP endpoint, the same
interface external agents use.

1. For a task with `as_of`, the runner creates a PMB session whose clock maps to
   that time (a minute session one bar before it, or a daily session for
   16:00 ET) and sends its id as the `X-QFZ-Session` header. The time lock is
   then enforced by the server; the prompt also states the time.
2. The model may call any offered tool (`--tools`, default `upq_,esp_,pmb_,research_`)
   for up to `--max-turns` turns (default 30). Tool output is cut at 12,000 characters.
3. The model must end with a line `ANSWER: <json>`: a number, a quoted string,
   `true`/`false` or `null`.

For a trading episode the runner creates the account and session, gives their
ids in the prompt and binds the session header. After the model stops, the
checks run against the session's fills and the account's positions:

| check | passes when |
|---|---|
| `position` | the account holds exactly `qty` of the symbol |
| `filled` | fills on that side add up to `qty`, optionally inside a time window |
| `flat_by` | the net position from fills before a time is zero |

## Scoring

- `number`: the absolute difference is at most `tolerance` (prices 0.005,
  percentages 0.02 points; units and `%` signs are ignored).
- `integer`: rounds to the reference.
- `text`: equal after removing spaces and case; option symbols match with or without `O:`.
- `date`: the first `YYYY-MM-DD` in the answer equals the reference.
- `bool`: `true`/`false` or yes/no.
- `none`: `null`, or a phrase such as "not yet released".
- `episode`: every check passes.

A task with no `ANSWER:` line, a tool error that ends the run, or a time-out
scores zero. `score` prints accuracy per category and overall, with the mean
number of tool calls; `--out` also writes `<name>.summary.json` with token counts.

## The oracle

Every question type (`op`) has two implementations in `qfinzero/bench/ops.py`:
`gold`, which computes the answer from the sample files with SQL, and `solve`,
which answers through the public UPQ, ESP and PMB APIs. `qfz-bench oracle`
runs `solve` for every task and the trading scripts for every episode. A
100% score shows that each question can be answered through the platform and
that the services return what the files hold. `tests/test_e2e.py` runs this
against a freshly started stack in CI.

## Reproducibility and reporting

The task file is regenerated from the sample by `qfz-bench build --data <root>
--out <file>`; `tests/test_bench.py` fails if the shipped file differs from a
fresh build. When you publish results, report the benchmark version (1.0), the
model and its version, temperature, `--max-turns`, the tool prefixes offered,
and whether the time lock header was used (it always is with `qfz-bench run`).

## Adding tasks

1. Add an op to `qfinzero/bench/ops.py` with `gold(store, args)` and `solve(api, args, as_of)`.
2. Generate instances in `qfinzero/bench/tasks.py` (use the builder's seeded
   random generator, never `random`).
3. Rebuild the task file and run the oracle; it must stay at 100%.
4. Bump `BENCH_VERSION` when existing tasks change.
