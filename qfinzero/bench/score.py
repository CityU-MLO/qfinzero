"""Answer extraction and scoring."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Optional

from .ops import parse_number

_NULLS = {"null", "none", "unknown", "n/a", "na", "not available", "not yet available",
          "not known", "not yet known", "not released", "not yet released"}
_TRUE = {"true", "yes", "y"}
_FALSE = {"false", "no", "n"}


def extract_answer(text: str) -> tuple[bool, Any]:
    """The value after the last ``ANSWER:`` line of a reply: (found, value).

    JSON is parsed when possible (``ANSWER: 12.5``, ``ANSWER: null``,
    ``ANSWER: "ACME"``); anything else is returned as a stripped string.
    """
    hits = re.findall(r"^\s*\**ANSWER\**\s*[:：]\s*\**\s*(.+?)\s*$", text or "", flags=re.M | re.I)
    if not hits:
        return False, None
    raw = hits[-1].strip().strip("`").strip()
    try:
        return True, json.loads(raw)
    except (ValueError, TypeError):
        return True, raw


def _is_null(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip().lower().rstrip(".") in _NULLS)


def check(kind: str, expected: Any, got: Any, tol: float = 0.0) -> bool:
    if kind == "none":
        return _is_null(got)
    if _is_null(got):
        return False
    if kind in ("number", "integer"):
        x = parse_number(got)
        if x is None:
            return False
        if kind == "integer":
            return abs(x - float(expected)) < 0.5
        return abs(x - float(expected)) <= tol + 1e-9
    if kind == "bool":
        if isinstance(got, bool):
            return got == expected
        s = str(got).strip().lower().rstrip(".")
        return (s in _TRUE and expected is True) or (s in _FALSE and expected is False)
    if kind == "date":
        m = re.search(r"\d{4}-\d{2}-\d{2}", str(got))
        return bool(m) and m.group() == str(expected)[:10]
    if kind == "text":
        norm = lambda s: re.sub(r"\s+", "", str(s)).upper().removeprefix("O:")  # noqa: E731
        return norm(got) == norm(expected)
    raise ValueError(f"unknown answer kind {kind}")


def summarize(results: list[dict]) -> dict:
    """Accuracy overall and per category, plus cost figures when present."""
    cats: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        cats[r["category"]].append(r)

    def agg(rs: list[dict]) -> dict:
        n = len(rs)
        out = {"n": n, "correct": sum(1 for r in rs if r.get("correct")),
               "accuracy": round(sum(1 for r in rs if r.get("correct")) / n, 4) if n else 0.0,
               "errors": sum(1 for r in rs if r.get("error"))}
        for k in ("tool_calls", "prompt_tokens", "completion_tokens", "seconds"):
            vals = [r[k] for r in rs if r.get(k) is not None]
            if vals:
                out[f"mean_{k}"] = round(sum(vals) / len(vals), 2)
        return out

    return {"overall": agg(results), "by_category": {c: agg(rs) for c, rs in sorted(cats.items())}}


def markdown_table(summary: dict, title: Optional[str] = None) -> str:
    lines = [f"### {title}", ""] if title else []
    lines += ["| category | n | accuracy | mean tool calls |", "|---|---:|---:|---:|"]
    rows = list(summary["by_category"].items()) + [("**overall**", summary["overall"])]
    for name, s in rows:
        calls = s.get("mean_tool_calls", "")
        lines.append(f"| {name} | {s['n']} | {s['accuracy'] * 100:.1f}% | {calls} |")
    return "\n".join(lines)
