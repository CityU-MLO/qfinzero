"""Minimal environment-file loader with explicit precedence."""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_env_defaults(path: str | Path) -> None:
    """Load KEY=VALUE pairs only when the variable is currently unset."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        os.environ[key] = _strip_quotes(value.strip())


def load_root_env_defaults() -> None:
    """Load root `.env` first, then checked-in fallback config if present."""
    load_env_defaults(REPO_ROOT / ".env")
    load_env_defaults(REPO_ROOT / "config" / "qfinzero.env")
