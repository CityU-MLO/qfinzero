"""QFinZero data-admin core — the shared backend for the ``qfz-data`` admin
subcommands and the data-admin FastAPI service (:19340).

This package sits beside :mod:`qfinzero.pipeline` (raw→UPQ conversion) and
:mod:`qfinzero.update` (convert-only orchestration) and adds the *operator*
surface the QFinZero Console drives:

* :mod:`~qfinzero.admin.config_store` — editable, masked vendor credentials +
  data dirs + update schedule, persisted at ``$QFZ_DATA_ROOT/_state/qfz.config.json``
  and applied to ``os.environ`` so the pipeline, scripts and services see them.
* :mod:`~qfinzero.admin.scan` — provider reachability / permission scans
  (MASSIVE S3 + REST, Tushare token).
* :mod:`~qfinzero.admin.acquire` — trigger the external download scripts
  (``upq_flatfiles.sh``, ``news_data.sh``) with streamed logs ("own it end to end").
* :mod:`~qfinzero.admin.scheduler` — cron-backed update cadence.
* :mod:`~qfinzero.admin.explore` — UPQ store / ESP coverage summaries.
* :mod:`~qfinzero.admin.setup` — first-run setup-state for the wizard.

House style: ``from __future__ import annotations``, stdlib-first, best-effort I/O.
"""

from __future__ import annotations

__all__ = ["config_store", "scan", "acquire", "scheduler", "explore", "setup"]
