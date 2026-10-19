"""Archive compression of the QFZ store (``qfz-data compact``).

Fresh partitions are written at zstd level 3 (fast, and they may be rewritten
by the next conversion). Partitions older than ``older_than_days`` can be
rewritten at level 9 with the same row groups: 3-6% smaller on real minute,
option and quote partitions, read at the same speed (see
:func:`qfinzero.pipeline.engine.parquet_options`). Each file is rewritten to a
temporary file, its row count checked, then swapped in; compacted files are
remembered in ``_state/compact.json`` (by size and mtime) so a re-run only
touches new or reconverted files.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from .engine import _lit, connect, parquet_options

STORES = ("stock_daily", "stock_minute", "stock_quote_minute", "option_day", "option_minute",
          "option_quote_minute", "future_daily", "future_minute", "future_quote_minute",
          "crypto_daily", "crypto_minute", "fx_daily", "fx_minute", "fx_quote_minute")


def _state(storage: Path) -> Path:
    return storage / "_state" / "compact.json"


def compact(storage: Path, *, stores: Optional[list[str]] = None, older_than_days: int = 30,
            dry_run: bool = False, on_line: Optional[Callable[[str], None]] = None,
            on_progress: Optional[Callable[..., None]] = None,
            should_stop: Optional[Callable[[], bool]] = None) -> dict[str, Any]:
    say = on_line or (lambda _l: None)
    prog = on_progress or (lambda **_k: None)
    stop = should_stop or (lambda: False)
    cutoff = (date.today() - timedelta(days=max(0, int(older_than_days)))).isoformat()
    try:
        done: dict[str, dict] = json.loads(_state(storage).read_text())
    except (OSError, ValueError):
        done = {}
    todo: list[Path] = []
    for st in stores or STORES:
        base = storage / st
        if not base.is_dir():
            continue
        for part in sorted(base.glob("trade_date=*")):
            if part.name[len("trade_date="):] >= cutoff:
                continue
            for f in sorted(part.glob("*.parquet")):
                rel = str(f.relative_to(storage))
                s = f.stat()
                rec = done.get(rel)
                if rec and rec.get("size") == s.st_size and rec.get("mtime_ns") == s.st_mtime_ns:
                    continue
                todo.append(f)
    total = sum(f.stat().st_size for f in todo)
    say(f"[compact] {len(todo)} file(s), {total / 1e9:.2f} GB older than {cutoff} to rewrite at zstd 9")
    prog(stage="planned", files_total=len(todo), files_done=0, bytes_total=total, bytes_done=0)
    if dry_run or not todo:
        return {"ok": True, "files": len(todo), "bytes": total, "dry_run": dry_run, "cutoff": cutoff}
    con = connect()
    before = after = 0
    n = 0
    try:
        for f in todo:
            if stop():
                say("[compact] stopped by the user")
                break
            rel = str(f.relative_to(storage))
            prog(stage="compacting", current=rel)
            tmp = f.with_name(f.name + ".compact")
            size0 = f.stat().st_size
            con.execute(f"COPY (SELECT * FROM read_parquet('{_lit(f)}')) TO '{_lit(tmp)}' ({parquet_options('archive')})")
            rows0 = con.execute(f"SELECT count(*) FROM read_parquet('{_lit(f)}')").fetchone()[0]
            rows1 = con.execute(f"SELECT count(*) FROM read_parquet('{_lit(tmp)}')").fetchone()[0]
            if rows0 != rows1:
                tmp.unlink(missing_ok=True)
                say(f"  [skip] {rel}: row count changed ({rows0} -> {rows1})")
                continue
            os.replace(tmp, f)
            s = f.stat()
            done[rel] = {"size": s.st_size, "mtime_ns": s.st_mtime_ns}
            before += size0
            after += s.st_size
            n += 1
            prog(files_done=n, bytes_done=before)
            if n % 50 == 0:
                _state(storage).parent.mkdir(parents=True, exist_ok=True)
                _state(storage).write_text(json.dumps(done))
    finally:
        con.close()
        _state(storage).parent.mkdir(parents=True, exist_ok=True)
        _state(storage).write_text(json.dumps(done))
    saved = before - after
    say(f"[compact] {n} file(s): {before / 1e9:.3f} GB -> {after / 1e9:.3f} GB "
        f"({saved / max(1, before):.1%} saved)")
    prog(stage="done")
    return {"ok": n == len(todo), "files": n, "before": before, "after": after, "saved": saved, "cutoff": cutoff,
            **({"error": "stopped by the user"} if n < len(todo) else {})}
