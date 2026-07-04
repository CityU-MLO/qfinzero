"""QFinZero data-update orchestration (convert-only).

Detect newly-arrived raw data, run the appropriate existing converter, validate,
and record freshness — without ever re-downloading or writing raw. See
``docs/plans/2026-06-29-assay-console-and-update-orchestration-design.md``.

Public surface:
    from qfinzero.update import Orchestrator, SOURCES, UpdateManifest
"""

from __future__ import annotations

from .sources import SOURCES, Source, select
from .manifest import UpdateManifest
from .freshness import Freshness, compute_freshness
from .orchestrator import Orchestrator, PlanItem, RunResult

__all__ = [
    "SOURCES",
    "Source",
    "select",
    "UpdateManifest",
    "Freshness",
    "compute_freshness",
    "Orchestrator",
    "PlanItem",
    "RunResult",
]
