"""The oracle agent: solves every task through the public service APIs.

It knows which op each task is, so it measures the platform, not reasoning:
a full score means each question is answerable through UPQ, ESP and PMB and
that they serve exactly what the sample files hold.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from typing import Optional

from . import episodes
from .ops import OPS, Api
from .score import check
from .tasks import Task


@dataclass
class Endpoints:
    upq: str
    esp: str
    pmb: str
    api_key: Optional[str] = None

    @classmethod
    def hub(cls, url: str, api_key: Optional[str] = None) -> "Endpoints":
        url = url.rstrip("/")
        return cls(f"{url}/svc/upq", f"{url}/svc/esp", f"{url}/svc/pmb", api_key)

    def clients(self):
        from qfinzero.clients.esp.client import ESPClient
        from qfinzero.clients.pmb.client import PMBClient
        from qfinzero.clients.upq.client import UPQClient
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        upq, esp = UPQClient(self.upq, timeout=120), ESPClient(self.esp, timeout=60)
        for c in (upq, esp):
            c._session.headers.update(headers)
        return upq, esp, PMBClient(self.pmb, headers=headers)


def run_oracle(tasks: list[Task], ep: Endpoints, progress=None) -> list[dict]:
    upq, esp, pmb = ep.clients()
    api = Api(upq, esp)
    results = []
    for t in tasks:
        t0 = time.perf_counter()
        r = {"id": t.id, "category": t.category}
        try:
            if t.episode:
                account_id, session_id = episodes.setup(pmb, t.episode)
                episodes.run_script(pmb, t.episode, account_id, session_id)
                r.update(episodes.score_episode(pmb, t.episode, account_id, session_id))
            else:
                got = OPS[t.op][1](api, t.args, t.as_of)
                r.update(answer=got, expected=t.answer, correct=check(t.kind, t.answer, got, t.tolerance))
        except Exception as e:  # noqa: BLE001 — record and continue
            r.update(correct=False, error=f"{type(e).__name__}: {e}",
                     trace=traceback.format_exc(limit=3))
        r["seconds"] = round(time.perf_counter() - t0, 3)
        results.append(r)
        if progress:
            progress(r)
    return results
