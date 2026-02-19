#!/usr/bin/env python3
"""
QFinZero Tool Calling Evaluation Runner
========================================

Usage:
    python runner.py \
        --benchmark benchmark.jsonl \
        --model-config models.yaml \
        --qfinzero-base-url http://127.0.0.1 \
        --mode dry-run \
        --max-workers 4 \
        --seed 42

Modes:
    dry-run : Compare model output to gold standard only (no HTTP calls).
    live    : Execute tool calls against running QFinZero services.

Outputs saved to: ./eval_outputs/<run_id>/
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from metrics import (
    CaseResult,
    aggregate_results,
    score_case,
    METRIC_WEIGHTS,
    CATEGORY_WEIGHTS,
)
from schema import (
    SYSTEM_PROMPT,
    extract_final_answer,
    extract_tool_calls,
    parse_model_output,
    validate_schema,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("eval_runner")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_TIMEOUT = 60  # seconds per model call
DEFAULT_MAX_WORKERS = 4
SERVICE_PORTS = {"UPQ": 19350, "NPP": 19330, "PMB": 19320}


# ---------------------------------------------------------------------------
# Model config loader
# ---------------------------------------------------------------------------
def load_model_configs(path: str) -> list[dict[str, Any]]:
    """
    Load model endpoint configs from YAML.

    Expected format:
    models:
      - model_name: gpt-4o
        base_url: https://api.openai.com/v1
        api_key: sk-...
        provider_type: openai_compatible
      - model_name: local-llama
        base_url: http://localhost:8000/v1
        api_key: null
        provider_type: vllm_openai_compatible
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    models = data.get("models", [])
    if not models:
        raise ValueError(f"No models found in {path}")
    for m in models:
        if "model_name" not in m or "base_url" not in m:
            raise ValueError(f"Each model needs model_name and base_url: {m}")
        m.setdefault("api_key", None)
        m.setdefault("provider_type", "openai_compatible")
    return models


