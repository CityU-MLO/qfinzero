"""
QFinZero Tool Calling Evaluation — Metrics & Scoring
=====================================================

This module defines all evaluation metrics, scoring rules, tolerance
thresholds, and the unified scoring formula.

Metric Definitions
------------------
1. TSA  – Tool Selection Accuracy
2. EC   – Endpoint Correctness
3. PA   – Parameter Accuracy
4. TAS  – Time Alignment Score
5. COS  – Call Order Score
6. JV   – JSON Validity
7. OCP  – Over-Calling Penalty
8. FOC  – Final Output Completeness

Scoring Formula
---------------
overall_score = (
    0.20 * TSA +
    0.15 * EC  +
    0.20 * PA  +
    0.15 * TAS +
    0.10 * COS +
    0.05 * JV  +
    0.10 * OCP +
    0.05 * FOC
) * 100

All component scores are in [0, 1].

Category Weights (for category-level aggregation)
--------------------------------------------------
price_query      : 0.25
news_query       : 0.20
calendar_query   : 0.15
broker_query     : 0.25
multi_tool_chain : 0.15
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Tolerance thresholds
# ---------------------------------------------------------------------------
TIME_TOLERANCE_INTRADAY_MINUTES = 5      # minute-level queries: +/- 5 min
TIME_TOLERANCE_DAILY_DAYS = 1            # daily queries: +/- 1 calendar day
TIME_TOLERANCE_HORIZON_MINUTES = 30      # horizon_minutes: +/- 30 min
TIME_TOLERANCE_LOOSE_DAYS = 2            # "past N trading days" style

CATEGORY_WEIGHTS = {
    "price_query": 0.25,
    "news_query": 0.20,
    "calendar_query": 0.15,
    "broker_query": 0.25,
    "multi_tool_chain": 0.15,
}

METRIC_WEIGHTS = {
    "TSA": 0.20,
    "EC": 0.15,
    "PA": 0.20,
    "TAS": 0.15,
    "COS": 0.10,
    "JV": 0.05,
    "OCP": 0.10,
    "FOC": 0.05,
}

# Canonical tool name -> (family, action) for TSA evaluation
TOOL_FAMILY_MAP = {
    "UPQ.stock.minute": ("UPQ", "stock.minute"),
    "UPQ.stock.daily": ("UPQ", "stock.daily"),
    "UPQ.option.chain_query": ("UPQ", "option.chain_query"),
    "UPQ.option.ticker_query": ("UPQ", "option.ticker_query"),
    "UPQ.rates.query": ("UPQ", "rates.query"),
    "NPP.events.query": ("NPP", "events.query"),
    "NPP.events.get": ("NPP", "events.get"),
    "NPP.events.stream": ("NPP", "events.stream"),
    "NPP.triggers.next": ("NPP", "triggers.next"),
    "NPP.timeline": ("NPP", "timeline"),
    "NPP.calendar.econ": ("NPP", "calendar.econ"),
    "NPP.calendar.earnings": ("NPP", "calendar.earnings"),
    "NPP.news.body": ("NPP", "news.body"),
    "PMB.account.create": ("PMB", "account.create"),
    "PMB.account.positions": ("PMB", "account.positions"),
    "PMB.account.orders": ("PMB", "account.orders"),
    "PMB.account.trades": ("PMB", "account.trades"),
    "PMB.session.create": ("PMB", "session.create"),
    "PMB.session.step": ("PMB", "session.step"),
    "PMB.session.stop": ("PMB", "session.stop"),
    "PMB.session.summary": ("PMB", "session.summary"),
    "PMB.session.export": ("PMB", "session.export"),
    "PMB.session.market": ("PMB", "session.market"),
    "PMB.order.place": ("PMB", "order.place"),
    "PMB.order.cancel": ("PMB", "order.cancel"),
    "PMB.order.modify": ("PMB", "order.modify"),
    "REFUSE": ("REFUSE", "refuse"),
}

# ---------------------------------------------------------------------------
# Failure Mode Taxonomy
# ---------------------------------------------------------------------------
FAILURE_MODES = {
    "wrong_tool_family": "Selected wrong service family (e.g. UPQ instead of NPP)",
    "wrong_tool_action": "Correct family but wrong action (e.g. stock.daily instead of stock.minute)",
    "wrong_endpoint": "Tool name correct but endpoint path wrong",
    "wrong_method": "Correct endpoint but wrong HTTP method (GET vs POST)",
    "missing_required_param": "A required parameter was omitted",
    "wrong_param_value": "Required parameter present but value is wrong",
    "wrong_param_type": "Parameter has wrong type (string vs number, etc.)",
    "hallucinated_endpoint": "Model invented a non-existent endpoint",
    "hallucinated_param": "Model invented a parameter that doesn't exist",
    "wrong_time_format": "Time/date in wrong format (e.g. date instead of datetime)",
    "wrong_time_value": "Time value outside tolerance window",
    "wrong_timezone": "Timezone mismatch (UTC vs ET vs missing Z)",
    "wrong_call_order": "Tool calls in wrong dependency order",
    "redundant_call": "Extra tool call not needed for the task",
    "missing_call": "Expected tool call was omitted entirely",
    "invalid_json": "Model output was not valid JSON",
    "schema_violation": "JSON valid but doesn't match expected schema",
    "false_refusal": "Model refused a valid request",
    "missed_refusal": "Model attempted an impossible/invalid request instead of refusing",
    "wrong_granularity": "Wrong data resolution (minute vs daily vs weekly)",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ToolCallGold:
    """Single expected tool call from the benchmark."""
    tool_name: str
    endpoint: str | None
    method: str | None
    required_params: dict[str, Any]
    optional_params: dict[str, Any]
    time_constraints: dict[str, Any]


@dataclass
class ToolCallPredicted:
    """Single tool call parsed from model output."""
    tool_name: str
    method: str
    endpoint: str
    params: dict[str, Any]


@dataclass
class CaseResult:
    """Evaluation result for a single benchmark case."""
    case_id: str
    category: str
    difficulty: str
    tsa: float = 0.0
    ec: float = 0.0
    pa: float = 0.0
    tas: float = 0.0
    cos: float = 0.0
    jv: float = 1.0
    ocp: float = 1.0
    foc: float = 0.0
    overall: float = 0.0
    failure_modes: list[str] = field(default_factory=list)
    notes: str = ""

    def compute_overall(self) -> float:
        self.overall = (
            METRIC_WEIGHTS["TSA"] * self.tsa
            + METRIC_WEIGHTS["EC"] * self.ec
            + METRIC_WEIGHTS["PA"] * self.pa
            + METRIC_WEIGHTS["TAS"] * self.tas
            + METRIC_WEIGHTS["COS"] * self.cos
            + METRIC_WEIGHTS["JV"] * self.jv
            + METRIC_WEIGHTS["OCP"] * self.ocp
            + METRIC_WEIGHTS["FOC"] * self.foc
        ) * 100
        return self.overall


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _parse_time(s: str) -> datetime | None:
    """Try to parse a datetime or date string."""
    if s is None:
        return None
    s = str(s).rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _time_within_tolerance(
    predicted: str | None,
    expected: str | None,
    tolerance_key: str | None,
) -> float:
    """Return 1.0 if within tolerance, 0.0 otherwise, 0.5 for partial."""
    if expected is None:
        return 1.0
    if predicted is None:
        return 0.0
    p = _parse_time(str(predicted))
    e = _parse_time(str(expected))
    if p is None or e is None:
        return 0.0

    diff = abs((p - e).total_seconds())

    if tolerance_key == "exact":
        return 1.0 if diff == 0 else 0.0
    elif tolerance_key == "5min":
        return 1.0 if diff <= TIME_TOLERANCE_INTRADAY_MINUTES * 60 else 0.0
    elif tolerance_key == "1day":
        return 1.0 if diff <= TIME_TOLERANCE_DAILY_DAYS * 86400 else 0.0
    elif tolerance_key == "2day":
        return 1.0 if diff <= TIME_TOLERANCE_LOOSE_DAYS * 86400 else 0.0
    elif tolerance_key == "30min":
        return 1.0 if diff <= TIME_TOLERANCE_HORIZON_MINUTES * 60 else 0.0
    elif tolerance_key == "60min":
        return 1.0 if diff <= 60 * 60 else 0.0
    else:
        # Default: 5 minutes
        return 1.0 if diff <= 300 else 0.0


def _deep_match_params(predicted: dict, expected: dict) -> tuple[float, list[str]]:
    """
    Compare predicted params against expected required params.
    Returns (score in [0,1], list of failure_mode strings).

    Handles nested dicts and lists. Skips placeholder values like
    "<from_step_1>" in gold (dependency placeholders).
    """
    if not expected:
        return 1.0, []

    failures: list[str] = []
    matched = 0
    total = 0

    for key, exp_val in expected.items():
        total += 1
        pred_val = predicted.get(key)

        if pred_val is None:
            failures.append("missing_required_param")
            continue

        # Skip dependency placeholders in gold (e.g. "<from_step_1>")
        if isinstance(exp_val, str) and exp_val.startswith("<") and exp_val.endswith(">"):
            matched += 1
            continue

        if isinstance(exp_val, dict) and isinstance(pred_val, dict):
            sub_score, sub_failures = _deep_match_params(pred_val, exp_val)
            matched += sub_score
            failures.extend(sub_failures)
        elif isinstance(exp_val, list) and isinstance(pred_val, list):
            if set(str(x) for x in exp_val) == set(str(x) for x in pred_val):
                matched += 1
            else:
                # Partial credit: jaccard overlap
                exp_set = set(str(x) for x in exp_val)
                pred_set = set(str(x) for x in pred_val)
                if exp_set & pred_set:
                    matched += len(exp_set & pred_set) / len(exp_set | pred_set)
                    failures.append("wrong_param_value")
                else:
                    failures.append("wrong_param_value")
        elif isinstance(exp_val, (int, float)) and isinstance(pred_val, (int, float)):
            if math.isclose(float(exp_val), float(pred_val), rel_tol=1e-4):
                matched += 1
            else:
                failures.append("wrong_param_value")
        elif str(exp_val).lower() == str(pred_val).lower():
            matched += 1
        else:
            failures.append("wrong_param_value")

    return matched / total if total > 0 else 1.0, failures


# ---------------------------------------------------------------------------
# Main per-case scorer
# ---------------------------------------------------------------------------

def score_case(
    gold_calls: list[dict[str, Any]],
    predicted_calls: list[dict[str, Any]],
    predicted_final_answer: dict[str, Any] | None,
    json_was_valid: bool,
) -> CaseResult:
    """
    Score a single benchmark case.

    Parameters
    ----------
    gold_calls : list of dicts from benchmark expected_tool_calls
    predicted_calls : list of dicts parsed from model output (tool_plan)
    predicted_final_answer : dict from model output (final_answer), or None
    json_was_valid : whether the raw model output was valid JSON

    Returns
    -------
    CaseResult with all metric scores filled in.
    """
    result = CaseResult(case_id="", category="", difficulty="")
    all_failures: list[str] = []

    # -- JV: JSON Validity --
    result.jv = 1.0 if json_was_valid else 0.0
    if not json_was_valid:
        all_failures.append("invalid_json")

    n_gold = len(gold_calls)
    n_pred = len(predicted_calls)

    if n_gold == 0 and n_pred == 0:
        # Nothing expected, nothing predicted -> perfect
        result.tsa = result.ec = result.pa = result.tas = result.cos = 1.0
        result.ocp = 1.0
        result.foc = 1.0 if predicted_final_answer else 0.0
        result.failure_modes = all_failures
        result.compute_overall()
        return result

    # Handle REFUSE (negative) test cases
    is_refusal_case = any(g.get("tool_name") == "REFUSE" for g in gold_calls)

    if is_refusal_case:
        if n_pred == 0:
            # Model correctly refused (no tool calls)
            result.tsa = result.ec = result.pa = result.tas = result.cos = 1.0
            result.ocp = 1.0
        elif n_pred > 0 and all(
            p.get("tool_name", "").upper() in ("REFUSE", "CANNOT_COMPLY", "NONE")
            for p in predicted_calls
        ):
            result.tsa = result.ec = result.pa = result.tas = result.cos = 1.0
            result.ocp = 1.0
        else:
            all_failures.append("missed_refusal")
            result.tsa = result.ec = result.pa = result.tas = result.cos = 0.0
            result.ocp = 0.0
        result.foc = 1.0 if predicted_final_answer else 0.5
        result.failure_modes = all_failures
        result.compute_overall()
        return result

    # If model refused but shouldn't have
    if n_pred == 0:
        all_failures.append("false_refusal")
        result.tsa = result.ec = result.pa = result.tas = result.cos = 0.0
        result.ocp = 1.0
        result.foc = 0.0
        result.failure_modes = all_failures
        result.compute_overall()
        return result

    # -- TSA: Tool Selection Accuracy --
    # For each gold call, find best matching predicted call
    tsa_scores: list[float] = []
    for g in gold_calls:
        g_name = g.get("tool_name", "")
        g_family = TOOL_FAMILY_MAP.get(g_name, ("?", "?"))
        best = 0.0
        for p in predicted_calls:
            p_name = p.get("tool_name", "")
            p_family = TOOL_FAMILY_MAP.get(p_name, ("??", "??"))
            if p_name == g_name:
                best = 1.0
                break
            elif p_family[0] == g_family[0]:
                best = max(best, 0.5)
                all_failures.append("wrong_tool_action")
            else:
                all_failures.append("wrong_tool_family")
        tsa_scores.append(best)
    result.tsa = sum(tsa_scores) / len(tsa_scores) if tsa_scores else 0.0

    # -- EC: Endpoint Correctness --
    ec_scores: list[float] = []
    for g in gold_calls:
        g_ep = g.get("endpoint", "")
        if g_ep is None:
            ec_scores.append(1.0)
            continue
        best = 0.0
        for p in predicted_calls:
            p_ep = p.get("endpoint", "")
            # Normalize: strip leading/trailing slashes
            g_norm = g_ep.strip("/").lower()
            p_norm = p_ep.strip("/").lower() if p_ep else ""
            if g_norm == p_norm:
                best = 1.0
                break
            # Partial: path prefix match
            elif p_norm.startswith(g_norm.split("/")[0]):
                best = max(best, 0.3)
        if best < 1.0 and best > 0:
            all_failures.append("wrong_endpoint")
        elif best == 0:
            all_failures.append("hallucinated_endpoint")
        ec_scores.append(best)
    result.ec = sum(ec_scores) / len(ec_scores) if ec_scores else 0.0

    # -- PA: Parameter Accuracy --
    # Greedy match: for each gold call, find the predicted call with same
    # tool_name (or closest) and score params
    pa_scores: list[float] = []
    pa_failures: list[str] = []
    for g in gold_calls:
        g_name = g.get("tool_name", "")
        g_req = g.get("required_params", {})
        # Find matching predicted call
        best_pa = 0.0
        best_pa_failures: list[str] = []
        for p in predicted_calls:
            if p.get("tool_name", "") == g_name or (
                TOOL_FAMILY_MAP.get(p.get("tool_name", ""), ("?",))[0]
                == TOOL_FAMILY_MAP.get(g_name, ("??",))[0]
            ):
                p_params = p.get("params", {})
                sc, fails = _deep_match_params(p_params, g_req)
                if sc > best_pa:
                    best_pa = sc
                    best_pa_failures = fails
        pa_scores.append(best_pa)
        pa_failures.extend(best_pa_failures)
    result.pa = sum(pa_scores) / len(pa_scores) if pa_scores else 0.0
    all_failures.extend(pa_failures)

    # -- TAS: Time Alignment Score --
    tas_scores: list[float] = []
    for g in gold_calls:
        tc = g.get("time_constraints", {})
        if not tc:
            tas_scores.append(1.0)
            continue
        g_name = g.get("tool_name", "")
        tolerance = tc.get("tolerance", "exact")
        # Find matching predicted call
        best_tas = 0.0
        for p in predicted_calls:
            if p.get("tool_name", "") != g_name:
                continue
            p_params = p.get("params", {})
            time_fields = [k for k in tc if k not in ("format", "tolerance")]
            if not time_fields:
                best_tas = 1.0
                break
            field_scores = []
            for tf in time_fields:
                exp_val = tc.get(tf)
                pred_val = p_params.get(tf)
                fs = _time_within_tolerance(pred_val, exp_val, tolerance)
                if fs < 1.0:
                    all_failures.append("wrong_time_value")
                field_scores.append(fs)
            avg = sum(field_scores) / len(field_scores) if field_scores else 1.0
            best_tas = max(best_tas, avg)
        tas_scores.append(best_tas)
    result.tas = sum(tas_scores) / len(tas_scores) if tas_scores else 1.0

    # -- COS: Call Order Score --
    # For multi-call cases, check that dependency order is preserved
    if n_gold <= 1:
        result.cos = 1.0
    else:
        # Build mapping of gold tool names to their position
        gold_names = [g.get("tool_name", "") for g in gold_calls]
        pred_names = [p.get("tool_name", "") for p in predicted_calls]
        # Find order of matched gold names in predicted list
        pred_positions: list[int] = []
        for gn in gold_names:
            for i, pn in enumerate(pred_names):
                if pn == gn and i not in pred_positions:
                    pred_positions.append(i)
                    break
        if len(pred_positions) <= 1:
            result.cos = 1.0 if len(pred_positions) == len(gold_names) else 0.0
        else:
            # Count inversions
            inversions = 0
            for i in range(len(pred_positions)):
                for j in range(i + 1, len(pred_positions)):
                    if pred_positions[i] > pred_positions[j]:
                        inversions += 1
            max_inversions = len(pred_positions) * (len(pred_positions) - 1) / 2
            result.cos = 1.0 - (inversions / max_inversions) if max_inversions > 0 else 1.0
            if inversions > 0:
                all_failures.append("wrong_call_order")

    # -- OCP: Over-Calling Penalty --
    # Penalize each extra call beyond what's expected
    if n_pred <= n_gold:
        result.ocp = 1.0
    else:
        extra = n_pred - n_gold
        # Penalty: 0.2 per extra call, floor at 0
        result.ocp = max(0.0, 1.0 - 0.2 * extra)
        all_failures.append("redundant_call")

    # -- FOC: Final Output Completeness --
    if predicted_final_answer is not None:
        has_summary = bool(predicted_final_answer.get("summary"))
        has_assumptions = "assumptions" in predicted_final_answer
        result.foc = 0.5 * int(has_summary) + 0.5 * int(has_assumptions)
    else:
        result.foc = 0.0

    result.failure_modes = list(set(all_failures))
    result.compute_overall()
    return result


# ---------------------------------------------------------------------------
# Aggregate scoring
# ---------------------------------------------------------------------------

def aggregate_results(
    results: list[CaseResult],
) -> dict[str, Any]:
    """Aggregate per-case results into summary statistics."""
    if not results:
        return {}

    n = len(results)
    metrics = ["tsa", "ec", "pa", "tas", "cos", "jv", "ocp", "foc", "overall"]
    summary: dict[str, Any] = {}

    # Overall averages
    for m in metrics:
        vals = [getattr(r, m) for r in results]
        summary[f"mean_{m}"] = sum(vals) / n
        summary[f"min_{m}"] = min(vals)
        summary[f"max_{m}"] = max(vals)

    # By category
    categories = set(r.category for r in results)
    summary["by_category"] = {}
    for cat in sorted(categories):
        cat_results = [r for r in results if r.category == cat]
        cn = len(cat_results)
        cat_summary = {"n": cn}
        for m in metrics:
            vals = [getattr(r, m) for r in cat_results]
            cat_summary[f"mean_{m}"] = sum(vals) / cn
        summary["by_category"][cat] = cat_summary

    # By difficulty
    difficulties = set(r.difficulty for r in results)
    summary["by_difficulty"] = {}
    for diff in sorted(difficulties):
        diff_results = [r for r in results if r.difficulty == diff]
        dn = len(diff_results)
        diff_summary = {"n": dn}
        for m in metrics:
            vals = [getattr(r, m) for r in diff_results]
            diff_summary[f"mean_{m}"] = sum(vals) / dn
        summary["by_difficulty"][diff] = diff_summary

    # Failure mode distribution
    failure_counts: dict[str, int] = {}
    for r in results:
        for fm in r.failure_modes:
            failure_counts[fm] = failure_counts.get(fm, 0) + 1
    summary["failure_modes"] = dict(
        sorted(failure_counts.items(), key=lambda x: -x[1])
    )

    return summary
