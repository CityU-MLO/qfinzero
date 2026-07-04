"""Update-state manifest — per-source freshness + last-run telemetry.

A small JSON file at ``STORAGE_ROOT/_state/update_manifest.json`` recording, per
source, the latest raw/store dates seen and the outcome of the last conversion.
This is the single source of truth the CLI and the (future) data-admin API read,
whether an update came from cron or the UI.

Distinct from ``qfinzero.pipeline.manifest.Manifest`` (which tracks per-partition
src size/mtime for the converter's own idempotency). This one is source-level.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATE_DIRNAME = "_state"
MANIFEST_NAME = "update_manifest.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class UpdateManifest:
    path: Path
    sources: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, storage_root: Path) -> "UpdateManifest":
        path = Path(storage_root) / STATE_DIRNAME / MANIFEST_NAME
        sources: dict[str, dict] = {}
        if path.exists():
            try:
                sources = json.loads(path.read_text()).get("sources", {})
            except (json.JSONDecodeError, OSError):
                sources = {}
        return cls(path=path, sources=sources)

    def get(self, source_id: str) -> dict | None:
        return self.sources.get(source_id)

    def record(self, source_id: str, **fields) -> dict:
        """Upsert a source entry, stamping ``last_run_ts``."""
        entry = self.sources.setdefault(source_id, {})
        entry.update(fields)
        entry["last_run_ts"] = _now_iso()
        return entry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"updated_at": _now_iso(), "sources": self.sources}
        self.path.write_text(json.dumps(payload, indent=2, default=str))
