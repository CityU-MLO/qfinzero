"""End-to-end: the whole stack on the synthetic sample.

Starts ``python -m qfinzero.server`` (hub, UPQ, ESP, PMB, MCP) on free ports
against a freshly generated sample and drives it only through public
interfaces. Opt-in because it needs the UPQ binary:

    cargo build -p upq-service          # in infra/upq
    QFZ_E2E=1 pytest tests/test_e2e.py
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("QFZ_E2E") != "1", reason="set QFZ_E2E=1 to run")

REPO = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _health(url: str) -> dict:
    try:
        with urllib.request.urlopen(url + "/health", timeout=2) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return {}


@pytest.fixture(scope="module")
def stack(sample_root, tmp_path_factory):
    from qfinzero.auth.store import AuthStore

    state = tmp_path_factory.mktemp("state")
    env = {**os.environ, "QFZ_DATA_ROOT": str(sample_root), "QFZ_STATE_DIR": str(state),
           "QFZ_AUTH_DB": str(state / "auth.sqlite3"), "QFZ_SERVE_UI": "0", "QFZ_AUTH_MODE": "required"}
    for k in ("STORAGE_ROOT", "EARNINGS_DB", "ECON_EVENTS_DB", "NEWS_DB", "QFZ_ADMIN_PASSWORD"):
        env.pop(k, None)
    for k in ("QFZ_SERVER_PORT", "UPQ_PORT", "ESP_PORT", "PMB_PORT", "PLAYGROUND_PORT",
              "DATA_ADMIN_PORT", "DASHBOARD_PORT"):
        env[k] = str(_free_port())

    store = AuthStore(state / "auth.sqlite3")
    user = store.create_user("e2e", "e2e-password-123", role="researcher")
    _, key = store.create_api_key(user.id, "e2e")

    url = f"http://127.0.0.1:{env['QFZ_SERVER_PORT']}"
    log = open(state / "hub.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "qfinzero.server"], cwd=REPO, env=env,
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            h = _health(url)
            if h.get("children", {}).get("mcp") == "up":
                break
            if proc.poll() is not None:
                break
            time.sleep(1)
        h = _health(url)
        if h.get("children", {}).get("upq") != "up":
            pytest.skip(f"stack did not come up (UPQ built?): {h} — see {state / 'hub.log'}")
        yield url, key
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(20)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
        log.close()


def test_mcp_and_services_require_a_key(stack):
    url, _ = stack
    for path in ("/mcp/", "/svc/upq/health"):
        req = urllib.request.Request(url + path, method="POST" if path == "/mcp/" else "GET",
                                     data=b"{}" if path == "/mcp/" else None,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        assert e.value.code in (401, 302, 303)


def test_oracle_solves_every_task(stack):
    from qfinzero.bench.oracle import Endpoints, run_oracle
    from qfinzero.bench.tasks import load_tasks
    url, key = stack
    results = run_oracle(load_tasks(), Endpoints.hub(url, key))
    failed = [r for r in results if not r.get("correct")]
    assert not failed, json.dumps(failed[:5], indent=1, default=str)


def test_session_lock_maps_to_task_time(stack):
    from qfinzero.bench.agent import lock_session
    from qfinzero.bench.oracle import Endpoints
    from qfinzero.bench.tasks import load_tasks
    from qfinzero.timelock import as_of_for_clock
    url, key = stack
    _, _, pmb = Endpoints.hub(url, key).clients()
    for t in {t.as_of: t for t in load_tasks() if t.as_of}.values():
        sid = lock_session(pmb, t.as_of)
        assert as_of_for_clock(pmb.get_session_state(sid)["clock"]) == t.as_of, t.id


class ScriptedLLM:
    """Stands in for a chat model: one tool call, then answers from its result."""

    def __init__(self, tool: str, args: dict, pick):
        self.tool, self.args, self.pick = tool, args, pick

    async def chat(self, client, messages, tools):
        assert any(t["function"]["name"] == self.tool for t in tools)
        if messages[-1]["role"] == "user":
            call = {"id": "c1", "type": "function",
                    "function": {"name": self.tool, "arguments": json.dumps(self.args)}}
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        value = self.pick(json.loads(messages[-1]["content"]))
        return {"choices": [{"message": {"role": "assistant", "content": f"ANSWER: {json.dumps(value)}"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5}}


def _eps(r):
    (ev,) = r["events"]
    return ev["payload"]["actual_eps"]


@pytest.mark.parametrize("task_id", ["time_lock-001", "time_lock-003"])
def test_agent_loop_over_mcp_is_time_locked(stack, task_id):
    """The model asks for the result without passing any time; the session
    header alone decides whether it is visible."""
    from qfinzero.bench.agent import run_agent
    from qfinzero.bench.tasks import load_tasks
    url, key = stack
    (t,) = [t for t in load_tasks() if t.id == task_id]
    llm = ScriptedLLM("esp_earnings_calendar",
                      {"start_date": t.args["date"], "end_date": t.args["date"], "tickers": [t.args["ticker"]]},
                      _eps)
    (r,) = run_agent([t], llm, url, key, allow=["esp_"])
    assert r["correct"], r
    assert r["tool_calls"] == 1 and r["prompt_tokens"] == 30
