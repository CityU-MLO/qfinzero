#!/usr/bin/env python3
"""
QFinZero Multi-Step Planning Evaluation Runner
================================================

Usage:
    python run_multistep.py \\
        --benchmark ../benchmarks/qfinzero_multistep_10.jsonl \\
        --model-config ../models.yaml \\
        --config ../config.yaml \\
        --mode dry-run

Modes:
    dry-run : Parse model output and score against gold. No tool execution.
    live    : Pre-create PMB account+session, execute tool calls, log responses.

Output saved to: ../../runs/<model_name>/multistep_results.jsonl

IMPORTANT:
    In live mode the runner pre-creates ONE account and ONE session via PMB
    BEFORE any episode is sent to the model. The session_id and account_id
    are then injected into every episode instruction as {session_id} /
    {account_id} placeholders. The agent MUST NOT call create_account or
    create_session.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

# ---------------------------------------------------------------------------
# Import evaluator for inline scoring
# ---------------------------------------------------------------------------
_EVAL_DIR = Path(__file__).parent.parent / "eval"
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

try:
    from eval_multistep import score_episode, aggregate, METRIC_NAMES  # type: ignore
    _SCORING_AVAILABLE = True
except ImportError as _e:
    _SCORING_AVAILABLE = False
    print(f"[warning] Inline scoring unavailable: {_e}")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("multistep_runner")

# ---------------------------------------------------------------------------
# Model output schema (STRICT)
# The model must output exactly:
# {
#   "plan": ["step description", ...],
#   "tool_calls": [
#       {"step_id": "s1", "tool": "NPP.calendar.earnings", "args": {...}},
#       ...
#   ],
#   "final_answer": "short text report"
# }
# ---------------------------------------------------------------------------
PLANNING_SYSTEM_PROMPT = """\
You are a financial planning agent for QFinZero. You receive a multi-step task \
and must produce a complete tool-calling plan plus a short final report.

RULES:
1. Output ONLY valid JSON — no markdown, no code fences, no extra text.
2. Use EXACTLY this schema (no extra fields):
{
  "plan": ["Step 1: ...", "Step 2: ...", ...],
  "tool_calls": [
    {"step_id": "s1", "tool": "<tool_name>", "args": {<params>}},
    ...
  ],
  "final_answer": "<short text report>"
}
3. List tool_calls in dependency order (calls depending on prior results come later).
4. "tool" must be one of the registered tool names below (e.g. "NPP.calendar.earnings").
5. For PMB endpoints that include {session_id} or {account_id} in the URL path,
   use the actual IDs provided in the instruction.
6. Do NOT call create_account or create_session — session and account are pre-created.
7. Date format: YYYY-MM-DD. Datetime: YYYY-MM-DDTHH:MM:SS. UTC: append Z.
8. For UPQ GET calls put parameters in "args" as query params.
   For NPP/PMB POST calls put parameters in "args" as request body.

AVAILABLE TOOLS:
=== UPQ (Unified Price Query) — base: http://127.0.0.1:23333 ===
UPQ.stock.minute     GET /stock              args: tickers(str,csv), start(datetime), end(datetime), fields(opt)
UPQ.stock.daily      GET /stock/daily        args: tickers(str,csv), start(date), end(date), fields(opt)
UPQ.option.chain_query  GET /option/chain_query  args: underlying(str), date(date), type(C|P,opt), strike_min/max(float,opt), expiry_min/max(date,opt)
UPQ.option.ticker_query GET /option/ticker_query args: contract(OPRA str), start, end, resolution(day|minute,opt)
UPQ.rates.query      GET /rates/query        args: start(date), end(date), tenors(csv: 1M,3M,1Y,2Y,5Y,10Y,30Y, opt=all)

