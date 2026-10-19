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
_ANY_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
QUOTE_DIRS = ("quotes_v1", "quotes_sample", "quotes_30min_snapshot")


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
    """Library index of a massive file; every quote flavour maps to ``quotes_v1``."""
    parts = path.parts
    for i in range(len(parts) - 1):
        if parts[i] in ("us_stocks_sip", "us_options_opra"):
            if parts[i + 1] in ("day_aggs_v1", "minute_aggs_v1"):
                return f"{parts[i]}/{parts[i + 1]}"
            if parts[i + 1] in QUOTE_DIRS:
                return f"{parts[i]}/quotes_v1"
    return None


def _quote_kind(f: Path) -> Optional[str]:
    """flat (one file a day), rest (one contract a day, jsonl.gz) or snapshot (mark_ns parquet)."""
    name = f.name
    if name.endswith(".jsonl.gz") or name.endswith(".jsonl"):
        return "rest"
    if name.endswith(".csv.gz"):
        return "flat" if _DATED.search(name) else None
    if name.endswith(".parquet"):
        try:
            import pyarrow.parquet as pq
            cols = set(pq.read_schema(f).names)
        except Exception:  # noqa: BLE001
            return None
        if "mark_ns" in cols:
            return "snapshot"
        if "sip_timestamp" in cols and _ANY_DATE.search(name):
            return "flat"
        return None
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
        idx = _massive_index(f)
        if not idx:
            ignored += 1
            continue
        if idx.endswith("quotes_v1"):
            dates = _ANY_DATE.findall(f.name)
            if not dates or _quote_kind(f) is None:
                ignored += 1
                continue
            groups.setdefault(idx, []).append((dates[-1], f))
            continue
        m = _DATED.search(f.name)
        if not m:
            ignored += 1
            continue
        groups.setdefault(idx, []).append((m.group(1), f))
    return groups, ignored


