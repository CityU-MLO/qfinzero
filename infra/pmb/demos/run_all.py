"""
Run all demos in sequence.

This script runs all three demo strategies one after another.
Results are saved in timestamped folders under results/

Usage:
  python demos/run_all.py
"""

import subprocess
import sys


def run_demo(script_name, description):
    print(f"\n{'='*70}")
    print(f"  Running: {description}")
    print(f"  Script: {script_name}")
    print(f"{'='*70}\n")

    parts = script_name.split()
    cmd = [sys.executable, f"demos/{parts[0]}"] + parts[1:]
    result = subprocess.run(cmd, cwd=".")

    if result.returncode != 0:
        print(f"\n❌ {script_name} failed with code {result.returncode}")
        return False

    print(f"\n✓ {script_name} completed successfully\n")
    return True


def main():
    print("\n" + "="*70)
    print("  Paper Money Broker - Demo Suite Runner")
    print("="*70)

    demos = [
        ("daily_buy_close.py", "Daily Buy-at-Close Strategy (AAPL Jan 2025)"),
        ("intraday_5min_signal.py", "Intraday 5-Min Mean Reversion (AAPL)"),
        ("covered_call.py", "Covered Call Strategy (NVDA with Options)"),
        ("overlay_profit_increase.py", "Overlay: Covered Call Profit Increase (AAPL 2024)"),
        ("overlay_hedging.py", "Overlay: Protective Put Hedging (AAPL 2024)"),
        ("overlay_profit_increase_v2.py", "Overlay v2: Covered Call (Paper Spec, QQQ/NVDA/USO)"),
        ("overlay_hedging_v2.py", "Overlay v2: Protective Put (Paper Spec, QQQ/NVDA)"),
        ("overlay_llm_agent.py --ticker QQQ --strategy profit",
         "LLM Agent: Covered Call (QQQ, DeepSeek)"),
        ("overlay_llm_agent.py --ticker QQQ --strategy hedge",
         "LLM Agent: Protective Put (QQQ, DeepSeek)"),
    ]

    success_count = 0
    for script, desc in demos:
        if run_demo(script, desc):
            success_count += 1

    print("\n" + "="*70)
    print(f"  Demo Suite Complete: {success_count}/{len(demos)} succeeded")
    print("="*70)
    print(f"\n  Results saved in: results/")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