=== NPP (News Pushing Pipeline) — base: http://127.0.0.1:19330 ===
NPP.events.query     POST /npp/events/query  args: mode(upcoming|just_happened|window), event_types(list), tickers(list,opt), horizon_minutes(int,opt), start_utc/end_utc(opt), min_importance(opt), limit(opt)
NPP.events.get       GET  /npp/events/{event_id}   (no args; event_id in URL)
NPP.events.stream    POST /npp/events/stream args: cursor(str), event_types(list,opt), tickers(list,opt)
NPP.triggers.next    POST /npp/triggers/next args: tickers(list,opt), min_importance(str), horizon_minutes(int)
NPP.timeline         POST /npp/timeline      args: tickers(list,opt), start_utc, end_utc, bucket_minutes(int)
NPP.calendar.econ    POST /npp/calendar/econ args: start_date(date), end_date(date), min_importance(str)
NPP.calendar.earnings POST /npp/calendar/earnings args: start_date(date), end_date(date), tickers(list,opt)
NPP.news.body        GET  /npp/news/{news_id}/body  (no args; news_id in URL)

=== PMB (Paper Money Broker) — base: http://127.0.0.1:19320 ===
PMB.account.positions GET /v1/accounts/{account_id}/positions   (no body args)
PMB.account.orders    GET /v1/accounts/{account_id}/orders      args: status_in(csv,opt), session_id(opt), limit(opt)
PMB.account.trades    GET /v1/accounts/{account_id}/trades      args: session_id(opt)
PMB.session.step      POST /v1/sessions/{session_id}/step       args: step(int)
PMB.session.stop      POST /v1/sessions/{session_id}/stop       (no args)
PMB.session.market    GET  /v1/sessions/{session_id}/market     (no args)
PMB.session.summary   GET  /v1/sessions/{session_id}/summary    (no args)
PMB.session.export    GET  /v1/sessions/{session_id}/export     args: format(json|csv,opt)
PMB.order.place       POST /v1/orders  args: session_id, account_id, order:{instrument:{type,symbol|contract},side(BUY|SELL),order_type(MARKET|LIMIT|STOP|STOP_LIMIT),qty(int),limit_price(float,opt),stop_price(float,opt),time_in_force(DAY|GTC|GTD)}
PMB.order.cancel      POST /v1/orders/{order_id}/cancel  args: session_id, account_id
PMB.order.modify      POST /v1/orders/{order_id}/modify  args: session_id, account_id, updates:{limit_price,qty,...}
"""


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def load_config(path: str) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def load_models(path: str, global_call_latency_s: float = 0.0) -> list[dict[str, Any]]:
    with open(path) as f:
        data = yaml.safe_load(f)
    models = data.get("models", [])
    if not models:
        raise ValueError(f"No models in {path}")
    for m in models:
        m.setdefault("api_key", None)
        m.setdefault("provider_type", "openai_compatible")
        # Per-model YAML setting takes precedence; CLI global default fills the rest
        m.setdefault("call_latency_s", global_call_latency_s)
    return models


def load_benchmark(path: str) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.warning(f"Skipping line {i}: {e}")
    log.info(f"Loaded {len(cases)} benchmark cases")
    return cases


# ---------------------------------------------------------------------------
# PMB pre-setup  (create account + session before any episode)
# ---------------------------------------------------------------------------
def setup_run_context(config: dict[str, Any], http_client: httpx.Client) -> dict[str, Any]:
    """
    Pre-create ONE paper trading account and ONE session.
    Returns run_context = {"session_id": "...", "account_id": "...", "accounts": {...}}
    """
    pmb_base = config["services"]["pmb"]["base_url"].rstrip("/")
    pt = config["paper_trading"]

    # 1. Create account
    acct_body = {
        "account_type": pt.get("account_type", "MARGIN"),
        "initial_cash": pt.get("initial_cash", 100000.0),
        "start_date": pt.get("start_date", "2025-01-06"),
        "timezone": pt.get("timezone", "America/New_York"),
    }
    try:
        resp = http_client.post(f"{pmb_base}/v1/accounts", json=acct_body, timeout=30)
        resp.raise_for_status()
        account = resp.json()
        account_id = account["account_id"]
        log.info(f"Created account: {account_id}")
    except Exception as e:
        log.error(f"Failed to create PMB account: {e}")
        # Fallback: use deterministic placeholder for dry-run
        account_id = "acct-eval-placeholder"
        log.warning(f"Using placeholder account_id: {account_id}")

    # 2. Create session
    sess_body = {
        "account_id": account_id,
        "frequency": pt.get("frequency", "1d"),
        "start_ts": pt.get("start_date", "2025-01-06"),
        "end_ts": pt.get("end_date", "2025-01-31"),
        "universe": pt.get("universe", {"stocks": ["AAPL", "MSFT", "NVDA", "TSLA", "JPM", "BAC"]}),
    }
    try:
        resp = http_client.post(f"{pmb_base}/v1/sessions", json=sess_body, timeout=30)
        resp.raise_for_status()
        session = resp.json()
        session_id = session["session_id"]
        log.info(f"Created session: {session_id}")
    except Exception as e:
        log.error(f"Failed to create PMB session: {e}")
        session_id = "sess-eval-placeholder"
        log.warning(f"Using placeholder session_id: {session_id}")

    return {
        "session_id": session_id,
        "account_id": account_id,
        "accounts": {"primary": account_id},
    }


# ---------------------------------------------------------------------------
# Instruction injection
# ---------------------------------------------------------------------------
def inject_context(instruction: str, run_context: dict[str, Any]) -> str:
    """Replace {session_id} and {account_id} placeholders in instruction."""
    return instruction.replace(
        "{session_id}", run_context["session_id"]
    ).replace(
        "{account_id}", run_context["account_id"]
    )


# ---------------------------------------------------------------------------
# Model caller
# ---------------------------------------------------------------------------
def call_model(
    http_client: httpx.Client,
    model_cfg: dict[str, Any],
    instruction: str,
    timeout: int = 90,
) -> tuple[str, float]:
    """Call OpenAI-compatible chat completions. Returns (raw_text, latency_s)."""
    base_url = model_cfg["base_url"].rstrip("/")
    url = f"{base_url}/chat/completions"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if model_cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {model_cfg['api_key']}"

    payload = {
        "model": model_cfg["model_name"],
        "messages": [
            {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ],
        "temperature": 0.0,
        "max_tokens": 3000,
    }

    t0 = time.monotonic()
    resp = http_client.post(url, json=payload, headers=headers, timeout=timeout)
    latency = time.monotonic() - t0
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return content, latency


# ---------------------------------------------------------------------------
# Output parser
# ---------------------------------------------------------------------------
def parse_model_output(raw: str) -> tuple[dict[str, Any] | None, bool, str]:
    """
    Parse model output into dict.
    Returns (parsed, json_valid, error_message).
    """
    cleaned = raw.strip()
    # Strip markdown fences
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        obj = json.loads(cleaned)
        return obj, True, ""
    except json.JSONDecodeError:
        pass

    # Try extracting JSON object
    s = cleaned.find("{")
    e = cleaned.rfind("}")
    if s != -1 and e > s:
        try:
            obj = json.loads(cleaned[s : e + 1])
            return obj, False, "JSON extracted from surrounding text"
        except json.JSONDecodeError:
            pass

    # Fix trailing commas
    try:
        fixed = re.sub(r",\s*([}\]])", r"\1", cleaned)
        obj = json.loads(fixed)
        return obj, False, "Fixed trailing commas"
    except json.JSONDecodeError:
        pass

    return None, False, f"Could not parse JSON (length={len(raw)})"


def validate_planning_schema(parsed: dict[str, Any]) -> list[str]:
    """Validate the planning output schema. Returns list of violations."""
    violations: list[str] = []
    if not isinstance(parsed, dict):
        return ["Root is not an object"]
    if "plan" not in parsed:
        violations.append("Missing 'plan' field")
    elif not isinstance(parsed["plan"], list):
        violations.append("'plan' must be an array")
    if "tool_calls" not in parsed:
        violations.append("Missing 'tool_calls' field")
    elif not isinstance(parsed["tool_calls"], list):
        violations.append("'tool_calls' must be an array")
    else:
        for i, tc in enumerate(parsed["tool_calls"]):
            if not isinstance(tc, dict):
                violations.append(f"tool_calls[{i}] is not an object")
                continue
            for f_name in ("step_id", "tool", "args"):
                if f_name not in tc:
                    violations.append(f"tool_calls[{i}] missing '{f_name}'")
    if "final_answer" not in parsed:
        violations.append("Missing 'final_answer' field")
    elif not isinstance(parsed.get("final_answer"), str):
        violations.append("'final_answer' must be a string")
    return violations


# ---------------------------------------------------------------------------
# Tool executor (live mode)
# ---------------------------------------------------------------------------

# Map tool name -> (method, url_template, param_style)
# param_style: "query" = GET query params, "body" = POST JSON body, "path" = in URL
TOOL_DISPATCH: dict[str, tuple[str, str, str]] = {
    "UPQ.stock.minute":          ("GET",  "{upq}/stock",                    "query"),
    "UPQ.stock.daily":           ("GET",  "{upq}/stock/daily",              "query"),
    "UPQ.option.chain_query":    ("GET",  "{upq}/option/chain_query",       "query"),
    "UPQ.option.ticker_query":   ("GET",  "{upq}/option/ticker_query",      "query"),
    "UPQ.rates.query":           ("GET",  "{upq}/rates/query",              "query"),
    "NPP.events.query":          ("POST", "{npp}/npp/events/query",         "body"),
    "NPP.events.get":            ("GET",  "{npp}/npp/events/{event_id}",    "path"),
    "NPP.events.stream":         ("POST", "{npp}/npp/events/stream",        "body"),
    "NPP.triggers.next":         ("POST", "{npp}/npp/triggers/next",        "body"),
    "NPP.timeline":              ("POST", "{npp}/npp/timeline",             "body"),
    "NPP.calendar.econ":         ("POST", "{npp}/npp/calendar/econ",        "body"),
    "NPP.calendar.earnings":     ("POST", "{npp}/npp/calendar/earnings",    "body"),
    "NPP.news.body":             ("GET",  "{npp}/npp/news/{news_id}/body",  "path"),
    "PMB.account.positions":     ("GET",  "{pmb}/v1/accounts/{account_id}/positions", "path"),
    "PMB.account.orders":        ("GET",  "{pmb}/v1/accounts/{account_id}/orders",    "query"),
    "PMB.account.trades":        ("GET",  "{pmb}/v1/accounts/{account_id}/trades",    "query"),
    "PMB.session.step":          ("POST", "{pmb}/v1/sessions/{session_id}/step",      "body"),
    "PMB.session.stop":          ("POST", "{pmb}/v1/sessions/{session_id}/stop",      "body"),
    "PMB.session.market":        ("GET",  "{pmb}/v1/sessions/{session_id}/market",    "path"),
    "PMB.session.summary":       ("GET",  "{pmb}/v1/sessions/{session_id}/summary",   "path"),
    "PMB.session.export":        ("GET",  "{pmb}/v1/sessions/{session_id}/export",    "query"),
    "PMB.order.place":           ("POST", "{pmb}/v1/orders",                          "body"),
    "PMB.order.cancel":          ("POST", "{pmb}/v1/orders/{order_id}/cancel",        "body"),
    "PMB.order.modify":          ("POST", "{pmb}/v1/orders/{order_id}/modify",        "body"),
}


def _substitute_url(url_template: str, args: dict, bases: dict) -> tuple[str, dict]:
    """
    Fill URL path params and base URLs.
    Returns (final_url, remaining_args_without_path_params).
    """
    url = url_template.format(
        upq=bases["upq"],
        npp=bases["npp"],
        pmb=bases["pmb"],
        # Path params from args
        event_id=args.get("event_id", "UNKNOWN_EVENT_ID"),
        news_id=args.get("news_id", "UNKNOWN_NEWS_ID"),
        account_id=args.get("account_id", "UNKNOWN_ACCT"),
        session_id=args.get("session_id", "UNKNOWN_SESS"),
        order_id=args.get("order_id", "UNKNOWN_ORDER"),
    )
    # Remove path params from remaining args
    remaining = {
        k: v for k, v in args.items()
        if k not in ("event_id", "news_id", "account_id", "session_id", "order_id")
    }
    return url, remaining


def _substitute_args(args: dict, run_context: dict) -> dict:
    """Replace {session_id}/{account_id} string placeholders in args (recursive)."""
    if isinstance(args, dict):
        return {k: _substitute_args(v, run_context) for k, v in args.items()}
    if isinstance(args, list):
        return [_substitute_args(v, run_context) for v in args]
    if isinstance(args, str):
        return args.replace("{session_id}", run_context["session_id"]).replace(
            "{account_id}", run_context["account_id"]
        )
    return args


def execute_tool_call(
    tool_call: dict[str, Any],
    run_context: dict[str, Any],
    bases: dict[str, str],
    http_client: httpx.Client,
) -> dict[str, Any]:
    """
    Execute a single tool call against live services.
    Returns result dict with ok, status, latency_ms, body_summary, error.
    """
    tool = tool_call.get("tool", "")
    raw_args = deepcopy(tool_call.get("args", {}))
    args = _substitute_args(raw_args, run_context)

    dispatch = TOOL_DISPATCH.get(tool)
    if dispatch is None:
        return {"ok": False, "error": f"Unknown tool: {tool}", "status": -1, "latency_ms": 0}

    method, url_template, param_style = dispatch
    url, remaining_args = _substitute_url(url_template, args, bases)

    t0 = time.monotonic()
    try:
        if method == "GET":
            # All remaining args go as query params
            resp = http_client.get(url, params=remaining_args, timeout=30)
        else:
            # POST: all remaining args go as JSON body
            resp = http_client.post(url, json=remaining_args, timeout=30)
        latency_ms = int((time.monotonic() - t0) * 1000)

        try:
            body = resp.json()
        except Exception:
            body = resp.text[:500]

        ok = resp.status_code < 400
        # Summarize body
        body_summary = _summarize_body(body)
        return {
            "ok": ok,
            "status": resp.status_code,
            "latency_ms": latency_ms,
            "body_summary": body_summary,
            "body": body,
            "error": "" if ok else str(body)[:300],
        }
    except Exception as e:
        return {
            "ok": False,
            "status": -1,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "body_summary": "",
            "body": {},
            "error": str(e),
        }


def _summarize_body(body: Any) -> str:
    """Return a short summary string of a response body."""
    if isinstance(body, list):
        return f"list[{len(body)}]"
    if isinstance(body, dict):
        keys = list(body.keys())[:5]
        return f"dict({', '.join(keys)})"
    return str(body)[:100]


# ---------------------------------------------------------------------------
# Episode runner
# ---------------------------------------------------------------------------
@dataclass
class StepLog:
    step_id: str
    tool: str
    args: dict
    ok: bool = False
    status: int = 0
    latency_ms: int = 0
    result_summary: str = ""
    error: str = ""


@dataclass
class EpisodeResult:
    episode_id: str
    model_name: str
    instruction: str
    raw_output: str = ""
    json_valid: bool = False
    schema_violations: list[str] = field(default_factory=list)
    parse_error: str = ""
    plan: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    final_answer: str = ""
    step_logs: list[StepLog] = field(default_factory=list)
    latency_s: float = 0.0
    run_context: dict = field(default_factory=dict)


def run_episode(
    case: dict[str, Any],
    model_cfg: dict[str, Any],
    run_context: dict[str, Any],
    http_client: httpx.Client,
    mode: str,
    bases: dict[str, str],
) -> EpisodeResult:
    """Run a single episode: inject context, call model, execute tools, log."""
    ep = EpisodeResult(
        episode_id=case["id"],
        model_name=model_cfg["model_name"],
        instruction="",
        run_context=run_context,
    )

    # Inject context into instruction
    raw_instruction = case["natural_language_instruction"]
    ep.instruction = inject_context(raw_instruction, run_context)

    # Call model with parse-retry loop.
    # A failed JSON parse is not counted as a performance failure — the runner
    # retries silently (up to MAX_PARSE_RETRIES) and only scores the first
    # successful parse.  Retry attempts are logged as warnings only.
    MAX_PARSE_RETRIES = 5
    parsed: dict[str, Any] | None = None
    json_valid = False
    parse_err = ""

    for attempt in range(1, MAX_PARSE_RETRIES + 1):
        try:
            raw, latency = call_model(http_client, model_cfg, ep.instruction)
        except Exception as e:
            ep.parse_error = f"Model call failed: {e}"
            log.error(f"[{ep.episode_id}] Model call failed: {e}")
            return ep

        parsed, json_valid, parse_err = parse_model_output(raw)

        if parsed is not None:
            # Successful parse — record output and stop retrying
            ep.raw_output = raw
            ep.latency_s = round(latency, 3)
            # Rate-limiting delay (applied per successful call to avoid hitting API limits)
            call_delay = model_cfg.get("call_latency_s", 0.0)
            if call_delay > 0:
                log.debug(f"[{ep.episode_id}] Rate-limit delay: {call_delay}s")
                time.sleep(call_delay)
            break

        remaining = MAX_PARSE_RETRIES - attempt
        log.warning(
            f"[{ep.episode_id}] Parse failed: {parse_err} "
            f"(attempt {attempt}/{MAX_PARSE_RETRIES}"
            + (f", retrying — {remaining} left)" if remaining > 0 else ", giving up)")
        )

    ep.json_valid = json_valid
    ep.parse_error = parse_err

    if parsed is None:
        return ep

    violations = validate_planning_schema(parsed)
    ep.schema_violations = violations

    ep.plan = parsed.get("plan", [])
    ep.tool_calls = parsed.get("tool_calls", []) if isinstance(parsed.get("tool_calls"), list) else []
    ep.final_answer = parsed.get("final_answer", "")

    # Execute in live mode
    if mode == "live":
        for tc in ep.tool_calls:
            step_id = tc.get("step_id", "?")
            tool = tc.get("tool", "?")
            args = tc.get("args", {})

            result = execute_tool_call(tc, run_context, bases, http_client)

            slog = StepLog(
                step_id=step_id,
                tool=tool,
                args=args,
                ok=result.get("ok", False),
                status=result.get("status", -1),
                latency_ms=result.get("latency_ms", 0),
                result_summary=result.get("body_summary", ""),
                error=result.get("error", ""),
            )
            ep.step_logs.append(slog)
            status_sym = "✓" if slog.ok else "✗"
            log.info(
                f"  [{ep.episode_id}] {status_sym} {step_id} {tool} "
                f"→ {slog.status} ({slog.latency_ms}ms) {slog.result_summary}"
            )
    return ep


# ---------------------------------------------------------------------------
# Result serializer
# ---------------------------------------------------------------------------
def ep_to_dict(ep: EpisodeResult) -> dict[str, Any]:
    d = {
        "episode_id": ep.episode_id,
        "model_name": ep.model_name,
        "instruction": ep.instruction,
        "raw_output": ep.raw_output,
        "json_valid": ep.json_valid,
        "schema_violations": ep.schema_violations,
        "parse_error": ep.parse_error,
        "plan": ep.plan,
        "tool_calls": ep.tool_calls,
        "final_answer": ep.final_answer,
        "latency_s": ep.latency_s,
        "run_context": ep.run_context,
        "step_logs": [asdict(s) for s in ep.step_logs],
    }
    return d


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="QFinZero Multi-Step Planning Runner")
    parser.add_argument("--benchmark", required=True, help="Path to benchmark JSONL")
    parser.add_argument("--model-config", required=True, help="Path to models.yaml")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument("--mode", choices=["dry-run", "live"], default="dry-run",
                        help="dry-run: no HTTP calls; live: execute tool calls")
    parser.add_argument("--output-dir", default=None,
                        help="Override output dir (default: ../../runs/<model>/<timestamp>/)")
    parser.add_argument("--call-latency", type=float, default=0.0, metavar="SECONDS",
                        help="Seconds to sleep after each LLM call (rate-limit guard). "
                             "Per-model call_latency_s in models.yaml takes precedence (default: 0)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    models = load_models(args.model_config, global_call_latency_s=args.call_latency)
    cases = load_benchmark(args.benchmark)
    # Index benchmark by episode id for inline scoring
    bench_index: dict[str, dict] = {c["id"]: c for c in cases}

    bases = {
        "upq": cfg["services"]["upq"]["base_url"].rstrip("/"),
        "npp": cfg["services"]["npp"]["base_url"].rstrip("/"),
        "pmb": cfg["services"]["pmb"]["base_url"].rstrip("/"),
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Base output directory — shared across all models for the summary CSV
    base_out_dir = Path(args.output_dir) if args.output_dir else (
        Path(__file__).parent.parent.parent.parent / "runs" / timestamp
    )

    # Collect per-model aggregate scores for the cross-model summary CSV
    all_model_aggs: dict[str, dict[str, Any]] = {}

    with httpx.Client(timeout=90) as http_client:
        # ── PRE-CREATE account + session (live only) ──────────────────────
        if args.mode == "live":
            log.info("=== PRE-SETUP: Creating PMB account and session ===")
            run_context = setup_run_context(cfg, http_client)
            log.info(f"run_context = {json.dumps(run_context, indent=2)}")
        else:
            # Dry-run: use stable placeholder IDs
            run_context = {
                "session_id": "sess-dryrun-2025",
                "account_id": "acct-dryrun-2025",
                "accounts": {"primary": "acct-dryrun-2025"},
            }
            log.info(f"[dry-run] Using placeholder run_context: {run_context}")

        for model_cfg in models:
            model_name = model_cfg["model_name"]
            log.info(f"=== Evaluating model: {model_name} ===")

            # BUG FIX: each model gets its own subdirectory so results don't
            # overwrite each other when --output-dir is provided.
            safe_name = re.sub(r"[^\w\-]", "_", model_name)
            if args.output_dir:
                out_dir = Path(args.output_dir) / safe_name
            else:
                out_dir = Path(__file__).parent.parent.parent.parent / "runs" / safe_name / timestamp
            out_dir.mkdir(parents=True, exist_ok=True)

            results_path = out_dir / "multistep_results.jsonl"
            all_results: list[dict] = []
            all_ep_scores = []  # collect EpisodeScore objects for aggregate

            for case in cases:
                log.info(f"  → Episode: {case['id']} ({case['difficulty']})")
                ep = run_episode(
                    case=case,
                    model_cfg=model_cfg,
                    run_context=run_context,
                    http_client=http_client,
                    mode=args.mode,
                    bases=bases,
                )
                rec = ep_to_dict(ep)

                # ── Inline scoring ────────────────────────────────────────
                if _SCORING_AVAILABLE:
                    ep_score = score_episode(case, rec)
                    rec["scores"] = {
                        m: round(getattr(ep_score, m), 4)
                        for m in ["TM", "PA", "TA", "SS", "DC", "ER", "RS", "EF", "overall"]
                    }
                    rec["scores"]["failure_modes"] = ep_score.failure_modes
                    all_ep_scores.append(ep_score)
                    log.info(
                        f"    SCORE  TM={ep_score.TM:.2f} PA={ep_score.PA:.2f} "
                        f"DC={ep_score.DC:.2f} RS={ep_score.RS:.2f} EF={ep_score.EF:.2f} "
                        f"→ overall={ep_score.overall:.1f}  "
                        f"[steps={len(ep.tool_calls)}/{len(case['expected_steps'])}  "
                        f"json={ep.json_valid}  {ep.latency_s}s]"
                    )
                else:
                    log.info(
                        f"    json_valid={ep.json_valid}  "
                        f"steps_produced={len(ep.tool_calls)}  "
                        f"latency={ep.latency_s}s"
                    )

                all_results.append(rec)

            # Write JSONL
            with open(results_path, "w") as f:
                for rec in all_results:
                    f.write(json.dumps(rec, default=str) + "\n")

            # Also save run_context
            ctx_path = out_dir / "run_context.json"
            with open(ctx_path, "w") as f:
                json.dump(run_context, f, indent=2)

            log.info(f"  Saved {len(all_results)} results → {results_path}")

            # ── Print aggregate summary table ─────────────────────────────
            if _SCORING_AVAILABLE and all_ep_scores:
                agg = aggregate(all_ep_scores)
                _print_summary(model_name, agg, all_ep_scores, out_dir)
                all_model_aggs[model_name] = agg

    # ── Write cross-model summary CSV (mirrors calling runner's summary.csv) ──
    if _SCORING_AVAILABLE and all_model_aggs:
        _write_summary_csv(all_model_aggs, base_out_dir)

    log.info("Done.")


def _write_summary_csv(all_model_aggs: dict[str, dict[str, Any]], out_dir: Path) -> None:
    """Write a cross-model summary CSV — one row per model, mirroring calling/summary.csv."""
    import csv as _csv
    SCORE_METRICS = ["TM", "PA", "TA", "SS", "DC", "ER", "RS", "EF", "overall"]
    fieldnames = ["model_name", *[f"mean_{m}" for m in SCORE_METRICS], "ESR", "n_episodes"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "summary.csv"
    with open(path, "w", newline="") as f:
        writer = _csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for model_name, agg in all_model_aggs.items():
            row: dict[str, Any] = {"model_name": model_name}
            for m in SCORE_METRICS:
                row[f"mean_{m}"] = round(agg.get(f"mean_{m}", 0.0), 4)
            row["ESR"] = round(agg.get("ESR", 0.0), 4)
            row["n_episodes"] = agg.get("n_episodes", 0)
            writer.writerow(row)
    log.info(f"  Cross-model summary CSV → {path}")


def _print_summary(
    model_name: str,
    agg: dict[str, Any],
    scores: list,
    out_dir: Path,
) -> None:
    """Print and save a summary score table after all episodes complete."""
    sep = "─" * 82
    header = f"\n{'═'*82}"
    header += f"\n  SCORE SUMMARY — {model_name}"
    header += f"\n{sep}"

    # Per-episode table
    col_w = {"id": 9, "diff": 7, "TM": 5, "PA": 5, "DC": 5, "RS": 5, "EF": 5, "overall": 8}
    hdr_row = (
        f"  {'ID':<9} {'DIFF':<7} {'TM':>5} {'PA':>5} {'DC':>5} "
        f"{'RS':>5} {'EF':>5} {'OVERALL':>8}  FAILURES"
    )
    log.info(header)
    log.info(hdr_row)
    log.info(f"  {sep}")

    for s in sorted(scores, key=lambda x: x.episode_id):
        fm = ", ".join(s.failure_modes) if s.failure_modes else "—"
        row = (
            f"  {s.episode_id:<9} {s.difficulty:<7} "
            f"{s.TM:>5.2f} {s.PA:>5.2f} {s.DC:>5.2f} "
            f"{s.RS:>5.2f} {s.EF:>5.2f} {s.overall:>8.1f}  {fm}"
        )
        log.info(row)

    log.info(f"  {sep}")
    mean_overall = agg.get("mean_overall", 0)
    esr = agg.get("ESR", 0)
    rec_rate = agg.get("recovery_rate")
    redundant = agg.get("redundant_call_rate", 0)
    log.info(
        f"  {'MEAN':<9} {'':7} "
        f"{agg.get('mean_TM',0):>5.2f} {agg.get('mean_PA',0):>5.2f} "
        f"{agg.get('mean_DC',0):>5.2f} {agg.get('mean_RS',0):>5.2f} "
        f"{agg.get('mean_EF',0):>5.2f} {mean_overall:>8.1f}"
    )
    log.info(f"  {'═'*82}")
    log.info(
        f"  ESR (≥70): {esr*100:.1f}%   "
        f"Recovery: {f'{rec_rate*100:.1f}%' if rec_rate is not None else 'N/A'}   "
        f"Redundant calls: {redundant*100:.1f}%   "
        f"Avg steps: {agg.get('avg_steps_predicted',0):.1f}/{agg.get('avg_steps_expected',0):.1f}"
    )
    log.info(f"  {'═'*82}\n")

    # Save summary JSON alongside results
    summary_path = out_dir / "scores_summary.json"
    import json as _json
    with open(summary_path, "w") as f:
        _json.dump(agg, f, indent=2)
    log.info(f"  Scores summary → {summary_path}")


if __name__ == "__main__":
    main()
