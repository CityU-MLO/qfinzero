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

API keys can be handed out narrower than their owner: a set of *scopes*
(which services the key may reach, see :data:`SCOPES`), read-only, an expiry
date and a rate limit. A key never exceeds its owner's role. Requests per key
and day are counted for the usage view.
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

# scope -> (path prefixes it opens to an API key, least owner role, description)
SCOPES: dict[str, tuple[tuple[str, ...], str, str]] = {
    "market-data": (("/svc/upq", "/api/upq", "/api/coverage"), "viewer", "UPQ prices, quotes, chains, futures"),
    "events": (("/svc/esp", "/api/esp"), "viewer", "ESP news, earnings and macro events"),
    "trading": (("/svc/pmb", "/api/pmb"), "researcher", "paper broker accounts, sessions and orders"),
    "mcp": (("/mcp",), "researcher", "the MCP endpoint; its tools follow the key's other scopes"),
    "chat": (("/api/playground", "/svc/playground"), "researcher", "the chat assistant"),
    "admin": (("/svc/data-admin", "/api/data-admin", "/auth/users", "/auth/keys", "/admin", "/data"), "admin",
              "data administration and user management"),
}
ALWAYS = ("/auth/me", "/auth/status", "/health", "/api/status", "/svc")


def key_allows(scopes: Optional[list[str]], read_only: bool, method: str, path: str) -> Optional[str]:
    """Why an API key may not make this request (``None`` if it may).
    ``scopes is None`` is a key from before scopes existed: everything."""
    # market data and event queries are reads even when POSTed (ESP takes JSON
    # bodies); MCP tools are checked one by one (mcp_tool_allows)
    query_only = SCOPES["market-data"][0] + SCOPES["events"][0] + SCOPES["mcp"][0]
    if read_only and method.upper() not in ("GET", "HEAD", "OPTIONS") and not path.startswith(query_only):
        return "this API key is read-only"
    if scopes is None or path in ALWAYS:
        return None
    for name in scopes:
        prefixes = SCOPES.get(name, ((), "", ""))[0]
        if path.startswith(prefixes):
            return None
    return "this API key's scopes do not include this service"


# MCP tool name prefix -> the scope it needs; read-only keys get only these pmb tools
MCP_TOOL_SCOPES = {"upq_": "market-data", "research_": "market-data", "data_": "market-data", "esp_": "events",
                   "pmb_": "trading", "admin_": "admin"}
MCP_READ_TOOLS = ("pmb_health", "pmb_get_", "pmb_quote", "pmb_session_state", "pmb_export_session")


