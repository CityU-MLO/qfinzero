"""Markdown export of a thread."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from context import render_output

STATUS_NOTE = {"interrupted": "_Interrupted by the user._", "error": "_The response failed._"}


def _when(ts: float | None) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else ""


def _duration(call: dict) -> str:
    a, b = call.get("started_at"), call.get("ended_at")
    return f" · {(b - a) / 1000:.1f} s" if a and b else ""


def thread_markdown(thread: dict, messages: list[dict], tools: bool = True, tool_chars: int = 4000) -> str:
    title = thread.get("title") or "Conversation"
    lines = [f"# {title}", ""]
    meta = [f"- Exported: {_when(datetime.now(timezone.utc).timestamp())}"]
    if thread.get("model"):
        meta.append(f"- Model: `{thread['model']}`")
    if thread.get("as_of"):
        meta.append(f"- Simulation time: {thread['as_of']}")
    meta.append(f"- Messages: {len(messages)}")
    lines += meta + [""]
    if thread.get("summary"):
        lines += ["> **Compacted context.** Earlier turns were summarised for the model as:", ">"]
        lines += [f"> {ln}" if ln else ">" for ln in thread["summary"].splitlines()] + [""]
    for m in messages:
        if m["role"] == "user":
            lines += ["---", "", f"## You · {_when(m.get('created_at'))}", "", m["content"], ""]
            continue
        model = f" (`{m['model']}`)" if m.get("model") else ""
        lines += [f"## Assistant{model}", ""]
        for step in m.get("steps") or []:
            if tools:
                for c in step.get("tool_calls") or []:
                    lines += [f"<details><summary>Tool <code>{c['tool']}</code> · {c.get('status', '')}"
                              f"{_duration(c)}</summary>", "", "**Input**", "", "```json",
                              json.dumps(c.get("input") or {}, ensure_ascii=False, indent=2), "```", ""]
                    body = c.get("output") if c.get("status") == "done" else c.get("error")
                    if body is not None:
                        text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, indent=2,
                                                                              default=str)
                        lines += ["**Output**", "", "```json", render_output(text, tool_chars), "```", ""]
                    lines += ["</details>", ""]
            if step.get("text"):
                lines += [step["text"], ""]
        if not m.get("steps") and m.get("content"):
            lines += [m["content"], ""]
        if m.get("status") in STATUS_NOTE:
            lines += [STATUS_NOTE[m["status"]] + (f" {m['error']}" if m.get("error") else ""), ""]
    return "\n".join(lines).rstrip() + "\n"
