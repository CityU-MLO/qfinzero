"""QFinZero data pipeline.

A formal, out-of-the-box pipeline that

  a. **manages** two raw market-data sources read *in place* (never copied):
       - massive  (Polygon-style US: stocks, options, rates, corporate actions)
       - tushare  (CN A-shares + HK, via the Assay downloader)
  b. **converts** raw quotes into the UPQ on-disk storage format, handling
     splits & dividends through a single unified corporate-actions table.

Entry points:
    from qfinzero.pipeline.registry import scan_raw_sources
    from qfinzero.pipeline.convert import Converter
    # CLI: ``qfz-data status | convert | validate``
"""

from __future__ import annotations

__all__ = ["paths", "schema", "registry", "convert", "corporate_actions"]