def mcp_tool_allows(scopes: Optional[list[str]], read_only: bool, tool: str) -> Optional[str]:
    """Why an API key may not call this MCP tool (``None`` if it may)."""
    need = next((sc for pre, sc in MCP_TOOL_SCOPES.items() if tool.startswith(pre)), None)
    if scopes is not None and need is not None and need not in scopes:
        return f"this API key lacks the {need} scope needed by {tool}"
    if read_only and tool.startswith("pmb_") and not tool.startswith(MCP_READ_TOOLS):
        return f"this API key is read-only; {tool} changes state"
    return None
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
CREATE TABLE IF NOT EXISTS api_key_usage (
    key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    requests INTEGER NOT NULL DEFAULT 0,
    denied INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (key_id, day)
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
            have = {r[1] for r in c.execute("PRAGMA table_info(api_keys)")}
            for col, ddl in (("scopes", "TEXT"), ("read_only", "INTEGER NOT NULL DEFAULT 0"),
                             ("expires_at", "REAL"), ("rate_per_min", "INTEGER"), ("note", "TEXT"),
                             ("created_by", "TEXT")):
                if col not in have:
                    c.execute(f"ALTER TABLE api_keys ADD COLUMN {col} {ddl}")
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

    def _check_scopes(self, user_id: int, scopes: Optional[list[str]]) -> Optional[list[str]]:
        if scopes is None:
            return None
        user = self.get_user(user_id)
        if user is None:
            raise AuthError("user not found")
        bad = [x for x in scopes if x not in SCOPES]
        if bad:
            raise AuthError(f"unknown scopes: {', '.join(bad)}")
        over = [x for x in scopes if not user.at_least(SCOPES[x][1])]
        if over:
            raise AuthError(f"the {user.role} role cannot hold scopes: {', '.join(over)}")
        if not scopes:
            raise AuthError("choose at least one scope")
        return sorted(set(scopes))

    def create_api_key(self, user_id: int, name: str, *, scopes: Optional[list[str]] = None,
                       read_only: bool = False, expires_at: Optional[float] = None,
                       rate_per_min: Optional[int] = None, note: str = "",
                       created_by: Optional[str] = None) -> tuple[dict, str]:
        name = (name or "").strip()[:80] or "key"
        scopes = self._check_scopes(user_id, scopes)
        prefix = secrets.token_hex(4)
        token = f"{KEY_PREFIX}{prefix}_{secrets.token_urlsafe(32)}"
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO api_keys (user_id, name, prefix, key_hash, created_at, scopes, read_only, expires_at, "
                "rate_per_min, note, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, name, prefix, self._digest(token), time.time(),
                 json.dumps(scopes) if scopes is not None else None, int(bool(read_only)), expires_at,
                 int(rate_per_min) if rate_per_min else None, (note or "")[:300], created_by))
            key_id = cur.lastrowid
        return self.get_api_key(key_id), token

    def update_api_key(self, key_id: int, *, user_id: Optional[int] = None, **fields) -> dict:
        """Change a key's name, scopes, read-only flag, expiry or rate limit
        (``user_id`` restricts to that owner)."""
        k = self.get_api_key(key_id)
        if k is None or (user_id is not None and k["user_id"] != user_id):
            raise AuthError("key not found")
        sets: dict = {}
        if "name" in fields:
            sets["name"] = (str(fields["name"] or "").strip()[:80] or k["name"])
        if "scopes" in fields:
            sc = self._check_scopes(k["user_id"], fields["scopes"])
            sets["scopes"] = json.dumps(sc) if sc is not None else None
        if "read_only" in fields:
            sets["read_only"] = int(bool(fields["read_only"]))
        if "expires_at" in fields:
            sets["expires_at"] = fields["expires_at"]
        if "rate_per_min" in fields:
            sets["rate_per_min"] = int(fields["rate_per_min"]) if fields["rate_per_min"] else None
        if "note" in fields:
            sets["note"] = str(fields["note"] or "")[:300]
        if sets:
            with self._lock, self._conn() as c:
                c.execute(f"UPDATE api_keys SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                          (*sets.values(), key_id))
        return self.get_api_key(key_id)

    @staticmethod
    def _key_row(r) -> dict:
        exp = r["expires_at"]
        return {"id": r["id"], "user_id": r["user_id"], "name": r["name"], "prefix": f"{KEY_PREFIX}{r['prefix']}",
                "created_at": r["created_at"], "last_used_at": r["last_used_at"],
                "revoked": bool(r["revoked"]), "username": r["username"],
                "scopes": json.loads(r["scopes"]) if r["scopes"] else None,
                "read_only": bool(r["read_only"]), "expires_at": exp,
                "expired": bool(exp and exp < time.time()), "rate_per_min": r["rate_per_min"],
                "note": r["note"] or "", "created_by": r["created_by"]}

    _KEY_SQL = ("SELECT k.*, u.username FROM api_keys k JOIN users u ON u.id = k.user_id")

    def get_api_key(self, key_id: int) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(self._KEY_SQL + " WHERE k.id = ?", (key_id,)).fetchone()
        return self._key_row(r) if r else None

    def list_api_keys(self, user_id: Optional[int] = None, usage_days: int = 14) -> list[dict]:
        sql, args = self._KEY_SQL, ()
        if user_id is not None:
            sql += " WHERE k.user_id = ?"
            args = (user_id,)
        since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - usage_days * 86400))
        with self._conn() as c:
            keys = [self._key_row(r) for r in c.execute(sql + " ORDER BY k.id", args)]
            use: dict[int, dict[str, list]] = {}
            for r in c.execute("SELECT key_id, day, requests, denied FROM api_key_usage WHERE day >= ?", (since,)):
                use.setdefault(r["key_id"], {})[r["day"]] = [r["requests"], r["denied"]]
        for k in keys:
            u = use.get(k["id"], {})
            k["usage"] = [{"day": d, "requests": v[0], "denied": v[1]} for d, v in sorted(u.items())]
            k["requests_total"] = sum(v[0] for v in u.values())
        return keys

    def add_usage(self, counts: dict[tuple[int, str], list[int]]) -> None:
        """Add ``{(key_id, day): [requests, denied]}`` to the usage table."""
        if not counts:
            return
        with self._lock, self._conn() as c:
            for (kid, day), (n, d) in counts.items():
                c.execute("INSERT INTO api_key_usage (key_id, day, requests, denied) VALUES (?, ?, ?, ?) "
                          "ON CONFLICT(key_id, day) DO UPDATE SET requests = requests + excluded.requests, "
                          "denied = denied + excluded.denied", (kid, day, n, d))

    def revoke_api_key(self, key_id: int, user_id: Optional[int] = None) -> None:
        sql, args = "UPDATE api_keys SET revoked = 1 WHERE id = ?", [key_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            args.append(user_id)
        with self._lock, self._conn() as c:
            if c.execute(sql, args).rowcount == 0:
                raise AuthError("key not found")

    def verify_api_key(self, token: str) -> Optional[User]:
        found = self.verify_api_key_full(token)
        return found[0] if found else None

    def verify_api_key_full(self, token: str) -> Optional[tuple[User, dict]]:
        """``(owner, key)`` for a live (not revoked, not expired) key."""
        if not token or not token.startswith(KEY_PREFIX):
            return None
        with self._conn() as c:
            row = c.execute(
                "SELECT k.id AS kid, k.last_used_at, k.scopes, k.read_only, k.expires_at, k.rate_per_min, "
                "u.* FROM api_keys k JOIN users u ON u.id = k.user_id "
                "WHERE k.key_hash = ? AND k.revoked = 0", (self._digest(token),)).fetchone()
        if row is None or row["disabled"]:
            return None
        now = time.time()
        if row["expires_at"] and row["expires_at"] < now:
            return None
        if not row["last_used_at"] or now - row["last_used_at"] > 60:   # cheap, coarse
            with self._lock, self._conn() as c:
                c.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["kid"]))
        key = {"id": row["kid"], "scopes": json.loads(row["scopes"]) if row["scopes"] else None,
               "read_only": bool(row["read_only"]), "rate_per_min": row["rate_per_min"]}
        return self._user(row), key


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