def _normalise_quote(f: Path, kind: str, d: str, lib: Path, idx: str) -> list[Path]:
    """Write a quote file into ``lib/idx`` as parquet with ticker, sip_timestamp,
    bid/ask price and size. Returns the files written (or linked)."""
    from .massive_dl import csv_to_parquet
    day_dir = lib / idx / d[:4] / d[5:7]
    if kind == "flat":
        dst = day_dir / f"{d}.parquet"
        if f.name.endswith(".csv.gz"):
            if not dst.exists():
                csv_to_parquet(f, dst)
        else:
            _link(f, dst)
        return [dst]
    from qfinzero.pipeline.engine import connect
    con = connect()
    try:
        if kind == "rest":
            m = re.match(r"^(O_[A-Z0-9]+|[A-Z.]+)__", f.name)
            ticker = (m.group(1).replace("O_", "O:", 1) if m else f.name.split("__")[0])
            dst = day_dir / d / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', ticker)}.parquet"
            dst.parent.mkdir(parents=True, exist_ok=True)
            con.execute(
                f"COPY (SELECT '{ticker}' AS ticker, CAST(sip_timestamp AS BIGINT) AS sip_timestamp, bid_price, "
                f"ask_price, CAST(bid_size AS BIGINT) AS bid_size, CAST(ask_size AS BIGINT) AS ask_size "
                f"FROM read_json_auto('{_lit_path(f)}')) TO '{_lit_path(dst)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
            return [dst]
        # snapshot: one row per (contract, mark); the mark is the end of the
        # minute before it, so the book lands in that minute
        out = []
        et = "timezone('America/New_York', to_timestamp((mark_ns - 1) // 1000000000))"
        days = [r[0] for r in con.execute(
            f"SELECT DISTINCT strftime(CAST({et} AS DATE), '%Y-%m-%d') FROM read_parquet('{_lit_path(f)}')").fetchall()]
        for day in days:
            dst = lib / idx / day[:4] / day[5:7] / day / f"snapshot-{f.stem}.parquet"
            dst.parent.mkdir(parents=True, exist_ok=True)
            con.execute(
                f"COPY (SELECT ticker, mark_ns - 1 AS sip_timestamp, bid_price, ask_price, bid_size, ask_size "
                f"FROM read_parquet('{_lit_path(f)}') WHERE strftime(CAST({et} AS DATE), '%Y-%m-%d') = '{day}') "
                f"TO '{_lit_path(dst)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
            out.append(dst)
        return out
    finally:
        con.close()


def _lit_path(p: Path) -> str:
    return str(p).replace("'", "''")


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
            g = {"index": idx, "asset": asset, "resolution": res, "files": len(files),
                 "csv": sum(1 for _, f in files if f.name.endswith(".csv.gz")),
                 "bytes": sum(f.stat().st_size for _, f in files),
                 "start": dates[0], "end": dates[-1]}
            if res == "quotes":
                kinds: dict[str, int] = {}
                for _, f in files:
                    k = _quote_kind(f) or "?"
                    kinds[k] = kinds.get(k, 0) + 1
                g["kinds"] = kinds
            out.append(g)
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


def set_quote_intervals(intervals: Optional[dict[str, int]]) -> dict[str, int]:
    """Persist the BBO sampling per asset (later updates keep it) and return the result."""
    from qfinzero.pipeline.convert import default_quote_intervals
    from qfinzero.pipeline.sources.databento import check_interval
    if intervals:
        clean = {f"{a}_interval_min": check_interval(v) for a, v in intervals.items() if a in ("stock", "option", "future") and v}
        if clean:
            config_store.update({"quotes": clean})
    return default_quote_intervals()


def import_local(vendor: str, paths: list[str], *, on_line: Optional[OnLine] = None,
                 convert: bool = True, jobs: int = 4,
                 quote_intervals: Optional[dict[str, int]] = None) -> dict[str, Any]:
    say = on_line or (lambda _l: None)
    iv = set_quote_intervals(quote_intervals)
    say(f"[import] BBO sampling: stocks every {iv['stock']} min, options every {iv['option']} min")
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
            asset, res = INDICES[idx]
            if res == "quotes":
                written = 0
                for d, f in files:
                    written += len(_normalise_quote(f, _quote_kind(f), d, lib, idx))
                dates = sorted(d for d, _ in files)
                say(f"  {idx}: {len(files)} quote file(s) {dates[0]}..{dates[-1]} -> {written} library file(s)")
                plans.append({"vendor": "massive", "asset": asset, "resolution": "quotes",
                              "start": dates[0], "end": dates[-1]})
                continue
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
            # tag first: the converter recognises files by their suffix (.dbn.zst)
            if _link(p, lib / "imports" / f"{tag}-{name}"):
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
    from qfinzero.pipeline.convert import default_quote_intervals
    iv = default_quote_intervals()
    cmd = [sys.executable, "-m", "qfinzero.pipeline.cli",
           "--massive", d.get("raw_massive", ""), "--databento", d.get("raw_databento", ""),
           "--storage", d.get("storage_root", ""), "convert", "--vendor", plan["vendor"], "--market", "us",
           "--stock-quote-interval", str(iv["stock"]), "--option-quote-interval", str(iv["option"]),
           "--future-quote-interval", str(iv["future"])]
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

def choose_key(vendor: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The key a request uses: ``params.key_id`` when given, else the first key
    whose products cover the dataset (Databento) or index (massive)."""
    want = str(params.get("key_id") or "")
    if want:
        return next((k for k in config_store.vendor_keys(vendor) if k.get("id") == want), None)
    product = params.get("dataset") if vendor == "databento" else params.get("index")
    return config_store.pick_key(vendor, str(product) if product else None)


def download(vendor: str, params: dict[str, Any], *, dry_run: bool = True, convert: bool = True,
             on_line: Optional[OnLine] = None, jobs: int = 4,
             quote_intervals: Optional[dict[str, int]] = None,
             on_progress: Optional[Callable[..., None]] = None,
             should_stop: Optional[Callable[[], bool]] = None, job_id: str = "") -> dict[str, Any]:
    """Quote (``dry_run``) or download, then convert what arrived."""
    say = on_line or (lambda _l: None)
    prog = on_progress or (lambda **_k: None)
    if not dry_run:
        set_quote_intervals(quote_intervals)
    lib = library(vendor)
    key = choose_key(vendor, params)
    if key is None:
        product = params.get("dataset") if vendor == "databento" else params.get("index")
        return {"ok": False, "error": f"no {vendor} key covers {product or 'this request'}: add one under Keys"}
    say(f"[{vendor}] using key {key.get('label') or key['id']} ({key['id']})")
    if vendor == "databento":
        from . import databento_dl
        res = databento_dl.download(params, api_key=key.get("api_key", ""), root=lib, dry_run=dry_run, on_line=say,
                                    on_progress=prog, should_stop=should_stop, key_id=key["id"], job_id=job_id)
        plan = {"vendor": "databento"}
    elif vendor == "massive":
        from . import massive_dl
        endpoint = key.get("s3_endpoint") or config_store.massive_s3().get("endpoint", "")
        res = massive_dl.download(params, access_key=key.get("s3_access_key_id", ""),
                                  secret_key=key.get("s3_secret_access_key", ""), endpoint=endpoint,
                                  root=lib, dry_run=dry_run, on_line=say, on_progress=prog,
                                  should_stop=should_stop)
        asset, resolution = massive_dl.INDICES.get(str(params.get("index")), ("stock", "daily"))
        plan = {"vendor": "massive", "asset": asset, "resolution": resolution,
                "start": str(params.get("start"))[:10], "end": str(params.get("end"))[:10]}
    else:
        raise ValueError(f"vendor must be one of {VENDORS}")
    res["key"] = {"id": key["id"], "label": key.get("label") or key["id"]}
    if not dry_run and convert and res.get("ok", True):
        prog(stage="converting", current="QFZ store")
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
        "keys": {v: len(config_store.vendor_keys(v)) for v in VENDORS},
        "massive_endpoint": s3.get("endpoint"),
        "quote_intervals": _intervals(),
        "today": date.today().isoformat(),
    }


def _intervals() -> dict[str, int]:
    from qfinzero.pipeline.convert import default_quote_intervals
    return default_quote_intervals()
