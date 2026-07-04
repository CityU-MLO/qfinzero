"""PMB broker configuration — global defaults for accounts, fees, and pricing.

A single settings surface so an operator (or an agent's harness) can tune how the
paper broker behaves without editing code. Persisted at
``$QFZ_DATA_ROOT/_state/pmb.config.json`` so it survives restarts.
"""

from __future__ import annotations

import json
from pathlib import Path

from qfinzero import config as qcfg

# key -> (default, help). Only these keys are accepted from a PUT.
FIELDS: dict[str, tuple] = {
    "initial_cash": (100_000.0, "Starting cash for a new account"),
    "fee_per_share": (0.0, "Commission per share on every broker fill"),
    "option_fee_per_contract": (0.65, "Commission per option contract"),
    "slippage_bps": (1.0, "Slippage in basis points (session engine)"),
    "buying_power_multiplier": (2.0, "Leverage: buying power = equity × this"),
    "default_market": ("us", "Default market for new accounts (us|cn|hk)"),
    "default_frequency": ("1d", "Default bar frequency for sessions (1d|1m)"),
    "price_rule": ("close", "Broker-book fill price from UPQ: close | open"),
    "auto_price_from_upq": (True, "Fill trades at the real UPQ market price when the agent omits one"),
}
DEFAULTS = {k: v[0] for k, v in FIELDS.items()}

_PATH = Path(qcfg.QFZ_DATA_ROOT) / "_state" / "pmb.config.json"


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        if _PATH.is_file():
            stored = json.loads(_PATH.read_text())
            cfg.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def save(patch: dict) -> dict:
    cfg = load()
    for k, v in (patch or {}).items():
        if k in DEFAULTS and v is not None:
            cfg[k] = v
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(cfg, indent=2))
    return cfg


def describe() -> dict:
    """Config + field metadata for the settings UI."""
    return {
        "config": load(),
        "fields": {k: {"default": d, "help": h} for k, (d, h) in FIELDS.items()},
        "path": str(_PATH),
    }
