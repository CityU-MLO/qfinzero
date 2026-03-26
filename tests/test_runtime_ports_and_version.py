"""Tests for centralized QFinZero ports and version metadata."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parent.parent


def _reload_module(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def _load_module(module_name: str, relative_path: str, injected_modules: dict[str, ModuleType] | None = None):
    path = ROOT / relative_path
    injected_modules = injected_modules or {}
    previous = {}
    for name, module in injected_modules.items():
        previous[name] = sys.modules.get(name)
        sys.modules[name] = module

    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for name, module in injected_modules.items():
            original = previous[name]
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def test_default_port_allocation(monkeypatch):
    for env_name in [
        "QFZ_HOST",
        "PMB_PORT",
        "NPP_PORT",
        "UPQ_PORT",
        "DASHBOARD_PORT",
        "PLAYGROUND_PORT",
    ]:
        monkeypatch.delenv(env_name, raising=False)

    config = _reload_module("qfinzero.config")

    assert config.DEFAULT_HOST == "127.0.0.1"
    assert config.DASHBOARD_PORT == 19700
    assert config.PMB_PORT == 19701
    assert config.NPP_PORT == 19702
    assert config.UPQ_PORT == 19703
    assert config.PLAYGROUND_PORT == 19704
    assert config.PMB_URL == "http://127.0.0.1:19701"
    assert config.NPP_URL == "http://127.0.0.1:19702"
    assert config.UPQ_URL == "http://127.0.0.1:19703"
    assert config.PLAYGROUND_URL == "http://127.0.0.1:19704"


def test_qfinzero_version_uses_env_hash(monkeypatch):
    monkeypatch.delenv("QFINZERO_VERSION", raising=False)
    monkeypatch.setenv("QFINZERO_GIT_HASH", "deadbee")

    metadata = _reload_module("qfinzero.runtime")

    assert metadata.qfinzero_version() == "qfinzero:deadbee"


def test_qfinzero_version_env_override_wins(monkeypatch):
    monkeypatch.setenv("QFINZERO_VERSION", "qfinzero:custom")
    monkeypatch.setenv("QFINZERO_GIT_HASH", "deadbee")

    metadata = _reload_module("qfinzero.runtime")

    assert metadata.qfinzero_version() == "qfinzero:custom"


def test_pmb_health_includes_standard_version(monkeypatch):
    module = _load_module("pmb_health_route_test", "infra/pmb/routes/health.py")
    monkeypatch.setattr(module, "qfinzero_version", lambda: "qfinzero:deadbee", raising=False)

    payload = asyncio.run(module.health())

    assert payload == {
        "status": "ok",
        "service": "pmb",
        "version": "qfinzero:deadbee",
    }


def test_npp_health_includes_standard_version(monkeypatch):
    module = _load_module("npp_health_route_test", "infra/npp/routes/health.py")
    monkeypatch.setattr(module, "qfinzero_version", lambda: "qfinzero:deadbee", raising=False)

    class DummySources:
        async def get_freshness(self):
            return {"news": {"latest_timestamp": "2026-03-26T00:00:00Z"}}

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(data_sources=DummySources()))
    )

    payload = asyncio.run(module.health(request))

    assert payload["status"] == "ok"
    assert payload["service"] == "npp"
    assert payload["version"] == "qfinzero:deadbee"
    assert payload["data_freshness"] == {"news": {"latest_timestamp": "2026-03-26T00:00:00Z"}}


def test_playground_health_includes_standard_version(monkeypatch):
    fake_agent = ModuleType("agent")
    fake_agent.run_agent_stream = lambda **_: None
    fake_config = ModuleType("config")
    fake_config.HOST = "127.0.0.1"
    fake_config.PORT = 19704
    fake_sse_package = ModuleType("sse_starlette")
    fake_sse_module = ModuleType("sse_starlette.sse")

    class FakeEventSourceResponse:
        def __init__(self, *_args, **_kwargs):
            pass

    fake_sse_module.EventSourceResponse = FakeEventSourceResponse

    module = _load_module(
        "playground_main_test",
        "infra/playground/main.py",
        injected_modules={
            "agent": fake_agent,
            "config": fake_config,
            "sse_starlette": fake_sse_package,
            "sse_starlette.sse": fake_sse_module,
        },
    )
    monkeypatch.setattr(module, "qfinzero_version", lambda: "qfinzero:deadbee", raising=False)

    payload = asyncio.run(module.health())

    assert payload == {
        "status": "ok",
        "service": "playground",
        "version": "qfinzero:deadbee",
    }
