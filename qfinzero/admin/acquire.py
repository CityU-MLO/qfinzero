"""Raw acquisition — trigger the external download scripts with streamed logs.

"Own it end to end": the Console can kick off the vendor downloads that populate
the shared RAW roots, not just the convert step. Acquisition itself still lives in
the battle-tested shell scripts (``scripts/upq_flatfiles.sh`` for MASSIVE flat-files,
``scripts/news_data.sh`` for news/econ/earnings); this module is the thin, safe,
streamable bridge the job runner and CLI call.

Design choices that keep this honest:

* **Dry-run by default.** A real download only runs with ``dry_run=False``; a prod
  write only with ``prod=True``. The wizard's "test the pipe" path is harmless.
* **We report where raw lands.** The scripts own their write targets (some are
  host-specific, e.g. ``/home/qlib/*`` in prod), so each target advertises
  ``writes_to`` rather than pretending the console controls it.
* **Credentials come from the config store.** :func:`~qfinzero.admin.config_store.apply_to_env`
  is applied before launch so ``POLYGON_S3_*`` etc. are present for the script.

:func:`run_stream` is the reusable primitive (also used to stream ``qfz-data``
convert jobs); it never raises on a non-zero exit — the caller inspects ``ok``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from qfinzero.env import REPO_ROOT
from . import config_store

OnLine = Callable[[str], None]


@dataclass(frozen=True)
class AcquireTarget:
    id: str
    label: str
    script: str            # filename under scripts/
    base_args: list[str]   # e.g. ["update"]
    writes_to: str         # human note of where the raw lands
    needs: tuple[str, ...] = ()   # config paths that must be set ("massive.s3_access_key_id")
    supports_prod: bool = True
    supports_dry_run: bool = True


TARGETS: dict[str, AcquireTarget] = {
    "us_prices": AcquireTarget(
        id="us_prices", label="MASSIVE flat-files (US stocks/options/rates)",
        script="upq_flatfiles.sh", base_args=["update"],
        writes_to="test: /tmp/upq_flatfiles_test · prod: /home/qlib/upq_* (host-specific)",
        needs=("massive.s3_access_key_id", "massive.s3_secret_access_key"),
    ),
    "news": AcquireTarget(
        id="news", label="News / econ / earnings (ESP sources)",
        script="news_data.sh", base_args=["update"],
        writes_to="MongoDB ticker_news + ESP SQLite (runs on the news host)",
        supports_prod=False,
    ),
}


def targets() -> list[dict[str, Any]]:
    """Registry as plain dicts (for the CLI/API), annotated with readiness."""
    out = []
    cfg = config_store.load()
    for t in TARGETS.values():
        missing = [n for n in t.needs if not _dig(cfg, n)]
        out.append({
            "id": t.id, "label": t.label, "script": t.script,
            "writes_to": t.writes_to, "supports_prod": t.supports_prod,
            "ready": not missing, "missing": missing,
        })
    return out


def _dig(cfg: dict, dotted: str) -> Any:
    cur: Any = cfg
    for k in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def run_stream(
    cmd: list[str],
    *,
    on_line: OnLine | None = None,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
    timeout: float | None = None,
    tail: int = 400,
) -> dict[str, Any]:
    """Run ``cmd``, streaming each stdout/stderr line to ``on_line``.

    Returns ``{cmd, returncode, ok, lines}`` where ``lines`` is the last ``tail``
    lines captured. Never raises on non-zero exit; a spawn failure (missing binary)
    is reported as ``returncode=127`` with the error in ``lines``.
    """
    import os
    full_env = {**os.environ, **(env or {})}
    captured: list[str] = []

    def emit(line: str) -> None:
        line = line.rstrip("\n")
        captured.append(line)
        if len(captured) > tail:
            del captured[0]
        if on_line is not None:
            on_line(line)

    try:
        proc = subprocess.Popen(
            cmd, cwd=str(cwd) if cwd else None, env=full_env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
    except (FileNotFoundError, PermissionError) as e:
        emit(f"[error] cannot launch {cmd[0]}: {e}")
        return {"cmd": cmd, "returncode": 127, "ok": False, "lines": captured}

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            emit(line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        emit(f"[error] timed out after {timeout}s")
        return {"cmd": cmd, "returncode": 124, "ok": False, "lines": captured}

    return {"cmd": cmd, "returncode": proc.returncode, "ok": proc.returncode == 0, "lines": captured}


def acquire(
    target_id: str,
    *,
    dry_run: bool = True,
    prod: bool = False,
    extra_args: list[str] | None = None,
    on_line: OnLine | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Trigger one acquisition target's download script (dry-run by default)."""
    t = TARGETS.get(target_id)
    if t is None:
        return {"ok": False, "error": f"unknown acquire target {target_id!r}",
                "targets": sorted(TARGETS)}

    cfg = config_store.load()
    missing = [n for n in t.needs if not _dig(cfg, n)]
    if missing:
        return {"ok": False, "error": f"missing config: {', '.join(missing)}", "target": t.id}

    script = REPO_ROOT / "scripts" / t.script
    if not script.exists():
        return {"ok": False, "error": f"script not found: {script}", "target": t.id}

    args = list(t.base_args)
    if prod and t.supports_prod:
        args.append("--prod")
    if dry_run and t.supports_dry_run:
        args.append("--dry-run")
    args.extend(extra_args or [])
    cmd = ["bash", str(script), *args]

    config_store.apply_to_env(cfg)  # ensure POLYGON_S3_* etc. are present
    if on_line:
        on_line(f"[acquire] {t.label} :: {' '.join(cmd)}")
    res = run_stream(cmd, on_line=on_line, timeout=timeout)
    res["target"] = t.id
    res["dry_run"] = dry_run
    res["prod"] = prod
    return res