# ---------------------------------------------------------------------------
# Benchmark loader
# ---------------------------------------------------------------------------
def load_benchmark(path: str) -> list[dict[str, Any]]:
    """Load benchmark JSONL file."""
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
# Model caller
# ---------------------------------------------------------------------------
def call_model(
    client: httpx.Client,
    model_cfg: dict[str, Any],
    user_message: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[str, float]:
    """
    Call a model endpoint using OpenAI-compatible chat completions API.

    Returns (raw_response_text, latency_seconds).
    """
    base_url = model_cfg["base_url"].rstrip("/")
    url = f"{base_url}/chat/completions"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if model_cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {model_cfg['api_key']}"

    payload = {
        "model": model_cfg["model_name"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.0,
        "max_tokens": 2048,
    }

    # For vLLM, add guided decoding hint if supported
    if model_cfg.get("provider_type") == "vllm_openai_compatible":
        payload["extra_body"] = {
            "guided_json": {
                "type": "object",
                "required": ["tool_plan", "final_answer"],
            }
        }

    t0 = time.monotonic()
    resp = client.post(url, json=payload, headers=headers, timeout=timeout)
    latency = time.monotonic() - t0

    resp.raise_for_status()
    data = resp.json()

    # Extract content from OpenAI-compatible response
    content = data["choices"][0]["message"]["content"]
    return content, latency


# ---------------------------------------------------------------------------
# Live executor (calls actual QFinZero APIs)
# ---------------------------------------------------------------------------
def execute_tool_call_live(
    client: httpx.Client,
    base_url: str,
    tool_call: dict[str, Any],
) -> dict[str, Any]:
    """Execute a single tool call against live QFinZero services."""
    tool_name = tool_call.get("tool_name", "")
    method = tool_call.get("method", "GET").upper()
    endpoint = tool_call.get("endpoint", "")
    params = tool_call.get("params", {})

    # Determine service port
    family = tool_name.split(".")[0] if "." in tool_name else tool_name
    port = SERVICE_PORTS.get(family)
    if port is None:
        return {"error": f"Unknown tool family: {family}", "status": -1}

    url = f"{base_url}:{port}{endpoint}"

    try:
        if method == "GET":
            resp = client.get(url, params=params, timeout=30)
        else:
            resp = client.post(url, json=params, timeout=30)
        return {
            "status": resp.status_code,
            "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
        }
    except Exception as e:
        return {"error": str(e), "status": -1}


# ---------------------------------------------------------------------------
# Evaluate single case
# ---------------------------------------------------------------------------
def evaluate_case(
    case: dict[str, Any],
    model_cfg: dict[str, Any],
    http_client: httpx.Client,
    mode: str,
    qfinzero_base_url: str,
) -> dict[str, Any]:
    """
    Run a single benchmark case against a model and score it.

    Returns dict with case_id, model_name, raw output, parsed result,
    scores, and any errors.
    """
    case_id = case["id"]
    category = case["category"]
    difficulty = case["difficulty"]
    instruction = case["natural_language_instruction"]
    gold_calls = case["expected_tool_calls"]

    record: dict[str, Any] = {
        "case_id": case_id,
        "model_name": model_cfg["model_name"],
        "category": category,
        "difficulty": difficulty,
        "instruction": instruction,
        "raw_output": "",
        "parse_error": "",
        "schema_violations": [],
        "latency_s": 0.0,
        "live_results": [],
    }

    # Call model
    try:
        raw, latency = call_model(http_client, model_cfg, instruction)
        record["raw_output"] = raw
        record["latency_s"] = round(latency, 3)
    except Exception as e:
        log.error(f"[{case_id}] Model call failed: {e}")
        record["parse_error"] = f"Model call failed: {e}"
        # Return zero-score result
        result = CaseResult(
            case_id=case_id, category=category, difficulty=difficulty
        )
        result.jv = 0.0
        result.compute_overall()
        record["scores"] = asdict(result)
        return record

    # Parse output
    parsed, json_valid, parse_err = parse_model_output(raw)
    record["parse_error"] = parse_err

    if parsed is None:
        log.warning(f"[{case_id}] Parse failed: {parse_err}")
        result = CaseResult(
            case_id=case_id, category=category, difficulty=difficulty
        )
        result.jv = 0.0
        result.failure_modes = ["invalid_json"]
        result.compute_overall()
        record["scores"] = asdict(result)
        return record

    # Validate schema
    violations = validate_schema(parsed)
    record["schema_violations"] = violations
    if violations:
        json_valid = False

    # Extract predictions
    predicted_calls = extract_tool_calls(parsed)
    predicted_final = extract_final_answer(parsed)

    # Score
    result = score_case(gold_calls, predicted_calls, predicted_final, json_valid)
    result.case_id = case_id
    result.category = category
    result.difficulty = difficulty
    record["scores"] = asdict(result)

    # Live execution (optional)
    if mode == "live" and predicted_calls:
        live_results = []
        for tc in predicted_calls:
            lr = execute_tool_call_live(http_client, qfinzero_base_url, tc)
            live_results.append(lr)
        record["live_results"] = live_results

    return record


# ---------------------------------------------------------------------------
# CSV / Markdown output
# ---------------------------------------------------------------------------
METRIC_COLS = ["tsa", "ec", "pa", "tas", "cos", "jv", "ocp", "foc", "overall"]


def write_per_model_csv(records: list[dict], path: Path) -> None:
    """Write per-case results CSV for a single model."""
    fieldnames = [
        "case_id", "category", "difficulty",
        *METRIC_COLS,
        "failure_modes", "latency_s", "parse_error",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            scores = rec.get("scores", {})
            row = {
                "case_id": rec["case_id"],
                "category": rec["category"],
                "difficulty": rec["difficulty"],
                "latency_s": rec["latency_s"],
                "parse_error": rec["parse_error"],
                "failure_modes": "; ".join(scores.get("failure_modes", [])),
            }
            for m in METRIC_COLS:
                row[m] = round(scores.get(m, 0.0), 4)
            writer.writerow(row)


def write_summary_csv(
    all_model_results: dict[str, list[dict]],
    path: Path,
) -> None:
    """Write aggregated summary CSV across all models."""
    fieldnames = ["model_name", *[f"mean_{m}" for m in METRIC_COLS], "n_cases"]
    rows = []
    for model_name, records in all_model_results.items():
        case_results = []
        for rec in records:
            s = rec.get("scores", {})
            cr = CaseResult(
                case_id=s.get("case_id", ""),
                category=s.get("category", ""),
                difficulty=s.get("difficulty", ""),
            )
            for m in METRIC_COLS:
                setattr(cr, m, s.get(m, 0.0))
            case_results.append(cr)
        agg = aggregate_results(case_results)
        row = {"model_name": model_name, "n_cases": len(records)}
        for m in METRIC_COLS:
            row[f"mean_{m}"] = round(agg.get(f"mean_{m}", 0.0), 4)
        rows.append(row)

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary_markdown(
    all_model_results: dict[str, list[dict]],
    path: Path,
) -> None:
    """Write aggregated summary as markdown table."""
    lines: list[str] = []
    lines.append("# QFinZero Tool Calling Evaluation — Summary\n")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")

    # ---- Table 1: Overall scores ----
    lines.append("## Overall Scores\n")
    header = "| Model | TSA | EC | PA | TAS | COS | JV | OCP | FOC | **Overall** | N |"
    sep = "|---|---|---|---|---|---|---|---|---|---|---|"
    lines.append(header)
    lines.append(sep)

    for model_name, records in all_model_results.items():
        case_results = _records_to_case_results(records)
        agg = aggregate_results(case_results)
        vals = [f"{agg.get(f'mean_{m}', 0)*100:.1f}" for m in METRIC_COLS[:-1]]
        overall = f"**{agg.get('mean_overall', 0):.1f}**"
        lines.append(f"| {model_name} | {' | '.join(vals)} | {overall} | {len(records)} |")

    lines.append("")

    # ---- Table 2: By category ----
    lines.append("## By Category\n")
    for model_name, records in all_model_results.items():
        lines.append(f"### {model_name}\n")
        case_results = _records_to_case_results(records)
        agg = aggregate_results(case_results)
        by_cat = agg.get("by_category", {})

        header2 = "| Category | TSA | PA | TAS | Overall | N |"
        sep2 = "|---|---|---|---|---|---|"
        lines.append(header2)
        lines.append(sep2)
        for cat, cat_data in sorted(by_cat.items()):
            row_vals = [
                f"{cat_data.get('mean_tsa', 0)*100:.1f}",
                f"{cat_data.get('mean_pa', 0)*100:.1f}",
                f"{cat_data.get('mean_tas', 0)*100:.1f}",
                f"{cat_data.get('mean_overall', 0):.1f}",
                str(cat_data.get("n", 0)),
            ]
            lines.append(f"| {cat} | {' | '.join(row_vals)} |")
        lines.append("")

    # ---- Table 3: Failure modes ----
    lines.append("## Failure Mode Distribution\n")
    for model_name, records in all_model_results.items():
        lines.append(f"### {model_name}\n")
        case_results = _records_to_case_results(records)
        agg = aggregate_results(case_results)
        fm = agg.get("failure_modes", {})

        lines.append("| Failure Mode | Count |")
        lines.append("|---|---|")
        for mode, count in sorted(fm.items(), key=lambda x: -x[1]):
            lines.append(f"| {mode} | {count} |")
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))


def _records_to_case_results(records: list[dict]) -> list[CaseResult]:
    """Convert record dicts back to CaseResult objects."""
    results = []
    for rec in records:
        s = rec.get("scores", {})
        cr = CaseResult(
            case_id=s.get("case_id", ""),
            category=s.get("category", ""),
            difficulty=s.get("difficulty", ""),
        )
        for m in METRIC_COLS:
            setattr(cr, m, s.get(m, 0.0))
        cr.failure_modes = s.get("failure_modes", [])
        results.append(cr)
    return results


# ---------------------------------------------------------------------------
# Error log
# ---------------------------------------------------------------------------
def write_error_log(
    all_model_results: dict[str, list[dict]],
    path: Path,
) -> None:
    """Write categorized error log."""
    with open(path, "w") as f:
        for model_name, records in all_model_results.items():
            f.write(f"=== {model_name} ===\n\n")
            for rec in records:
                scores = rec.get("scores", {})
                failures = scores.get("failure_modes", [])
                if failures or rec.get("parse_error"):
                    f.write(f"Case: {rec['case_id']}\n")
                    f.write(f"  Category: {rec['category']}\n")
                    f.write(f"  Instruction: {rec['instruction'][:120]}...\n")
                    if rec.get("parse_error"):
                        f.write(f"  Parse Error: {rec['parse_error']}\n")
                    if failures:
                        f.write(f"  Failures: {', '.join(failures)}\n")
                    f.write(f"  Overall Score: {scores.get('overall', 0):.1f}\n")
                    f.write("\n")
            f.write("\n")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------
def run_evaluation(
    benchmark_path: str,
    model_config_path: str,
    qfinzero_base_url: str,
    mode: str,
    max_workers: int,
    seed: int,
    output_dir: str | None = None,
) -> dict[str, list[dict]]:
    """
    Run the full evaluation pipeline.

    Parameters
    ----------
    benchmark_path : path to benchmark.jsonl
    model_config_path : path to models.yaml
    qfinzero_base_url : e.g. "http://127.0.0.1"
    mode : "dry-run" or "live"
    max_workers : thread pool size
    seed : random seed for deterministic ordering
    output_dir : override output directory (default: auto-generated)

    Returns
    -------
    dict mapping model_name -> list of record dicts
    """
    # Load inputs
    cases = load_benchmark(benchmark_path)
    models = load_model_configs(model_config_path)

    # Deterministic ordering
    random.seed(seed)
    random.shuffle(cases)

    # Create output directory
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if output_dir is None:
        output_dir = str(Path("eval_outputs") / run_id)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    log.info(f"Output directory: {out_path}")

    # Save run metadata
    meta = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "benchmark": benchmark_path,
        "n_cases": len(cases),
        "models": [m["model_name"] for m in models],
        "mode": mode,
        "seed": seed,
        "max_workers": max_workers,
    }
    with open(out_path / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    all_results: dict[str, list[dict]] = {}

    for model_cfg in models:
        model_name = model_cfg["model_name"]
        log.info(f"--- Evaluating model: {model_name} ---")

        records: list[dict] = []

        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            if max_workers <= 1:
                # Sequential
                for case in cases:
                    rec = evaluate_case(
                        case, model_cfg, client, mode, qfinzero_base_url
                    )
                    records.append(rec)
                    log.info(
                        f"  [{rec['case_id']}] overall={rec['scores'].get('overall', 0):.1f} "
                        f"latency={rec['latency_s']}s"
                    )
            else:
                # Concurrent
                futures = {}
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    for case in cases:
                        fut = pool.submit(
                            evaluate_case,
                            case, model_cfg, client, mode, qfinzero_base_url,
                        )
                        futures[fut] = case["id"]

                    for fut in as_completed(futures):
                        case_id = futures[fut]
                        try:
                            rec = fut.result()
                            records.append(rec)
                            log.info(
                                f"  [{case_id}] overall={rec['scores'].get('overall', 0):.1f} "
                                f"latency={rec['latency_s']}s"
                            )
                        except Exception as e:
                            log.error(f"  [{case_id}] Exception: {e}")
                            records.append({
                                "case_id": case_id,
                                "model_name": model_name,
                                "category": "",
                                "difficulty": "",
                                "instruction": "",
                                "raw_output": "",
                                "parse_error": str(e),
                                "schema_violations": [],
                                "latency_s": 0.0,
                                "live_results": [],
                                "scores": asdict(CaseResult(
                                    case_id=case_id, category="", difficulty="",
                                )),
                            })

        # Sort records by case_id for reproducibility
        records.sort(key=lambda r: r["case_id"])
        all_results[model_name] = records

        # Write per-model CSV
        csv_path = out_path / f"{model_name}_results.csv"
        write_per_model_csv(records, csv_path)
        log.info(f"  Wrote {csv_path}")

        # Write raw outputs
        raw_path = out_path / f"{model_name}_raw.jsonl"
        with open(raw_path, "w") as f:
            for rec in records:
                f.write(json.dumps(rec, default=str) + "\n")

    # Write aggregated outputs
    write_summary_csv(all_results, out_path / "summary.csv")
    write_summary_markdown(all_results, out_path / "summary.md")
    write_error_log(all_results, out_path / "errors.log")

    log.info(f"Evaluation complete. Results in {out_path}")
    return all_results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="QFinZero Tool Calling Evaluation Runner"
    )
    parser.add_argument(
        "--benchmark", required=True,
        help="Path to benchmark JSONL file",
    )
    parser.add_argument(
        "--model-config", required=True,
        help="Path to models.yaml config file",
    )
    parser.add_argument(
        "--qfinzero-base-url", default="http://127.0.0.1",
        help="Base URL for QFinZero services (default: http://127.0.0.1)",
    )
    parser.add_argument(
        "--mode", choices=["dry-run", "live"], default="dry-run",
        help="Execution mode (default: dry-run)",
    )
    parser.add_argument(
        "--max-workers", type=int, default=DEFAULT_MAX_WORKERS,
        help=f"Max concurrent workers (default: {DEFAULT_MAX_WORKERS})",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for deterministic ordering (default: 42)",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Override output directory (default: ./eval_outputs/<run_id>/)",
    )
    args = parser.parse_args()

    run_evaluation(
        benchmark_path=args.benchmark,
        model_config_path=args.model_config,
        qfinzero_base_url=args.qfinzero_base_url,
        mode=args.mode,
        max_workers=args.max_workers,
        seed=args.seed,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
