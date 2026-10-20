"""Update cadence — a managed crontab block rendered from the config store.

QFinZero is multi-service with no single always-on Python host, so the robust
"set update frequency" primitive is **cron**, not an in-process daemon. The
operator sets a cron expression per update group in the config store; this module
renders those into a clearly-delimited *managed block* and splices it into the
user's crontab without touching their other entries.

Each group's command defaults to the convert-only orchestrator (``qfz-data
update``); a group may override ``command`` in the config to also run acquisition
(the "own it end to end" path) — e.g. the news group shells the news script.

Everything is best-effort and dry-run-previewable: :func:`render` returns the
block without installing; :func:`apply` writes it; :func:`status` reads back what
is actually installed. No ``crontab`` binary → reported, not raised.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Optional

from qfinzero.env import REPO_ROOT
from . import config_store

MANAGED_BEGIN = "# BEGIN qfz-data (QFinZero data-admin managed) — do not edit"
MANAGED_END = "# END qfz-data (QFinZero data-admin managed)"

# Default command per known group. ``{py}`` = venv python, ``{repo}`` = repo root.
DEFAULT_COMMANDS = {
    "prices": "{py} -m qfinzero.pipeline.cli update --source prices",
    "news": "bash {repo}/scripts/news_data.sh update",
}


def _command_for(group: str, entry: dict) -> str:
    tmpl = entry.get("command") or DEFAULT_COMMANDS.get(group, "{py} -m qfinzero.pipeline.cli update")
    return tmpl.format(py=sys.executable, repo=str(REPO_ROOT))


def _next_run(cron: str) -> Optional[str]:
    """Next fire time (ISO) if ``croniter`` is importable, else ``None``."""
    try:
        from datetime import datetime
        from croniter import croniter
        return croniter(cron, datetime.now()).get_next(datetime).isoformat(timespec="minutes")
    except Exception:  # noqa: BLE001 — optional dep / bad expr → just omit
        return None


def plan() -> list[dict[str, Any]]:
    """Per-group schedule view (enabled/cron/command/next_run)."""
    sched = config_store.schedule()
    log_dir = REPO_ROOT / "logs"
    out = []
    for group, entry in sched.items():
        if not isinstance(entry, dict):
            continue
        cron = str(entry.get("cron") or "").strip()
        cmd = _command_for(group, entry)
        out.append({
            "group": group,
            "enabled": bool(entry.get("enabled")),
            "cron": cron,
            "command": cmd,
            "log": str(log_dir / f"cron-{group}.log"),
            "next_run": _next_run(cron) if (entry.get("enabled") and cron) else None,
        })
    return out


def render() -> str:
    """Render the managed crontab block for all enabled groups (may be empty)."""
    lines = [MANAGED_BEGIN]
    for item in plan():
        if not item["enabled"] or not item["cron"]:
            continue
        lines.append(
            f"{item['cron']} cd {REPO_ROOT} && {item['command']} "
            f">> {item['log']} 2>&1"
        )
    lines.append(MANAGED_END)
    return "\n".join(lines) + "\n"


def current_crontab() -> str:
    """The user's current crontab text ('' if none / no crontab binary)."""
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _strip_managed(text: str) -> list[str]:
    """Return ``text`` lines with any existing managed block removed."""
    out, skip = [], False
    for line in text.splitlines():
        if line.strip() == MANAGED_BEGIN:
            skip = True
            continue
        if line.strip() == MANAGED_END:
            skip = False
            continue
        if not skip:
            out.append(line)
    return out


def _write_crontab(text: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(["crontab", "-"], input=text, capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return False, "crontab binary not available"
    except subprocess.SubprocessError as e:
        return False, str(e)
    return (r.returncode == 0), (r.stderr.strip() or "")


def apply(dry_run: bool = False) -> dict[str, Any]:
    """Splice the managed block into the crontab (preview when ``dry_run``)."""
    block = render()
    has_enabled = any(i["enabled"] and i["cron"] for i in plan())
    kept = _strip_managed(current_crontab())
    # Drop trailing blanks, then append the block (only if something is enabled).
    while kept and not kept[-1].strip():
        kept.pop()
    new_text = "\n".join(kept)
    if has_enabled:
        new_text = (new_text + "\n\n" if new_text else "") + block
    else:
        new_text = new_text + "\n" if new_text else ""

    if dry_run:
        return {"ok": True, "dry_run": True, "installed": has_enabled, "crontab": new_text, "block": block}
    ok, err = _write_crontab(new_text)
    return {"ok": ok, "dry_run": False, "installed": ok and has_enabled,
            "error": err or None, "block": block if has_enabled else ""}


def clear() -> dict[str, Any]:
    """Remove the managed block from the crontab (leave everything else)."""
    kept = _strip_managed(current_crontab())
    while kept and not kept[-1].strip():
        kept.pop()
    ok, err = _write_crontab(("\n".join(kept) + "\n") if kept else "")
    return {"ok": ok, "error": err or None}


def status() -> dict[str, Any]:
    """Schedule plan + whether our block is currently installed."""
    text = current_crontab()
    installed = MANAGED_BEGIN in text
    return {"plan": plan(), "installed": installed, "have_crontab": bool(text) or _has_crontab()}


def _has_crontab() -> bool:
    try:
        subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
