"""Users, roles, API keys and signed browser sessions (stdlib only).

* Users and API keys live in SQLite at ``$QFZ_DATA_ROOT/_state/auth.sqlite3``
  (``QFZ_AUTH_DB`` overrides). Passwords are hashed with scrypt; API keys are
  stored as SHA-256 digests and shown in the clear exactly once.
* Browser sessions are HMAC-signed cookies carrying the user id, role and a
  per-user *session version*; changing a password or disabling a user bumps
  the version, which invalidates every outstanding cookie.
* The signing secret comes from ``QFZ_SECRET_KEY`` or is generated once into
  ``_state/auth_secret`` (mode 0600).

Roles, from least to most: ``viewer`` (read only), ``researcher`` (trade,
research, MCP), ``admin`` (also data administration and user management).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROLES = ("viewer", "researcher", "admin")
ROLE_RANK = {r: i for i, r in enumerate(ROLES)}
KEY_PREFIX = "qfz_"
_USERNAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789._-@")


def _state_dir() -> Path:
    root = os.environ.get("QFZ_DATA_ROOT", "/data/qfinzero")
    return Path(os.environ.get("QFZ_STATE_DIR", f"{root}/_state"))


def default_db_path() -> Path:
    return Path(os.environ.get("QFZ_AUTH_DB", str(_state_dir() / "auth.sqlite3")))


# ── passwords ────────────────────────────────────────────────────────────

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt${n}${r}${p}${s}${h}".format(
        s=base64.b64encode(salt).decode(), h=base64.b64encode(dk).decode(), **_SCRYPT)


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32,
                            n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(dk, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def check_password_strength(password: str) -> Optional[str]:
    if len(password or "") < 10:
        return "password must be at least 10 characters"
    return None


# ── the store ────────────────────────────────────────────────────────────

@dataclass
class User:
    id: int
    username: str
    role: str
    display_name: str = ""
    disabled: bool = False
    session_version: int = 1
    created_at: float = 0.0
    last_login_at: Optional[float] = None

    def public(self) -> dict:
        return {"id": self.id, "username": self.username, "role": self.role,
                "display_name": self.display_name or self.username, "disabled": self.disabled,
                "created_at": self.created_at, "last_login_at": self.last_login_at}

    def at_least(self, role: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK[role]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    session_version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    last_login_at REAL
);
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL,
    key_hash TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL,
    last_used_at REAL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL, actor TEXT, action TEXT NOT NULL, detail TEXT
);
"""


class AuthError(ValueError):
    """A user-facing auth failure (bad input, conflict, not found)."""


class AuthStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._conn() as c:
            c.executescript(_SCHEMA)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    @staticmethod
    def _user(row) -> Optional[User]:
        if row is None:
            return None
        return User(id=row["id"], username=row["username"], role=row["role"],
                    display_name=row["display_name"], disabled=bool(row["disabled"]),
                    session_version=row["session_version"], created_at=row["created_at"],
                    last_login_at=row["last_login_at"])

    def audit(self, actor: Optional[str], action: str, detail: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO audit (ts, actor, action, detail) VALUES (?, ?, ?, ?)",
                      (time.time(), actor, action, detail[:500]))

    # users
    def count_users(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT count(*) FROM users").fetchone()[0])

    def create_user(self, username: str, password: str, role: str = "researcher",
                    display_name: str = "") -> User:
        username = (username or "").strip().lower()
        if not username or len(username) > 64 or set(username) - _USERNAME_OK:
            raise AuthError("username: 1-64 chars of a-z 0-9 . _ - @")
        if role not in ROLES:
            raise AuthError(f"role must be one of {ROLES}")
        weak = check_password_strength(password)
        if weak:
            raise AuthError(weak)
        with self._lock, self._conn() as c:
            try:
                cur = c.execute(
                    "INSERT INTO users (username, display_name, password_hash, role, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (username, display_name or "", hash_password(password), role, time.time()))
            except sqlite3.IntegrityError as e:
                raise AuthError(f"user {username!r} already exists") from e
            user_id = cur.lastrowid
        return self.get_user(user_id)            # after the commit

    def get_user(self, user_id: int) -> Optional[User]:
        with self._conn() as c:
            return self._user(c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def find_user(self, username: str) -> Optional[User]:
        with self._conn() as c:
            return self._user(c.execute("SELECT * FROM users WHERE username = ?",
                                        ((username or "").strip().lower(),)).fetchone())

    def list_users(self) -> list[User]:
        with self._conn() as c:
            return [self._user(r) for r in c.execute("SELECT * FROM users ORDER BY id")]

    def authenticate(self, username: str, password: str) -> Optional[User]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE username = ?",
                            ((username or "").strip().lower(),)).fetchone()
        if row is None:
            hash_password("timing-equaliser")         # same cost as a real check
            return None
        if not verify_password(password or "", row["password_hash"]) or row["disabled"]:
            return None
        with self._lock, self._conn() as c:
            c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (time.time(), row["id"]))
        return self.get_user(row["id"])

    def update_user(self, user_id: int, *, role: Optional[str] = None,
                    disabled: Optional[bool] = None, display_name: Optional[str] = None) -> User:
        user = self.get_user(user_id)
        if user is None:
            raise AuthError("user not found")
        if role is not None and role not in ROLES:
            raise AuthError(f"role must be one of {ROLES}")
        if user.role == "admin" and (role not in (None, "admin") or disabled):
            if sum(1 for u in self.list_users() if u.role == "admin" and not u.disabled) <= 1:
                raise AuthError("cannot demote or disable the last admin")
        with self._lock, self._conn() as c:
            if role is not None:
                c.execute("UPDATE users SET role = ?, session_version = session_version + 1 "
                          "WHERE id = ?", (role, user_id))
            if disabled is not None:
                c.execute("UPDATE users SET disabled = ?, session_version = session_version + 1 "
                          "WHERE id = ?", (int(disabled), user_id))
            if display_name is not None:
                c.execute("UPDATE users SET display_name = ? WHERE id = ?",
                          (display_name[:120], user_id))
        return self.get_user(user_id)

    def set_password(self, user_id: int, password: str) -> None:
        weak = check_password_strength(password)
        if weak:
            raise AuthError(weak)
        with self._lock, self._conn() as c:
            c.execute("UPDATE users SET password_hash = ?, session_version = session_version + 1 "
                      "WHERE id = ?", (hash_password(password), user_id))

    def delete_user(self, user_id: int) -> None:
        user = self.get_user(user_id)
        if user is None:
            raise AuthError("user not found")
        if user.role == "admin" and sum(1 for u in self.list_users() if u.role == "admin") <= 1:
            raise AuthError("cannot delete the last admin")
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))

    # API keys
    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_api_key(self, user_id: int, name: str) -> tuple[dict, str]:
        name = (name or "").strip()[:80] or "key"
        prefix = secrets.token_hex(4)
        token = f"{KEY_PREFIX}{prefix}_{secrets.token_urlsafe(32)}"
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO api_keys (user_id, name, prefix, key_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, name, prefix, self._digest(token), time.time()))
            key_id = cur.lastrowid
        return {"id": key_id, "name": name, "prefix": f"{KEY_PREFIX}{prefix}"}, token

    def list_api_keys(self, user_id: Optional[int] = None) -> list[dict]:
        sql = ("SELECT k.id, k.name, k.prefix, k.created_at, k.last_used_at, k.revoked, "
               "u.username FROM api_keys k JOIN users u ON u.id = k.user_id")
        args: tuple = ()
        if user_id is not None:
            sql += " WHERE k.user_id = ?"
            args = (user_id,)
        with self._conn() as c:
            return [{"id": r["id"], "name": r["name"], "prefix": f"{KEY_PREFIX}{r['prefix']}",
                     "created_at": r["created_at"], "last_used_at": r["last_used_at"],
                     "revoked": bool(r["revoked"]), "username": r["username"]}
                    for r in c.execute(sql + " ORDER BY k.id", args)]

    def revoke_api_key(self, key_id: int, user_id: Optional[int] = None) -> None:
        sql, args = "UPDATE api_keys SET revoked = 1 WHERE id = ?", [key_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            args.append(user_id)
        with self._lock, self._conn() as c:
            if c.execute(sql, args).rowcount == 0:
                raise AuthError("key not found")

    def verify_api_key(self, token: str) -> Optional[User]:
        if not token or not token.startswith(KEY_PREFIX):
            return None
        with self._conn() as c:
            row = c.execute(
                "SELECT k.id AS kid, k.last_used_at, u.* FROM api_keys k JOIN users u ON u.id = k.user_id "
                "WHERE k.key_hash = ? AND k.revoked = 0", (self._digest(token),)).fetchone()
        if row is None or row["disabled"]:
            return None
        now = time.time()
        if not row["last_used_at"] or now - row["last_used_at"] > 60:   # cheap, coarse
            with self._lock, self._conn() as c:
                c.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["kid"]))
        return self._user(row)


# ── signed session cookies ──────────────────────────────────────────────

def load_secret() -> bytes:
    env = os.environ.get("QFZ_SECRET_KEY", "").strip()
    if env:
        return env.encode()
    path = _state_dir() / "auth_secret"
    try:
        return path.read_bytes().strip()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_urlsafe(48).encode()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(secret)
        return secret


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_session(secret: bytes, user: User, ttl_s: int) -> str:
    payload = json.dumps({"u": user.id, "v": user.session_version,
                          "exp": int(time.time()) + int(ttl_s)}, separators=(",", ":")).encode()
    sig = hmac.new(secret, payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(sig)}"


def read_session(secret: bytes, token: str) -> Optional[dict]:
    try:
        p, s = token.split(".", 1)
        payload = _unb64(p)
        if not hmac.compare_digest(_unb64(s), hmac.new(secret, payload, hashlib.sha256).digest()):
            return None
        data = json.loads(payload)
        if int(data.get("exp", 0)) < time.time():
            return None
        return data
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def setup_token_path() -> Path:
    return _state_dir() / "setup_token"


def ensure_setup_token() -> str:
    """One-time token that authorises creating the first admin from the web."""
    path = setup_token_path()
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(18)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token)
        return token
