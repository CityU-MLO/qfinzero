"""Orchestrator — detect → (convert) → record, convert-only.

Composes the existing converter; never re-implements conversion. Dependencies
(``scan_fn``, ``converter_factory``) are injectable so the planning/decision logic
is unit-testable without DuckDB or real data.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import date
from time import perf_counter
from typing import Callable, Optional

from .freshness import Freshness, colour, compute_freshness
from .lock import domain_lock
from .manifest import UpdateManifest
from .sources import Source, select


@dataclass
class PlanItem:
    source: Source
    freshness: Freshness
    will_run: bool
    reason: str  # stale | forced | dependency | fresh-skip | unavailable | no-raw

    def to_dict(self) -> dict:
        fr = self.freshness
        return {
            "id": self.source.id,
            "domain": self.source.domain,
            "market": self.source.market,
            "owner": self.source.owner,
            "store": self.source.store,
            "raw_max": fr.raw_max,
            "store_max": fr.store_max,
            "behind_days": fr.behind_days,
            "lag_days": fr.lag_days,
            "state": fr.state,
            "colour": colour(fr),
            "will_run": self.will_run,
            "reason": self.reason,
            "note": self.source.note,
        }


@dataclass
class RunResult:
    source_id: str
    status: str  # ok | error | skipped | unavailable
    reason: str
    partitions: int = 0
    rows: int = 0
    skipped: int = 0
    duration_s: float = 0.0
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.source_id,
            "status": self.status,
            "reason": self.reason,
            "partitions": self.partitions,
            "rows": self.rows,
            "skipped": self.skipped,
            "duration_s": round(self.duration_s, 3),
            "error": self.error,
            "notes": self.notes,
        }


class Orchestrator:
    def __init__(
        self,
        paths=None,
        scan_fn: Optional[Callable[[], dict]] = None,
        converter_factory: Optional[Callable[[], object]] = None,
        today: Optional[date] = None,
    ):
        if paths is None:
            from qfinzero.pipeline.paths import resolve
            paths = resolve()
        self.paths = paths
        self._scan_fn = scan_fn
        self._converter_factory = converter_factory
        self.today = today

    # ── dependency hooks (lazy so unit tests don't import duckdb) ────────

    def _scan(self) -> dict:
        if self._scan_fn is not None:
            return self._scan_fn()
        from qfinzero.pipeline import registry
        return registry.scan(self.paths)

    def _converter(self):
        if self._converter_factory is not None:
            return self._converter_factory()
        from qfinzero.pipeline.convert import Converter
        return Converter(self.paths)

    # ── planning ─────────────────────────────────────────────────────────

    @staticmethod
    def _decide(src: Source, fr: Freshness, force: bool) -> tuple[bool, str]:
        if not src.available:
            return False, "unavailable"
        if fr.state == "no_raw":
            return False, "no-raw"
        if force:
            return True, "forced"
        if fr.stale:
            return True, "stale"
        return False, "fresh-skip"

    def plan(
        self,
        selection: str | None = "all",
        market: str | None = None,
        force: bool = False,
        scan: dict | None = None,
    ) -> list[PlanItem]:
        scan = scan if scan is not None else self._scan()
        sources = select(selection, market)
        items: list[PlanItem] = []
        any_price_stale = False
        for src in sources:
            fr = compute_freshness(src, scan, self.today)
            will, reason = self._decide(src, fr, force)
            if will and src.domain == "price" and src.dated:
                any_price_stale = True
            items.append(PlanItem(src, fr, will, reason))

        # corp_actions depends on stock/option output: rebuild if any dated price ran.
        if any_price_stale:
            for it in items:
                if it.source.id == "corp_actions" and it.source.available and not it.will_run:
                    it.will_run = True
                    it.reason = "dependency"
        return items

    # ── execution ────────────────────────────────────────────────────────

    def run(
        self,
        selection: str | None = "all",
        market: str | None = None,
        since: str | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> dict:
        items = self.plan(selection, market, force)
        plan_payload = [it.to_dict() for it in items]
        if dry_run:
            return {"dry_run": True, "plan": plan_payload, "results": []}

        to_run = [it for it in items if it.will_run]
        results: list[RunResult] = []
        # nothing to do — still record skips so the manifest reflects the check
        manifest = UpdateManifest.load(self.paths.storage)

        if not to_run:
            for it in items:
                results.append(RunResult(it.source.id, "skipped", it.reason,
                                         notes=[it.freshness.note] if it.freshness.note else []))
            self._record(manifest, items, results)
            manifest.save()
            return {"dry_run": False, "plan": plan_payload, "results": [r.to_dict() for r in results]}

        with contextlib.ExitStack() as stack:
            # one advisory lock per domain that has work (only "price" is active in v1)
            for dom in sorted({it.source.domain for it in to_run}):
                stack.enter_context(domain_lock(self.paths.storage, dom))
            cv = stack.enter_context(self._converter())

            run_ids = {it.source.id for it in to_run}
            for it in items:
                src = it.source
                if src.id not in run_ids:
                    results.append(RunResult(src.id, "skipped", it.reason))
                    continue
                start = since if since is not None else (
                    it.freshness.store_max if src.dated else None
                )
                t0 = perf_counter()
                try:
                    res = src.run(cv, start, force)
                    rr = RunResult(
                        src.id, "ok", it.reason,
                        partitions=getattr(res, "partitions", 0),
                        rows=getattr(res, "rows", 0),
                        skipped=getattr(res, "skipped", 0),
                        duration_s=perf_counter() - t0,
                        notes=list(getattr(res, "notes", []) or []),
                    )
                except Exception as e:  # noqa: BLE001 — surface per-source, keep going
                    rr = RunResult(src.id, "error", it.reason,
                                   duration_s=perf_counter() - t0, error=str(e))
                results.append(rr)

        self._record(manifest, items, results)
        manifest.save()
        return {"dry_run": False, "plan": plan_payload, "results": [r.to_dict() for r in results]}

    def _record(self, manifest: UpdateManifest, items: list[PlanItem], results: list[RunResult]) -> None:
        by_id = {it.source.id: it for it in items}
        for rr in results:
            it = by_id.get(rr.source_id)
            if it is None:
                continue
            fr = it.freshness
            # on a successful dated conversion the store has caught up to raw
            store_max = fr.raw_max if (rr.status == "ok" and it.source.dated) else fr.store_max
            manifest.record(
                rr.source_id,
                domain=it.source.domain,
                raw_max=fr.raw_max,
                store_max=store_max,
                behind_days=fr.behind_days,
                lag_days=fr.lag_days,
                state=fr.state,
                status=rr.status,
                reason=rr.reason,
                rows=rr.rows,
                partitions=rr.partitions,
                skipped=rr.skipped,
                duration_s=round(rr.duration_s, 3),
                error=rr.error,
            )

    # ── status (freshness + last run), for CLI/API ───────────────────────

    def status(self, selection: str | None = "all", market: str | None = None) -> dict:
        scan = self._scan()
        items = self.plan(selection, market, force=False, scan=scan)
        manifest = UpdateManifest.load(self.paths.storage)
        out = []
        for it in items:
            d = it.to_dict()
            d["last_run"] = manifest.get(it.source.id)
            out.append(d)
        return {"sources": out}
