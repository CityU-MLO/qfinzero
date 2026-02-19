#!/usr/bin/env python3
"""
QFinZero Unified Evaluation Runner
====================================
Runs both evaluation suites (tool-calling and multi-step planning) against
every model defined in a single models.yaml.

Usage:
    # Run both suites in dry-run mode (default)
    python eval/run_eval.py

    # Live mode, specific model config
    python eval/run_eval.py --mode live --models eval/models.yaml

    # Only one suite
    python eval/run_eval.py --suite calling
    python eval/run_eval.py --suite planning

    # Custom output root
    python eval/run_eval.py --output-root eval/runs/experiment-1

All outputs land under:
    <output-root>/<timestamp>/calling/
    <output-root>/<timestamp>/planning/
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — all relative to this file's parent (the repo root)
# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).resolve().parent.parent   # …/qfinzero/
EVAL_ROOT   = Path(__file__).resolve().parent           # …/qfinzero/eval/

CALLING_RUNNER  = EVAL_ROOT / "calling"  / "runner.py"
CALLING_BENCH   = EVAL_ROOT / "calling"  / "benchmark.jsonl"

PLANNING_RUNNER = EVAL_ROOT / "planning" / "runner" / "run_multistep.py"
PLANNING_BENCH  = EVAL_ROOT / "planning" / "benchmarks" / "qfinzero_multistep_10.jsonl"
PLANNING_CFG    = EVAL_ROOT / "planning" / "config.yaml"

DEFAULT_MODELS  = EVAL_ROOT / "models.yaml"
DEFAULT_OUT_ROOT = EVAL_ROOT / "runs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _banner(msg: str) -> None:
    width = max(len(msg) + 4, 60)
    print("\n" + "=" * width)
    print(f"  {msg}")
    print("=" * width)


def _run(cmd: list[str], cwd: Path, label: str) -> int:
    """Run a subprocess, stream its output, and return the exit code."""
    print(f"\n[{label}] $ {' '.join(str(c) for c in cmd)}\n")
    t0 = time.monotonic()
    result = subprocess.run(cmd, cwd=str(cwd))
    elapsed = time.monotonic() - t0
    status = "OK" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
    print(f"\n[{label}] finished in {elapsed:.1f}s — {status}\n")
    return result.returncode


def _read_summary(out_dir: Path, suite: str) -> dict | None:
    """
    Try to find and return the summary JSON produced by a runner.
    Both runners write a *_summary.json (calling) or summary.json (planning).
    """
    candidates = list(out_dir.rglob("*summary*.json"))
    if not candidates:
        return None
    # Pick the most recently modified one
    path = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Suite runners
# ---------------------------------------------------------------------------
def run_calling(
    models_path: Path,
    out_dir: Path,
    mode: str,
    max_workers: int,
    seed: int,
    call_latency_s: float = 0.0,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(CALLING_RUNNER),
        "--benchmark",      str(CALLING_BENCH),
        "--model-config",   str(models_path),
        "--mode",           mode,
        "--max-workers",    str(max_workers),
        "--seed",           str(seed),
        "--output-dir",     str(out_dir),
        "--call-latency",   str(call_latency_s),
    ]
    # calling/runner.py imports from the same directory (metrics, schema)
    return _run(cmd, cwd=CALLING_RUNNER.parent, label="calling")


def run_planning(
    models_path: Path,
    out_dir: Path,
    mode: str,
    call_latency_s: float = 0.0,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(PLANNING_RUNNER),
        "--benchmark",    str(PLANNING_BENCH),
        "--model-config", str(models_path),
        "--config",       str(PLANNING_CFG),
        "--mode",         mode,
        "--output-dir",   str(out_dir),
        "--call-latency", str(call_latency_s),
    ]
    # run_multistep.py imports eval_multistep via sys.path insertion
    return _run(cmd, cwd=PLANNING_RUNNER.parent, label="planning")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="QFinZero unified eval runner — calling + planning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--models", default=str(DEFAULT_MODELS),
        metavar="PATH",
        help=f"Path to unified models.yaml (default: {DEFAULT_MODELS.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--mode", choices=["dry-run", "live"], default="dry-run",
        help="Execution mode for both suites (default: dry-run)",
    )
    parser.add_argument(
        "--suite", choices=["calling", "planning", "both"], default="both",
        help="Which eval suite(s) to run (default: both)",
    )
    parser.add_argument(
        "--output-root", default=str(DEFAULT_OUT_ROOT),
        metavar="DIR",
        help=f"Root directory for run outputs (default: {DEFAULT_OUT_ROOT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--max-workers", type=int, default=4,
        help="Parallel workers for the calling suite (default: 4)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for the calling suite (default: 42)",
    )
    parser.add_argument(
        "--call-latency", type=float, default=0.0, metavar="SECONDS",
        help="Seconds to sleep after each LLM call to avoid rate limits. "
             "Applied to both suites. Per-model call_latency_s in models.yaml "
             "takes precedence over this global default (default: 0)",
    )
    args = parser.parse_args()

    models_path  = Path(args.models).resolve()
    output_root  = Path(args.output_root).resolve()
    timestamp    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_root     = output_root / timestamp

    # Validate models file
    if not models_path.exists():
        sys.exit(f"[error] models.yaml not found: {models_path}")

    _banner(f"QFinZero Eval  |  mode={args.mode}  |  suite={args.suite}  |  {timestamp}")
    print(f"  models   : {models_path}")
    print(f"  outputs  : {run_root}")
    if args.call_latency > 0:
        print(f"  latency  : {args.call_latency}s per call (global default)")

    exit_codes: dict[str, int] = {}

    # ── Calling suite ────────────────────────────────────────────────────────
    if args.suite in ("calling", "both"):
        _banner("Suite: tool-calling")
        exit_codes["calling"] = run_calling(
            models_path   = models_path,
            out_dir       = run_root / "calling",
            mode          = args.mode,
            max_workers   = args.max_workers,
            seed          = args.seed,
            call_latency_s= args.call_latency,
        )

    # ── Planning suite ───────────────────────────────────────────────────────
    if args.suite in ("planning", "both"):
        _banner("Suite: multi-step planning")
        exit_codes["planning"] = run_planning(
            models_path   = models_path,
            out_dir       = run_root / "planning",
            mode          = args.mode,
            call_latency_s= args.call_latency,
        )

    # ── Final summary ────────────────────────────────────────────────────────
    _banner("Run complete")
    all_ok = True
    for suite, code in exit_codes.items():
        status = "OK" if code == 0 else f"FAILED (exit {code})"
        print(f"  {suite:<12} {status}")
        if code != 0:
            all_ok = False

    print(f"\n  Results saved to: {run_root}\n")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
