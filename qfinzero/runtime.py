"""Runtime metadata shared across QFinZero services."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache

from qfinzero.env import REPO_ROOT, load_root_env_defaults


load_root_env_defaults()


@lru_cache(maxsize=1)
def qfinzero_git_hash() -> str:
    explicit = os.getenv("QFINZERO_GIT_HASH")
    if explicit:
        return explicit

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"

    value = result.stdout.strip()
    return value or "unknown"


def qfinzero_version() -> str:
    explicit = os.getenv("QFINZERO_VERSION")
    if explicit:
        return explicit
    return f"qfinzero:{qfinzero_git_hash()}"
