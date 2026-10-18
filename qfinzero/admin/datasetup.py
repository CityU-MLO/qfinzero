"""Data setup utility: bring Databento and massive data into QFinZero.

Two ways in, one way through:

* **Local files.** :func:`browse` lists the server's file system inside the
  allowed roots; :func:`inspect` describes a selection; :func:`import_local`
  links it into the vendor's *raw library* (the configured raw directory) and
  converts it. massive ``.csv.gz`` flat files are converted to parquet on the
  way in; everything else is linked, never copied.
* **Download.** Databento through :mod:`databento_dl` (cost-quoted, capped) and
  massive flat files through :mod:`massive_dl`; both write into the raw library.

Then the standard incremental conversion (``qfz-data convert``) runs over the
library. Linking keeps every import in the library, so a later import never
makes the converter forget an earlier one, and re-running is cheap.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

from . import config_store

OnLine = Callable[[str], None]
VENDORS = ("databento", "massive")
MAX_ENTRIES = 3000
MAX_DESCRIBE = 400
_DATED = re.compile(r"(\d{4}-\d{2}-\d{2})\.(parquet|csv\.gz)$")


# ── roots and the file browser ────────────────────────────────────────────

def roots() -> list[Path]:
    """Directories the browser may show: ``QFZ_BROWSE_ROOTS`` (``:``-separated),
    else the raw directories, the data root and ``/data``."""
    env = os.environ.get("QFZ_BROWSE_ROOTS", "")
    if env:
        cands = [Path(p) for p in re.split(r"[:,]", env) if p.strip()]
    else:
        d = config_store.dirs()
        cands = [Path(d.get(k, "")) for k in ("raw_databento", "raw_massive", "qfz_data_root") if d.get(k)]
        cands.append(Path("/data"))
    out: list[Path] = []
    for c in cands:
        try:
            r = c.expanduser().resolve()
        except OSError:
            continue
        if r.is_dir() and not any(r == o or r.is_relative_to(o) for o in out):
            out = [o for o in out if not o.is_relative_to(r)] + [r]
    return out


def _allowed(path: Path) -> Path:
    p = path.expanduser().resolve()
    if not any(p == r or p.is_relative_to(r) for r in roots()):
        raise PermissionError(f"{path} is outside the allowed roots")
    return p


def _hint(p: Path, is_dir: bool) -> Optional[str]:
    name = p.name
    if is_dir:
        if name in ("day_aggs_v1", "minute_aggs_v1") or name in ("us_stocks_sip", "us_options_opra"):
            return "massive"
        if re.match(r"^[A-Z]{3,5}\.[A-Z0-9]+$", name):
            return "databento"
        return None
    if name.endswith((".dbn", ".dbn.zst")):
        return "dbn"
    m = _DATED.search(name)
    if m:
        return "massive-csv" if m.group(2) == "csv.gz" else "dated-parquet"
    if name.endswith(".parquet"):
        return "parquet"
    return None


def browse(path: Optional[str] = None, show_hidden: bool = False) -> dict[str, Any]:
    """Entries of a directory inside the allowed roots (directories first)."""
    rs = roots()
    if not path:
        return {"path": None, "parent": None, "roots": [str(r) for r in rs],
                "entries": [{"name": str(r), "path": str(r), "dir": True, "hint": _hint(r, True)} for r in rs]}
    p = _allowed(Path(path))
    if not p.is_dir():
        raise NotADirectoryError(str(p))
    entries, truncated = [], False
    with os.scandir(p) as it:
        for e in it:
            if not show_hidden and e.name.startswith("."):
                continue
            if len(entries) >= MAX_ENTRIES:
                truncated = True
                break
            try:
                is_dir = e.is_dir()
                st = e.stat()
            except OSError:
                continue
            entries.append({"name": e.name, "path": os.path.join(str(p), e.name), "dir": is_dir,
                            "size": None if is_dir else st.st_size, "mtime": int(st.st_mtime),
                            "hint": _hint(Path(e.name), is_dir)})
    entries.sort(key=lambda x: (not x["dir"], x["name"]))
    parent = str(p.parent) if any(p.parent == r or p.parent.is_relative_to(r) for r in rs) and p not in rs else None
    return {"path": str(p), "parent": parent, "roots": [str(r) for r in rs], "entries": entries,
            "truncated": truncated}


# ── massive ───────────────────────────────────────────────────────────────

def _massive_index(path: Path) -> Optional[str]:
    parts = path.parts
    for i in range(len(parts) - 1):
        if parts[i] in ("us_stocks_sip", "us_options_opra") and parts[i + 1] in ("day_aggs_v1", "minute_aggs_v1"):
            return f"{parts[i]}/{parts[i + 1]}"
    return None


def _walk(paths: list[Path]):
    for p in paths:
        if p.is_file():
            yield p
        elif p.is_dir():
            for dirpath, dirnames, filenames in os.walk(p, followlinks=True):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                for fn in sorted(filenames):
                    yield Path(dirpath) / fn


def _massive_files(paths: list[Path]) -> tuple[dict[str, list[tuple[str, Path]]], int]:
    groups: dict[str, list[tuple[str, Path]]] = {}
    ignored = 0
    for f in _walk(paths):
        m = _DATED.search(f.name)
        idx = _massive_index(f)
        if not m or not idx:
            ignored += 1
            continue
        groups.setdefault(idx, []).append((m.group(1), f))
    return groups, ignored


# ── inspect ───────────────────────────────────────────────────────────────

def inspect(vendor: str, paths: list[str]) -> dict[str, Any]:
    """What a selection holds, before importing it."""
    if vendor not in VENDORS:
        raise ValueError(f"vendor must be one of {VENDORS}")
    sel = [_allowed(Path(p)) for p in paths]
    if vendor == "massive":
        from .massive_dl import INDICES
        groups, ignored = _massive_files(sel)
        out = []
        for idx, files in sorted(groups.items()):
            dates = sorted(d for d, _ in files)
            asset, res = INDICES[idx]
            out.append({"index": idx, "asset": asset, "resolution": res, "files": len(files),
                        "csv": sum(1 for _, f in files if f.name.endswith(".csv.gz")),
                        "bytes": sum(f.stat().st_size for _, f in files),
                        "start": dates[0], "end": dates[-1]})
        return {"vendor": vendor, "groups": out, "ignored": ignored,
                "files": sum(g["files"] for g in out)}
    from qfinzero.pipeline.engine import connect
    from qfinzero.pipeline.sources import databento as dbn
    files = [f for f in _walk(sel) if dbn.is_raw_file(f)]
    con = connect()
    try:
        infos = [dbn.describe(f, con) for f in files[:MAX_DESCRIBE]]
    finally:
        con.close()
    summary = dbn.summarize(infos, sel[0] if sel else Path("."))
    summary.update(vendor=vendor, files=len(files), described=len(infos),
                   bytes=sum(f.stat().st_size for f in files))
    return summary


# ── import and convert ────────────────────────────────────────────────────

def library(vendor: str) -> Path:
    d = config_store.dirs()
    return Path(d["raw_databento" if vendor == "databento" else "raw_massive"]).expanduser()


def _link(src: Path, dst: Path) -> bool:
    """Symlink ``dst`` -> ``src``; False when it already points there."""
    if dst.is_symlink() or dst.exists():
        try:
            if dst.resolve() == src.resolve():
                return False
        except OSError:
            pass
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.symlink_to(src)
    return True


def import_local(vendor: str, paths: list[str], *, on_line: Optional[OnLine] = None,
                 convert: bool = True, jobs: int = 4) -> dict[str, Any]:
    say = on_line or (lambda _l: None)
    sel = [_allowed(Path(p)) for p in paths]
    lib = library(vendor)
    lib.mkdir(parents=True, exist_ok=True)
    lib_real = lib.resolve()
    say(f"[import] {vendor}: {len(sel)} selection(s) -> raw library {lib}")
    plans: list[dict[str, Any]] = []
    if vendor == "massive":
        from .massive_dl import INDICES, csv_to_parquet
        groups, ignored = _massive_files(sel)
        if ignored:
            say(f"  {ignored} files are not massive day/minute aggregates and are skipped")
        for idx, files in sorted(groups.items()):
            linked = transferred = kept = 0
            for d, f in files:
                dst = lib / idx / d[:4] / d[5:7] / f"{d}.parquet"
                if f.resolve().is_relative_to(lib_real) and f.name.endswith(".parquet"):
                    kept += 1
                elif f.name.endswith(".csv.gz"):
                    if not dst.exists():
                        csv_to_parquet(f, dst)
                        transferred += 1
                    else:
                        kept += 1
                elif _link(f, dst):
                    linked += 1
                else:
                    kept += 1
            dates = sorted(d for d, _ in files)
            asset, res = INDICES[idx]
            say(f"  {idx}: {len(files)} days {dates[0]}..{dates[-1]}  linked={linked} "
                f"csv->parquet={transferred} already={kept}")
            plans.append({"vendor": "massive", "asset": asset, "resolution": res,
                          "start": dates[0], "end": dates[-1]})
    elif vendor == "databento":
        n = 0
        for p in sel:
            if p.is_relative_to(lib_real):
                continue
            tag = hashlib.sha1(str(p).encode()).hexdigest()[:8]
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", p.name)[:60] or "import"
            if _link(p, lib / "imports" / f"{name}-{tag}"):
                n += 1
        say(f"  linked {n} new selection(s) under {lib / 'imports'}")
        plans.append({"vendor": "databento"})
    else:
        raise ValueError(f"vendor must be one of {VENDORS}")
    result: dict[str, Any] = {"ok": True, "vendor": vendor, "library": str(lib), "plans": plans}
    if convert:
        result["convert"] = [run_convert(p, on_line=say, jobs=jobs) for p in plans]
        result["ok"] = all(c["ok"] for c in result["convert"])
    return result


def run_convert(plan: dict[str, Any], *, on_line: Optional[OnLine] = None, jobs: int = 4) -> dict[str, Any]:
    """``qfz-data convert`` for one plan, in a subprocess, streaming its log."""
    from .acquire import run_stream
    d = config_store.dirs()
    cmd = [sys.executable, "-m", "qfinzero.pipeline.cli",
           "--massive", d.get("raw_massive", ""), "--databento", d.get("raw_databento", ""),
           "--storage", d.get("storage_root", ""), "convert", "--vendor", plan["vendor"], "--market", "us"]
    if plan["vendor"] == "massive":
        cmd += ["--asset", plan["asset"], "--resolution", plan["resolution"],
                "--start", plan["start"], "--end", plan["end"]]
    else:
        cmd += ["--jobs", str(max(1, int(jobs)))]
    if on_line:
        on_line("[convert] " + " ".join(cmd[1:]))
    res = run_stream(cmd, on_line=on_line)
    return {"ok": res["ok"], "returncode": res["returncode"], "plan": plan}


# ── downloads ─────────────────────────────────────────────────────────────

def download(vendor: str, params: dict[str, Any], *, dry_run: bool = True, convert: bool = True,
             on_line: Optional[OnLine] = None, jobs: int = 4) -> dict[str, Any]:
    """Quote (``dry_run``) or download, then convert what arrived."""
    say = on_line or (lambda _l: None)
    lib = library(vendor)
    if vendor == "databento":
        from . import databento_dl
        key = config_store.databento_key()
        if not key:
            return {"ok": False, "error": "set the Databento API key first"}
        res = databento_dl.download(params, api_key=key, root=lib, dry_run=dry_run, on_line=say)
        plan = {"vendor": "databento"}
    elif vendor == "massive":
        from . import massive_dl
        s3 = config_store.massive_s3()
        res = massive_dl.download(params, access_key=s3.get("access_key_id", ""),
                                  secret_key=s3.get("secret_access_key", ""), endpoint=s3.get("endpoint", ""),
                                  root=lib, dry_run=dry_run, on_line=say)
        asset, resolution = massive_dl.INDICES.get(str(params.get("index")), ("stock", "daily"))
        plan = {"vendor": "massive", "asset": asset, "resolution": resolution,
                "start": str(params.get("start"))[:10], "end": str(params.get("end"))[:10]}
    else:
        raise ValueError(f"vendor must be one of {VENDORS}")
    if not dry_run and convert and res.get("ok", True):
        res["convert"] = run_convert(plan, on_line=say, jobs=jobs)
        res["ok"] = res["convert"]["ok"]
    return res


def status() -> dict[str, Any]:
    """Where things go, and which credentials are present (never their values)."""
    d = config_store.dirs()
    s3 = config_store.massive_s3()
    return {
        "storage_root": d.get("storage_root"),
        "libraries": {v: str(library(v)) for v in VENDORS},
        "roots": [str(r) for r in roots()],
        "credentials": {
            "databento": bool(config_store.databento_key()),
            "massive": bool(s3.get("access_key_id") and s3.get("secret_access_key")),
        },
        "massive_endpoint": s3.get("endpoint"),
        "today": date.today().isoformat(),
    }
