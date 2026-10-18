"""Write the whole sample dataset under one root (``QFZ_DATA_ROOT`` layout)."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .universe import SAMPLE_VERSION, Universe


def build(out, *, with_esp: bool = True, universe: Universe | None = None) -> dict:
    """``out``/upq is UPQ storage, ``out``/esp holds the ESP databases.

    The directory is replaced. Returns a manifest of row counts.
    """
    from . import market
    t0 = time.perf_counter()
    root = Path(out)
    u = universe or Universe()
    upq = root / "upq"
    if upq.exists():
        shutil.rmtree(upq)
    upq.mkdir(parents=True)
    paths = market.simulate(u)
    counts: dict = {}
    counts.update(market.write_stocks(u, paths, upq))
    counts["stock_quote_minute"] = market.write_stock_quotes(u, paths, upq)
    counts.update(market.write_options(u, paths, upq))
    counts.update(market.write_reference(u, paths, upq))
    if with_esp:
        from . import events
        counts.update(events.write_esp(u, paths, root / "esp"))
    manifest = {"sample_version": SAMPLE_VERSION, "seed": u.seed,
                "start": str(u.days[0]), "end": str(u.days[-1]),
                "minute_days": [str(d) for d in u.minute_days],
                "tickers": [s.ticker for s in u.stocks], "rows": counts,
                "seconds": round(time.perf_counter() - t0, 1)}
    (root / "sample_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
