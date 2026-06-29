"""Idempotent conversion-state manifest.

A small JSON file under the storage root recording, per converted partition, the
source file's size+mtime and the row count. Re-running the converter skips
partitions whose source is unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Manifest:
    path: Path
    entries: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, storage_root: Path) -> "Manifest":
        path = storage_root / "_pipeline_manifest.json"
        entries: dict[str, dict] = {}
        if path.exists():
            try:
                entries = json.loads(path.read_text()).get("entries", {})
            except (json.JSONDecodeError, OSError):
                entries = {}
        return cls(path=path, entries=entries)

    def key(self, store: str, trade_date: str) -> str:
        return f"{store}/{trade_date}"

    def is_current(self, store: str, trade_date: str, src: Path) -> bool:
        e = self.entries.get(self.key(store, trade_date))
        if not e:
            return False
        try:
            st = src.stat()
        except OSError:
            return False
        return e.get("src_size") == st.st_size and e.get("src_mtime") == int(st.st_mtime)

    def record(self, store: str, trade_date: str, src: Path | None, rows: int) -> None:
        rec = {"rows": rows}
        if src is not None:
            try:
                st = src.stat()
                rec["src_size"] = st.st_size
                rec["src_mtime"] = int(st.st_mtime)
                rec["src"] = str(src)
            except OSError:
                pass
        self.entries[self.key(store, trade_date)] = rec

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"entries": self.entries}, indent=2, default=str))
