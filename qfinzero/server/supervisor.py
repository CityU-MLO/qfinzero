"""Supervises the internal service processes behind the hub.

Each child binds localhost only; the hub is the sole public listener. Children
are launched with peer URLs pointing at each other's internal ports (no loopback
through the hub). Health is polled best-effort — a slow/unhealthy child logs a
warning but never crashes the hub.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from qfinzero import config

REPO_ROOT = Path(config.__file__).resolve().parent.parent
LOG_DIR = REPO_ROOT / "logs"

# Internal base URLs (localhost children).
UPQ_IN = f"http://127.0.0.1:{config.UPQ_PORT}"
ESP_IN = f"http://127.0.0.1:{config.ESP_PORT}"
PMB_IN = f"http://127.0.0.1:{config.PMB_PORT}"
PLAYGROUND_IN = f"http://127.0.0.1:{config.PLAYGROUND_PORT}"
DATA_ADMIN_IN = f"http://127.0.0.1:{config.DATA_ADMIN_PORT}"
DASHBOARD_IN = f"http://127.0.0.1:{config.DASHBOARD_PORT}"


def _uvicorn(app: str, port: int) -> list[str]:
    return [sys.executable, "-m", "uvicorn", app,
            "--host", "127.0.0.1", "--port", str(port), "--no-access-log"]


def _is_up(url: str, timeout: float = 1.5) -> bool:
    if not url:
        return False
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except Exception:  # noqa: BLE001
        return False


@dataclass
class Child:
    name: str
    argv: list[str]
    cwd: Path
    health: str            # full URL, or "" to skip
    env: dict = field(default_factory=dict)
    enabled: bool = True
    proc: subprocess.Popen | None = None
    adopted: bool = False  # already running before the hub started; don't spawn/stop

    def start(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        # ensure children can import the qfinzero package
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        env.update({k: str(v) for k, v in self.env.items()})
        log = open(LOG_DIR / f"{self.name}.log", "ab")
        self.proc = subprocess.Popen(
            self.argv, cwd=str(self.cwd), env=env, stdout=log, stderr=log,
            start_new_session=True,
        )

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout: float = 8.0) -> None:
        if not self.proc:
            return
        if self.proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass


def _default_children() -> list[Child]:
    upq_bin = REPO_ROOT / "infra/upq/target/release/upq-service"
    if not upq_bin.exists():
        upq_bin = REPO_ROOT / "infra/upq/target/debug/upq-service"

    children = [
        Child("upq", [str(upq_bin)], REPO_ROOT / "infra/upq",
              f"{UPQ_IN}/health",
              env={"PORT": config.UPQ_PORT, "STORAGE_ROOT": config.UPQ_STORAGE_ROOT},
              enabled=upq_bin.exists()),
        Child("esp", _uvicorn("main:app", config.ESP_PORT), REPO_ROOT / "infra/esp",
              f"{ESP_IN}/esp/health", env={"ESP_PORT": config.ESP_PORT}),
        Child("pmb", _uvicorn("main:app", config.PMB_PORT), REPO_ROOT / "infra/pmb",
              f"{PMB_IN}/v1/health",
              env={"PMB_PORT": config.PMB_PORT, "PMB_UPQ_BASE_URL": UPQ_IN}),
        Child("playground", _uvicorn("main:app", config.PLAYGROUND_PORT),
              REPO_ROOT / "infra/playground", f"{PLAYGROUND_IN}/health",
              env={"PLAYGROUND_PORT": config.PLAYGROUND_PORT,
                   "QFINZERO_UPQ_URL": UPQ_IN, "QFINZERO_ESP_URL": ESP_IN,
                   "QFINZERO_PMB_URL": PMB_IN}),
        Child("data-admin", _uvicorn("main:app", config.DATA_ADMIN_PORT),
              REPO_ROOT / "infra/data-admin", f"{DATA_ADMIN_IN}/health",
              env={"DATA_ADMIN_PORT": config.DATA_ADMIN_PORT}),
    ]

    # Web UI (Next.js) — opt-in and only if a build exists (needs Node).
    dash_dir = REPO_ROOT / "infra/dashboard-web"
    serve_ui = os.getenv("QFZ_SERVE_UI", "auto")
    ui_built = (dash_dir / ".next").is_dir()
    if serve_ui not in ("0", "false", "off") and ui_built:
        children.append(Child(
            "dashboard",
            [str(dash_dir / "node_modules/.bin/next"), "start", "-p", str(config.DASHBOARD_PORT)],
            dash_dir, f"{DASHBOARD_IN}/",
            env={"PORT": config.DASHBOARD_PORT, "PMB_BASE_URL": PMB_IN,
                 "ESP_BASE_URL": ESP_IN, "UPQ_BASE_URL": UPQ_IN,
                 "PLAYGROUND_SERVICE_URL": PLAYGROUND_IN,
                 "DATA_ADMIN_BASE_URL": DATA_ADMIN_IN}))
    return children


class Supervisor:
    def __init__(self, children: list[Child] | None = None):
        self.children = children if children is not None else _default_children()

    def start_all(self) -> None:
        for c in self.children:
            if not c.enabled:
                continue
            # If something is already serving this port (e.g. a service the user
            # started separately), adopt it instead of spawning a conflict.
            if _is_up(c.health):
                c.adopted = True
                continue
            c.start()

    def alive_or_adopted(self, c: Child) -> bool:
        return c.adopted or c.alive()

    def wait_healthy(self, timeout: float = 30.0) -> dict[str, bool]:
        deadline = time.time() + timeout
        active = [c for c in self.children if c.enabled and c.health]
        status: dict[str, bool] = {c.name: c.adopted for c in active}
        pending = [c for c in active if not c.adopted]
        while pending and time.time() < deadline:
            for c in list(pending):
                if not c.alive():
                    pending.remove(c)  # crashed — report unhealthy
                    continue
                try:
                    with urllib.request.urlopen(c.health, timeout=2) as r:
                        if r.status < 500:
                            status[c.name] = True
                            pending.remove(c)
                except Exception:  # noqa: BLE001
                    pass
            if pending:
                time.sleep(0.5)
        return status

    def stop_all(self) -> None:
        for c in reversed(self.children):
            c.stop()

    def child(self, name: str) -> Child | None:
        return next((c for c in self.children if c.name == name), None)
