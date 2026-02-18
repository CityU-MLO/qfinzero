#!/usr/bin/env python3
"""
QFinZero Multi-Step Planning Evaluator
========================================

Usage:
    python eval_multistep.py \\
        --results  ../../runs/<model>/multistep_results.jsonl \\
        --benchmark ../benchmarks/qfinzero_multistep_10.jsonl \\
        --output-dir ./<model_name>/

Metrics computed per episode:
    TM  – Tool Match           : correct tool name, endpoint, method per expected step
    PA  – Param Accuracy       : required params present and correct (with tolerance)
    TA  – Time Alignment       : date/time fields within allowed tolerance
    SS  – Step Success         : fraction of executed steps that returned ok (live mode)
    DC  – Dependency Consistency: later steps correctly reference earlier step outputs
    ER  – Execution Reliability : PMB state matches expected_final_state (live mode)
    RS  – Recovery Score       : for recovery episodes, agent eventually completes
    EF  – Efficiency           : penalizes redundant calls

Aggregate outputs:
    ESR – Episode Success Rate
    Avg steps produced vs expected
    Recovery Rate
    Redundant Call Rate
    Overall weighted score

Output files:
    ./eval/<model_name>/summary.json
    ./eval/<model_name>/table.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Tolerance constants
# ---------------------------------------------------------------------------
TOL_INTRADAY_MIN = 5          # ±5 minutes for intraday
TOL_DAILY_DAYS = 1            # ±1 calendar day
TOL_LOOSE_DAYS = 2            # ±2 days for "N trading days" style
TOL_HORIZON_MIN = 60          # ±60 min for horizon_minutes
TOL_NUMERIC_REL = 1e-4        # 0.01% for floats

# Metric weights for overall score
METRIC_WEIGHTS = {
    "TM": 0.20,
    "PA": 0.20,
    "TA": 0.10,
    "SS": 0.10,
    "DC": 0.15,
    "ER": 0.10,
    "RS": 0.10,
    "EF": 0.05,
}

# Recovery episode IDs (known from benchmark design)
RECOVERY_EPISODE_IDS = {"ms-005", "ms-009", "ms-020"}

# Ambiguity-tolerant episodes (accept wider tolerance)
AMBIGUITY_EPISODE_IDS = {"ms-003", "ms-008", "ms-010"}

# ---------------------------------------------------------------------------
# Tool → canonical endpoint / method
# The model output format only has {"step_id","tool","args"} — no endpoint or
# method fields.  We infer both from the tool name so that a correctly-named
# tool is not penalised for a "missing" endpoint.
# ---------------------------------------------------------------------------
TOOL_ENDPOINT_MAP: dict[str, str] = {
    "UPQ.stock.minute":        "/stock",
    "UPQ.stock.daily":         "/stock/daily",
    "UPQ.option.chain_query":  "/option/chain_query",
    "UPQ.option.ticker_query": "/option/ticker_query",
    "UPQ.rates.query":         "/rates/query",
    "NPP.events.query":        "/npp/events/query",
    "NPP.events.get":          "/npp/events/{event_id}",
    "NPP.events.stream":       "/npp/events/stream",
    "NPP.triggers.next":       "/npp/triggers/next",
    "NPP.timeline":            "/npp/timeline",
    "NPP.calendar.econ":       "/npp/calendar/econ",
    "NPP.calendar.earnings":   "/npp/calendar/earnings",
    "NPP.news.body":           "/npp/news/{news_id}/body",
    "PMB.account.positions":   "/v1/accounts/{account_id}/positions",
    "PMB.account.orders":      "/v1/accounts/{account_id}/orders",
    "PMB.account.trades":      "/v1/accounts/{account_id}/trades",
    "PMB.session.step":        "/v1/sessions/{session_id}/step",
    "PMB.session.stop":        "/v1/sessions/{session_id}/stop",
    "PMB.session.market":      "/v1/sessions/{session_id}/market",
    "PMB.session.summary":     "/v1/sessions/{session_id}/summary",
    "PMB.session.export":      "/v1/sessions/{session_id}/export",
    "PMB.order.place":         "/v1/orders",
    "PMB.order.cancel":        "/v1/orders/{order_id}/cancel",
    "PMB.order.modify":        "/v1/orders/{order_id}/modify",
}

TOOL_METHOD_MAP: dict[str, str] = {
    "UPQ.stock.minute":        "GET",
    "UPQ.stock.daily":         "GET",
    "UPQ.option.chain_query":  "GET",
    "UPQ.option.ticker_query": "GET",
    "UPQ.rates.query":         "GET",
    "NPP.events.query":        "POST",
    "NPP.events.get":          "GET",
    "NPP.events.stream":       "POST",
    "NPP.triggers.next":       "POST",
    "NPP.timeline":            "POST",
    "NPP.calendar.econ":       "POST",
    "NPP.calendar.earnings":   "POST",
    "NPP.news.body":           "GET",
    "PMB.account.positions":   "GET",
    "PMB.account.orders":      "GET",
    "PMB.account.trades":      "GET",
    "PMB.session.step":        "POST",
    "PMB.session.stop":        "POST",
    "PMB.session.market":      "GET",
    "PMB.session.summary":     "GET",
    "PMB.session.export":      "GET",
    "PMB.order.place":         "POST",
    "PMB.order.cancel":        "POST",
    "PMB.order.modify":        "POST",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class EpisodeScore:
    episode_id: str
    category: str
    difficulty: str
    is_recovery: bool = False
    n_expected_steps: int = 0
    n_predicted_steps: int = 0
    TM: float = 0.0   # Tool Match
    PA: float = 0.0   # Param Accuracy
    TA: float = 1.0   # Time Alignment
    SS: float = 0.0   # Step Success (live) — 1.0 default in dry-run
    DC: float = 0.0   # Dependency Consistency
    ER: float = 1.0   # Execution Reliability (live) — 1.0 default
    RS: float = 1.0   # Recovery Score — 1.0 for non-recovery episodes
    EF: float = 1.0   # Efficiency
    overall: float = 0.0
    json_valid: bool = False
    failure_modes: list[str] = field(default_factory=list)
    notes: str = ""

    def compute_overall(self) -> float:
        self.overall = (
            METRIC_WEIGHTS["TM"] * self.TM
            + METRIC_WEIGHTS["PA"] * self.PA
            + METRIC_WEIGHTS["TA"] * self.TA
            + METRIC_WEIGHTS["SS"] * self.SS
            + METRIC_WEIGHTS["DC"] * self.DC
            + METRIC_WEIGHTS["ER"] * self.ER
            + METRIC_WEIGHTS["RS"] * self.RS
            + METRIC_WEIGHTS["EF"] * self.EF
        ) * 100
        return self.overall


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = str(s).strip().rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _time_match(predicted: Any, expected: Any, tolerance: str) -> float:
    """Return 1.0 if within tolerance, 0.0 otherwise."""
    if expected is None:
        return 1.0
    if predicted is None:
        return 0.0
    p = _parse_dt(str(predicted))
    e = _parse_dt(str(expected))
    if p is None or e is None:
        # Try string compare if neither can be parsed
        return 1.0 if str(predicted).lower() == str(expected).lower() else 0.0
    diff = abs((p - e).total_seconds())
    if tolerance == "exact":
        return 1.0 if diff == 0 else 0.0
    elif tolerance == "5min":
        return 1.0 if diff <= TOL_INTRADAY_MIN * 60 else 0.0
    elif tolerance == "1day":
        return 1.0 if diff <= TOL_DAILY_DAYS * 86400 else 0.0
    elif tolerance == "2day":
        return 1.0 if diff <= TOL_LOOSE_DAYS * 86400 else 0.0
    elif tolerance in ("30min", "60min"):
        limit = int(re.sub(r"\D", "", tolerance)) * 60
        return 1.0 if diff <= limit else 0.0
    return 1.0 if diff <= 300 else 0.0


# ---------------------------------------------------------------------------
# Param comparison
# ---------------------------------------------------------------------------
def _is_placeholder(v: Any) -> bool:
    """Check if a value is a dependency placeholder like {session_id}."""
    if isinstance(v, str):
        return (v.startswith("{") and v.endswith("}")) or \
               (v.startswith("<") and v.endswith(">"))
    return False


def _deep_param_match(pred: Any, exp: Any) -> tuple[float, list[str]]:
    """
    Recursively compare predicted param value against expected.
    Returns (score in [0,1], list of failure codes).
    """
    failures: list[str] = []

    # Skip dependency placeholders in expected
    if _is_placeholder(exp):
        return 1.0, []

    if isinstance(exp, dict) and isinstance(pred, dict):
        if not exp:
            return 1.0, []
        scores = []
        for k, ev in exp.items():
            pv = pred.get(k)
            if pv is None:
                failures.append("missing_required_param")
                scores.append(0.0)
            else:
                sc, fs = _deep_param_match(pv, ev)
                scores.append(sc)
                failures.extend(fs)
        return sum(scores) / len(scores), failures

    if isinstance(exp, list) and isinstance(pred, list):
        exp_set = {str(x).upper() for x in exp}
        pred_set = {str(x).upper() for x in pred}
        if exp_set == pred_set:
            return 1.0, []
        inter = exp_set & pred_set
        union = exp_set | pred_set
        if inter:
            return len(inter) / len(union), ["wrong_param_value"]
        return 0.0, ["wrong_param_value"]

    if isinstance(exp, (int, float)) and isinstance(pred, (int, float)):
        if math.isclose(float(exp), float(pred), rel_tol=TOL_NUMERIC_REL):
            return 1.0, []
        return 0.0, ["wrong_param_value"]

    # String comparison (case-insensitive)
    if str(exp).lower() == str(pred).lower():
        return 1.0, []
    return 0.0, ["wrong_param_value"]


def _score_params(pred_args: dict, required_params: dict) -> tuple[float, list[str]]:
    """Score required params against predicted args. Returns (score, failures)."""
    if not required_params:
        return 1.0, []
    return _deep_param_match(pred_args, required_params)


# ---------------------------------------------------------------------------
# Tool name matching
# ---------------------------------------------------------------------------
def _tool_family(tool_name: str) -> str:
    """Return UPQ / NPP / PMB / UNKNOWN."""
    if tool_name.startswith("UPQ"):
        return "UPQ"
    if tool_name.startswith("NPP"):
        return "NPP"
    if tool_name.startswith("PMB"):
        return "PMB"
    return "UNKNOWN"


def _tool_match_score(pred_tool: str, exp_tool: str) -> float:
    """1.0 = exact match, 0.5 = same family, 0.0 = different family."""
    if pred_tool == exp_tool:
        return 1.0
    if _tool_family(pred_tool) == _tool_family(exp_tool):
        return 0.5
    return 0.0


def _endpoint_match(pred_ep: str | None, exp_ep: str | None, run_context: dict) -> float:
    """Compare endpoints with path-param substitution."""
    if exp_ep is None:
        return 1.0
    if pred_ep is None:
        return 0.0
    # Substitute dynamic IDs in expected endpoint
    exp_norm = exp_ep
    for placeholder, value in [
        ("{session_id}", run_context.get("session_id", "")),
        ("{account_id}", run_context.get("account_id", "")),
        ("{order_id}",   ""),   # unknown at plan time — skip check
        ("{event_id}",   ""),
        ("{news_id}",    ""),
    ]:
        exp_norm = exp_norm.replace(placeholder, value)

    # Normalize
    exp_norm = exp_norm.strip("/").lower()
    pred_norm = pred_ep.strip("/").lower() if pred_ep else ""

    # For path params we don't know (order_id, event_id, news_id):
    # accept any non-empty segment in corresponding position
    def tokenize(s: str) -> list[str]:
        return [t for t in s.split("/") if t]

    exp_parts = tokenize(exp_norm)
    pred_parts = tokenize(pred_norm)

    if exp_parts == pred_parts:
        return 1.0
    # Allow dynamic segments (empty in exp after substitution) to match anything
    if len(exp_parts) == len(pred_parts):
        matches = sum(
            1 for a, b in zip(exp_parts, pred_parts)
            if a == b or a == ""  # empty = unknown placeholder
        )
        return matches / len(exp_parts)
    # Prefix match partial credit
    if pred_parts and exp_parts and pred_parts[0] == exp_parts[0]:
        return 0.3
    return 0.0


# ---------------------------------------------------------------------------
# TM – Tool Match
# ---------------------------------------------------------------------------
def _score_TM(
    expected_steps: list[dict],
    tool_calls: list[dict],
    run_context: dict,
) -> tuple[float, list[str]]:
    """
    For each expected step find the best matching predicted tool_call.
    Returns (TM score in [0,1], failure_modes).
    """
    failures: list[str] = []
    if not expected_steps:
        return 1.0, []
    if not tool_calls:
        failures.append("false_refusal")
        return 0.0, failures

    step_scores: list[float] = []
    for exp in expected_steps:
        exp_tool = exp.get("tool_name", "")
        exp_ep   = exp.get("endpoint", "")
        exp_meth = exp.get("method", "GET").upper()

        best = 0.0
        for pred in tool_calls:
            pred_tool = pred.get("tool", "")
            # The model output schema only has {step_id, tool, args} — no
            # endpoint or method fields.  Infer both from the tool name so
            # that a correctly-named tool is not penalised for omitting them.
            pred_ep   = pred.get("endpoint") or TOOL_ENDPOINT_MAP.get(pred_tool, "")
            raw_meth  = pred.get("method", "")
            pred_meth = (raw_meth.upper() if raw_meth
                         else TOOL_METHOD_MAP.get(pred_tool, ""))

            t_score = _tool_match_score(pred_tool, exp_tool)
            e_score = _endpoint_match(pred_ep, exp_ep, run_context)
            # Method: 1.0 exact, 0.0 wrong (absent already resolved above)
            m_score = 1.0 if (not pred_meth or pred_meth == exp_meth) else 0.0

            combined = 0.5 * t_score + 0.3 * e_score + 0.2 * m_score
            if combined > best:
                best = combined

        if best < 0.5:
            if best == 0.0:
                failures.append("missing_call")
            else:
                failures.append("wrong_tool_family")
        elif best < 1.0:
            failures.append("wrong_tool_action")

        step_scores.append(best)

    return sum(step_scores) / len(step_scores), failures


# ---------------------------------------------------------------------------
# PA – Param Accuracy
# ---------------------------------------------------------------------------
def _score_PA(
    expected_steps: list[dict],
    tool_calls: list[dict],
    run_context: dict,
) -> tuple[float, list[str]]:
    """Score required params for each expected step."""
    if not expected_steps:
        return 1.0, []
    if not tool_calls:
        return 0.0, ["missing_call"]

    all_failures: list[str] = []
    step_scores: list[float] = []

    for exp in expected_steps:
        exp_tool    = exp.get("tool_name", "")
        req_params  = exp.get("required_params", {})
        # Substitute placeholders in expected params
        req_params  = _substitute_expected(req_params, run_context)

        best_pa = 0.0
        best_fs: list[str] = []
        for pred in tool_calls:
            if _tool_match_score(pred.get("tool", ""), exp_tool) > 0:
                pred_args = pred.get("args", {})
                sc, fs = _score_params(pred_args, req_params)
                if sc > best_pa:
                    best_pa = sc
                    best_fs = fs
        step_scores.append(best_pa)
        all_failures.extend(best_fs)

    return sum(step_scores) / len(step_scores), all_failures


def _substitute_expected(obj: Any, run_context: dict) -> Any:
    """Replace {session_id}/{account_id} in expected params."""
    if isinstance(obj, dict):
        return {k: _substitute_expected(v, run_context) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_expected(v, run_context) for v in obj]
    if isinstance(obj, str):
        return obj.replace("{session_id}", run_context.get("session_id", "")) \
                  .replace("{account_id}", run_context.get("account_id", ""))
    return obj


# ---------------------------------------------------------------------------
# TA – Time Alignment
# ---------------------------------------------------------------------------
def _score_TA(
    expected_steps: list[dict],
    tool_calls: list[dict],
) -> tuple[float, list[str]]:
    """Check time/date fields against expected time_constraints."""
    if not expected_steps:
        return 1.0, []

    failures: list[str] = []
    step_scores: list[float] = []

    for exp in expected_steps:
        tc = exp.get("time_constraints", {})
        if not tc:
            step_scores.append(1.0)
            continue
        tolerance = tc.get("tolerance", "exact")
        time_fields = [k for k in tc if k not in ("format", "tolerance")]
        if not time_fields:
            step_scores.append(1.0)
            continue

        exp_tool = exp.get("tool_name", "")
        best_ta = 0.0
        for pred in tool_calls:
            if _tool_match_score(pred.get("tool", ""), exp_tool) == 0:
                continue
            pred_args = pred.get("args", {})
            field_scores = []
            for tf in time_fields:
                exp_val  = tc.get(tf)
                pred_val = pred_args.get(tf)
                fs = _time_match(pred_val, exp_val, tolerance)
                if fs < 1.0:
                    failures.append("wrong_time_value")
                field_scores.append(fs)
            ta = sum(field_scores) / len(field_scores) if field_scores else 1.0
            best_ta = max(best_ta, ta)
        step_scores.append(best_ta)

    return sum(step_scores) / len(step_scores) if step_scores else 1.0, failures


# ---------------------------------------------------------------------------
# SS – Step Success (live mode)
# ---------------------------------------------------------------------------
def _score_SS(step_logs: list[dict]) -> float:
    """Fraction of executed steps that returned ok."""
    if not step_logs:
        return 1.0  # dry-run: assume success
    ok_count = sum(1 for s in step_logs if s.get("ok", False))
    return ok_count / len(step_logs)


# ---------------------------------------------------------------------------
# DC – Dependency Consistency
# ---------------------------------------------------------------------------
def _score_DC(
    expected_steps: list[dict],
    tool_calls: list[dict],
) -> tuple[float, list[str]]:
    """
    Check that tool calls with inter-step dependencies appear in the correct order.
    Also penalizes if a step that depends on a prior result is placed before it.

    Strategy:
    1. Build dependency graph from expected_steps (step_ids).
    2. Find matching tool calls and verify their order.
    3. Check that PMB order_id / event_id dependencies are handled (non-null args
       in positions that require prior results).
    """
    if not expected_steps or not tool_calls:
        return 1.0, []

    failures: list[str] = []

    # Extract step_ids from predicted tool_calls (if present)
    pred_step_ids = [tc.get("step_id", f"auto_{i}") for i, tc in enumerate(tool_calls)]
    pred_tools    = [tc.get("tool", "") for tc in tool_calls]

    # Build expected ordering from expected_steps
    exp_tools = [s.get("tool_name", "") for s in expected_steps]

    # Map each expected tool to position in predicted list
    pred_positions: list[int | None] = []
    used = set()
    for et in exp_tools:
        found = None
        for j, pt in enumerate(pred_tools):
            if j not in used and _tool_match_score(pt, et) >= 0.5:
                found = j
                used.add(j)
                break
        pred_positions.append(found)

    # Count order violations
    filled = [p for p in pred_positions if p is not None]
    inversions = 0
    for i in range(len(filled)):
        for j in range(i + 1, len(filled)):
            if filled[i] > filled[j]:
                inversions += 1
    max_inv = len(filled) * (len(filled) - 1) / 2

    if inversions > 0:
        failures.append("wrong_call_order")

    order_score = 1.0 - (inversions / max_inv) if max_inv > 0 else 1.0

    # Check that dependent steps have non-empty args in key fields
    # (rough check: if expected required_params contains {session_id}/{account_id}
    #  the predicted args must also have non-empty corresponding values)
    dep_ok = []
    for i, exp in enumerate(expected_steps):
        req = exp.get("required_params", {})
        if not any(_is_placeholder(v) for v in _flatten_values(req)):
            dep_ok.append(1.0)
            continue
        # Find matching pred
        matched = False
        for pred in tool_calls:
            if _tool_match_score(pred.get("tool", ""), exp.get("tool_name", "")) >= 0.5:
                args = pred.get("args", {})
                # Session and account must be non-empty
                sid = _nested_get(args, "session_id")
                aid = _nested_get(args, "account_id")
                if sid and aid:
                    matched = True
                    break
        dep_ok.append(1.0 if matched else 0.5)

    dep_score = sum(dep_ok) / len(dep_ok) if dep_ok else 1.0
    dc = 0.6 * order_score + 0.4 * dep_score
    return dc, failures


def _flatten_values(obj: Any) -> list[Any]:
    if isinstance(obj, dict):
        result = []
        for v in obj.values():
            result.extend(_flatten_values(v))
        return result
    if isinstance(obj, list):
        result = []
        for v in obj:
            result.extend(_flatten_values(v))
        return result
    return [obj]


def _nested_get(d: dict, key: str) -> Any:
    """Search for key at any depth in nested dict."""
    if not isinstance(d, dict):
        return None
    if key in d:
        return d[key]
    for v in d.values():
        result = _nested_get(v, key)
        if result is not None:
            return result
    return None


# ---------------------------------------------------------------------------
# ER – Execution Reliability (live mode)
# ---------------------------------------------------------------------------
def _score_ER(
    step_logs: list[dict],
    expected_final_state: dict,
    tool_calls: list[dict],
) -> float:
    """
    In live mode: compare resulting PMB state with expected_final_state.
    In dry-run: return 1.0.
    """
    if not step_logs:
        return 1.0  # dry-run

    # Check order placement: if expected_final_state says open_orders=N,
    # count how many PMB.order.place calls succeeded
    exp_orders = expected_final_state.get("open_orders", None)
    if exp_orders is not None:
        place_logs = [s for s in step_logs
                      if "order.place" in s.get("tool", "") and s.get("ok")]
        ratio = min(1.0, len(place_logs) / max(1, exp_orders))
        return ratio

    # Default: fraction of PMB calls that succeeded
    pmb_logs = [s for s in step_logs if s.get("tool", "").startswith("PMB.")]
    if not pmb_logs:
        return 1.0
    return sum(1 for s in pmb_logs if s.get("ok", False)) / len(pmb_logs)


# ---------------------------------------------------------------------------
# RS – Recovery Score
# ---------------------------------------------------------------------------
def _score_RS(
    episode_id: str,
    expected_steps: list[dict],
    tool_calls: list[dict],
    step_logs: list[dict],
    is_live: bool,
) -> float:
    """
    For recovery episodes: agent should include BOTH the initial (wrong) attempt
    and a corrected follow-up step. Full credit if:
    1. The recovery step tool is present in tool_calls.
    2. (Live mode) The recovery step executed ok.

    For non-recovery episodes: return 1.0.
    """
    if episode_id not in RECOVERY_EPISODE_IDS:
        return 1.0

    # Find recovery steps (s2 is always the recovery step by convention)
    recovery_steps = [s for s in expected_steps if s.get("step_id") == "s2"]
    if not recovery_steps:
        return 1.0

    rec_step = recovery_steps[0]
    rec_tool = rec_step.get("tool_name", "")

    # Check if recovery tool is in predicted tool_calls
    rec_present = any(_tool_match_score(tc.get("tool", ""), rec_tool) >= 0.5
                      for tc in tool_calls)
    if not rec_present:
        return 0.0

    if is_live and step_logs:
        # Check that the recovery step actually succeeded
        for slog in step_logs:
            if _tool_match_score(slog.get("tool", ""), rec_tool) >= 0.5:
                return 1.0 if slog.get("ok") else 0.5
        return 0.5  # present but not found in logs

    return 1.0 if rec_present else 0.0


# ---------------------------------------------------------------------------
# EF – Efficiency
# ---------------------------------------------------------------------------
def _score_EF(n_expected: int, n_predicted: int) -> float:
    """
    Penalize redundant (extra) steps beyond what's expected.
    -0.15 per extra step, floored at 0.
    """
    if n_predicted <= n_expected:
        return 1.0
    extra = n_predicted - n_expected
    return max(0.0, 1.0 - 0.15 * extra)


# ---------------------------------------------------------------------------
# Episode scorer
# ---------------------------------------------------------------------------
def score_episode(
    case: dict[str, Any],
    result: dict[str, Any],
) -> EpisodeScore:
    """Score one episode result against its benchmark case."""
    ep_id      = case["id"]
    difficulty = case.get("difficulty", "medium")
    category   = case.get("category", "multi_step")
    exp_steps  = case.get("expected_steps", [])
    gt         = case.get("ground_truth", {})
    exp_final  = gt.get("expected_final_state", {})

    is_recovery = ep_id in RECOVERY_EPISODE_IDS
    is_live     = bool(result.get("step_logs"))

    tool_calls  = result.get("tool_calls", []) or []
    step_logs   = result.get("step_logs", []) or []
    json_valid  = result.get("json_valid", False)
    run_context = result.get("run_context", {})

    score = EpisodeScore(
        episode_id=ep_id,
        category=category,
        difficulty=difficulty,
        is_recovery=is_recovery,
        n_expected_steps=len(exp_steps),
        n_predicted_steps=len(tool_calls),
        json_valid=json_valid,
    )

    if not json_valid and not tool_calls:
        score.failure_modes = ["invalid_json"]
        score.TM = score.PA = score.TA = score.DC = 0.0
        score.SS = 0.0
        score.RS = 0.0 if is_recovery else 1.0
        score.EF = 1.0
        score.ER = 1.0
        score.compute_overall()
        return score

    all_failures: list[str] = []

    # -- TM --
    score.TM, f_tm = _score_TM(exp_steps, tool_calls, run_context)
    all_failures.extend(f_tm)

    # -- PA --
    score.PA, f_pa = _score_PA(exp_steps, tool_calls, run_context)
    all_failures.extend(f_pa)

    # -- TA --
    score.TA, f_ta = _score_TA(exp_steps, tool_calls)
    all_failures.extend(f_ta)

    # -- SS --
    score.SS = _score_SS(step_logs)

    # -- DC --
    score.DC, f_dc = _score_DC(exp_steps, tool_calls)
    all_failures.extend(f_dc)

    # -- ER --
    score.ER = _score_ER(step_logs, exp_final, tool_calls)

    # -- RS --
    score.RS = _score_RS(ep_id, exp_steps, tool_calls, step_logs, is_live)
    if is_recovery and score.RS < 1.0:
        all_failures.append("recovery_failed")

    # -- EF --
    score.EF = _score_EF(len(exp_steps), len(tool_calls))
    if score.EF < 1.0:
        all_failures.append("redundant_call")

    score.failure_modes = list(set(all_failures))
    score.compute_overall()
    return score


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------
METRIC_NAMES = ["TM", "PA", "TA", "SS", "DC", "ER", "RS", "EF", "overall"]


def aggregate(scores: list[EpisodeScore]) -> dict[str, Any]:
    n = len(scores)
    if n == 0:
        return {}

    summary: dict[str, Any] = {"n_episodes": n}

    for m in METRIC_NAMES:
        vals = [getattr(s, m) for s in scores]
        summary[f"mean_{m}"]  = round(sum(vals) / n, 4)
        summary[f"min_{m}"]   = round(min(vals), 4)
        summary[f"max_{m}"]   = round(max(vals), 4)

    # Episode Success Rate (overall >= 70)
    success = [s for s in scores if s.overall >= 70.0]
    summary["ESR"] = round(len(success) / n, 4)

    # Avg steps
    summary["avg_steps_expected"]  = round(sum(s.n_expected_steps for s in scores) / n, 2)
    summary["avg_steps_predicted"] = round(sum(s.n_predicted_steps for s in scores) / n, 2)

    # Recovery Rate
    rec_eps = [s for s in scores if s.is_recovery]
    if rec_eps:
        summary["recovery_rate"] = round(sum(s.RS for s in rec_eps) / len(rec_eps), 4)
    else:
        summary["recovery_rate"] = None

    # Redundant Call Rate
    redundant_eps = [s for s in scores if "redundant_call" in s.failure_modes]
    summary["redundant_call_rate"] = round(len(redundant_eps) / n, 4)

    # By difficulty
    for diff in ("easy", "medium", "hard"):
        sub = [s for s in scores if s.difficulty == diff]
        if sub:
            summary[f"n_{diff}"] = len(sub)
            summary[f"mean_overall_{diff}"] = round(
                sum(s.overall for s in sub) / len(sub), 4
            )

    # Failure mode distribution
    fm_counts: dict[str, int] = {}
    for s in scores:
        for fm in s.failure_modes:
            fm_counts[fm] = fm_counts.get(fm, 0) + 1
    summary["failure_modes"] = dict(sorted(fm_counts.items(), key=lambda x: -x[1]))

    return summary


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------
CSV_FIELDS = [
    "episode_id", "category", "difficulty", "is_recovery",
    "n_expected_steps", "n_predicted_steps",
    "TM", "PA", "TA", "SS", "DC", "ER", "RS", "EF", "overall",
    "json_valid", "failure_modes",
]


def write_table_csv(scores: list[EpisodeScore], path: Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for s in sorted(scores, key=lambda x: x.episode_id):
            row = asdict(s)
            row["failure_modes"] = "; ".join(row["failure_modes"])
            for m in METRIC_NAMES:
                row[m] = round(row[m], 4)
            writer.writerow({k: row[k] for k in CSV_FIELDS})


def write_summary_json(agg: dict, path: Path) -> None:
    with open(path, "w") as f:
        json.dump(agg, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="QFinZero Multi-Step Evaluator")
    parser.add_argument("--results",   required=True, help="Path to multistep_results.jsonl")
    parser.add_argument("--benchmark", required=True, help="Path to benchmark JSONL")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory (default: ./<model_name>/)")
    args = parser.parse_args()

    # Load benchmark
    bench: dict[str, dict] = {}
    with open(args.benchmark) as f:
        for line in f:
            line = line.strip()
            if line:
                case = json.loads(line)
                bench[case["id"]] = case

    # Load results
    results: list[dict] = []
    model_name = "unknown"
    with open(args.results) as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                results.append(rec)
                if rec.get("model_name"):
                    model_name = rec["model_name"]

    print(f"Loaded {len(results)} results for model: {model_name}")

    # Score each episode
    scores: list[EpisodeScore] = []
    for rec in results:
        ep_id = rec.get("episode_id", "")
        case = bench.get(ep_id)
        if case is None:
            print(f"Warning: episode {ep_id} not found in benchmark, skipping")
            continue
        ep_score = score_episode(case, rec)
        scores.append(ep_score)
        print(
            f"  {ep_id:8s} | TM={ep_score.TM:.2f} PA={ep_score.PA:.2f} "
            f"DC={ep_score.DC:.2f} RS={ep_score.RS:.2f} EF={ep_score.EF:.2f} "
            f"→ overall={ep_score.overall:.1f}"
        )

    # Aggregate
    agg = aggregate(scores)

    print("\n=== SUMMARY ===")
    print(f"Episodes scored : {agg.get('n_episodes', 0)}")
    print(f"ESR (≥70)       : {agg.get('ESR', 0)*100:.1f}%")
    print(f"Mean overall    : {agg.get('mean_overall', 0):.1f}")
    print(f"Recovery rate   : {agg.get('recovery_rate', 'N/A')}")
    print(f"Redundant rate  : {agg.get('redundant_call_rate', 0)*100:.1f}%")

    # Output dir
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        out_dir = Path(__file__).parent / model_name
    out_dir.mkdir(parents=True, exist_ok=True)

    table_path   = out_dir / "table.csv"
    summary_path = out_dir / "summary.json"

    write_table_csv(scores, table_path)
    write_summary_json(agg, summary_path)

    print(f"\nWrote: {table_path}")
    print(f"Wrote: {summary_path}")


if __name__ == "__main__":
    main()
