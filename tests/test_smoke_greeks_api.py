"""Tests for the UPQ smoke Greeks API script defaults."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "infra/upq/tests/smoke_greeks_api.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("smoke_greeks_api_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_smoke_script_defaults_to_standard_upq_port(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(sys, "argv", ["smoke_greeks_api.py"])

    args = module.parse_args()

    assert args.host == "127.0.0.1"
    assert args.port == 19350
