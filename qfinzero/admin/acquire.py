"""Raw acquisition — trigger the external download scripts with streamed logs.

"Own it end to end": the Console can kick off the vendor downloads that populate
the shared RAW roots, not just the convert step. News/econ/earnings still come
from ``scripts/news_data.sh``; this module is the thin, safe, streamable bridge
the job runner and CLI call. The ``databento`` and ``tiingo`` targets are pure
Python (:mod:`~qfinzero.admin.databento_dl`, :mod:`~qfinzero.admin.tiingo_dl`);
massive flat files are fetched by the data utility (:mod:`~qfinzero.admin.massive_dl`).

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
    python: bool = False   # True = handled in-process (no script)


TARGETS: dict[str, AcquireTarget] = {
    "news": AcquireTarget(
        id="news", label="News / econ / earnings (ESP sources)",
        script="news_data.sh", base_args=["update"],
        writes_to="MongoDB ticker_news + ESP SQLite (runs on the news host)",
        supports_prod=False,
    ),
    "databento": AcquireTarget(
        id="databento", label="Databento historical API (US stocks / OPRA options)",
        script="", base_args=[],
        writes_to="$RAW_DATABENTO_DIR/<dataset>/<schema>/<symbol>/ (DBN, read in place)",
        needs=("databento.api_key",), supports_prod=False, python=True,
    ),
    "tiingo": AcquireTarget(
        id="tiingo", label="Tiingo BOATS overnight (Blue Ocean minute bars / top of book)",
        script="", base_args=[],
        writes_to="$RAW_TIINGO_DIR/boats/{prices/<YYYY-MM>/<TICKER>,quotes/<date>/<HHMM>}.json.gz",
        supports_prod=False, python=True,
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
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Trigger one acquisition target's download (dry-run by default).

    ``params`` carries the request for in-process targets (``databento``:
    dataset, schema, symbols, stype_in, start, end, max_cost, out_dir).
    """
    t = TARGETS.get(target_id)
    if t is None:
        return {"ok": False, "error": f"unknown acquire target {target_id!r}",
                "targets": sorted(TARGETS)}

    cfg = config_store.load()
    missing = [n for n in t.needs if not _dig(cfg, n)]
    if missing:
        return {"ok": False, "error": f"missing config: {', '.join(missing)}", "target": t.id}

    if t.python and t.id == "tiingo":
        return _acquire_tiingo(params or {}, dry_run=dry_run, on_line=on_line)
    if t.python:
        return _acquire_databento(cfg, params or {}, dry_run=dry_run, on_line=on_line)

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


def _acquire_tiingo(params: dict[str, Any], *, dry_run: bool, on_line: OnLine | None,
                    on_progress=None, should_stop=None) -> dict[str, Any]:
    from . import tiingo_dl
    key = tiingo_dl.api_key()
    if not key:
        return {"ok": False, "error": "no Tiingo key (Data setup -> Vendor keys -> Tiingo, product boats)",
                "target": "tiingo"}
    syms = params.get("symbols")
    syms = [s for s in str(syms).split(",") if s.strip()] if syms else None
    if params.get("kind") == "quotes":
        if dry_run:
            return {"ok": True, "dry_run": True, "target": "tiingo",
                    "note": "records /boats once a minute while the 20:00-04:00 ET session runs"}
        res = tiingo_dl.record_quotes(key=key, minutes=params.get("minutes"), on_line=on_line,
                                      should_stop=should_stop)
    else:
        if dry_run:
            client = tiingo_dl.Client(key)
            n = len(syms) if syms else len(tiingo_dl.universe(client))
            return {"ok": True, "dry_run": True, "target": "tiingo", "tickers": n,
                    "note": "one request per ticker and month; Tiingo bills by plan, not per request"}
        res = tiingo_dl.download_prices(key=key, start=params.get("start"), end=params.get("end"),
                                        tickers=syms, on_line=on_line, on_progress=on_progress,
                                        should_stop=should_stop)
    res["target"] = "tiingo"
    return res


def _acquire_databento(cfg: dict, params: dict[str, Any], *, dry_run: bool,
                       on_line: OnLine | None) -> dict[str, Any]:
    from . import databento_dl
    root = Path(params.get("out_dir") or (cfg.get("dirs", {}) or {}).get("raw_databento")
                or "/data/databento").expanduser()
    res = databento_dl.download(
        params, api_key=_dig(cfg, "databento.api_key") or "", root=root,
        dry_run=dry_run, on_line=on_line)
    res["target"] = "databento"
    res["dry_run"] = dry_run
    return res
