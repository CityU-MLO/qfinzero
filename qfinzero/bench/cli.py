"""``qfz-bench`` — build, run and score the agent benchmark."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .score import markdown_table, summarize
from .tasks import build_tasks, load_tasks, write_tasks


def _select(tasks, args):
    if args.category:
        cats = set(args.category.split(","))
        tasks = [t for t in tasks if t.category in cats]
    if args.ids:
        ids = set(args.ids.split(","))
        tasks = [t for t in tasks if t.id in ids]
    return tasks[: args.limit] if args.limit else tasks


def _progress(r):
    mark = "ok " if r.get("correct") else "ERR" if r.get("error") else "-- "
    print(f"{mark} {r['id']:<16} {r.get('seconds', 0):>6}s {r.get('error', '')}", file=sys.stderr)


def _write_results(results, out):
    summary = summarize(results)
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r, default=str) + "\n" for r in results))
        p.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2))
    print(markdown_table(summary))
    return 0 if results else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qfz-bench", description="QFinZero agent benchmark")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="generate tasks from a sample root")
    b.add_argument("--data", required=True, help="sample root (output of qfz-sample generate)")
    b.add_argument("--out", required=True)

    def common(p):
        p.add_argument("--tasks", help="task file (default: the one shipped with qfinzero)")
        p.add_argument("--category", help="comma-separated categories")
        p.add_argument("--ids", help="comma-separated task ids")
        p.add_argument("--limit", type=int)
        p.add_argument("--out", help="results JSONL (a .summary.json is written next to it)")

    o = sub.add_parser("oracle", help="solve every task through the service APIs")
    common(o)
    o.add_argument("--hub", help="hub URL, e.g. http://127.0.0.1:19777")
    o.add_argument("--api-key", default=os.environ.get("QFZ_API_KEY"))
    o.add_argument("--upq"), o.add_argument("--esp"), o.add_argument("--pmb")

    r = sub.add_parser("run", help="run an LLM agent through the hub's MCP endpoint")
    common(r)
    r.add_argument("--hub", required=True)
    r.add_argument("--api-key", default=os.environ.get("QFZ_API_KEY"), help="QFinZero API key (researcher)")
    r.add_argument("--model", required=True)
    r.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    r.add_argument("--llm-key", default=os.environ.get("OPENAI_API_KEY"))
    r.add_argument("--tools", default="upq_,esp_,pmb_,research_",
                   help="tool-name prefixes offered to the model")
    r.add_argument("--max-turns", type=int, default=30)
    r.add_argument("--temperature", type=float, default=0.0)

    s = sub.add_parser("score", help="summarize a results file")
    s.add_argument("results")

    args = ap.parse_args(argv)
    if args.cmd == "build":
        tasks = build_tasks(args.data)
        write_tasks(tasks, args.out)
        print(f"{len(tasks)} tasks -> {args.out}")
        return 0
    if args.cmd == "score":
        rows = [json.loads(x) for x in Path(args.results).read_text().splitlines() if x.strip()]
        print(markdown_table(summarize(rows)))
        return 0

    tasks = _select(load_tasks(args.tasks), args)
    if args.cmd == "oracle":
        from .oracle import Endpoints, run_oracle
        if args.hub:
            ep = Endpoints.hub(args.hub, args.api_key)
        elif args.upq and args.esp and args.pmb:
            ep = Endpoints(args.upq, args.esp, args.pmb, args.api_key)
        else:
            ap.error("oracle needs --hub or all of --upq/--esp/--pmb")
        return _write_results(run_oracle(tasks, ep, _progress), args.out)

    from .agent import LLM, run_agent
    llm = LLM(args.model, args.base_url, args.llm_key, temperature=args.temperature)
    results = run_agent(tasks, llm, args.hub, args.api_key, allow=args.tools.split(","),
                        max_turns=args.max_turns, progress=_progress)
    return _write_results(results, args.out)


if __name__ == "__main__":
    sys.exit(main())
