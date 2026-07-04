"""Per-domain advisory file lock.

Prevents two QFinZero updates (e.g. a cron run and a Data-tab button) from
converting the same domain concurrently. Advisory only — it does not, and does
not need to, coordinate with Assay, because QFinZero and Assay write to disjoint
targets (Assay → raw stock files; QFinZero → derived stores).
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
from pathlib import Path

from .manifest import STATE_DIRNAME


class LockBusy(RuntimeError):
    """Raised when a non-blocking lock cannot be acquired."""


@contextlib.contextmanager
def domain_lock(storage_root: Path, domain: str, blocking: bool = False):
    """Acquire an advisory lock for ``domain`` under the storage state dir."""
    lock_dir = Path(storage_root) / STATE_DIRNAME / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{domain}.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    flags = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        try:
            fcntl.flock(fd, flags)
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EAGAIN):
                raise LockBusy(f"another update is running for domain '{domain}'") from e
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        yield lock_path
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
