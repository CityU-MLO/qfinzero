"""``qfz-auth`` — manage hub users and API keys from the shell.

    qfz-auth create-user alice --role admin          # prompts for a password
    qfz-auth list
    qfz-auth set-role alice researcher
    qfz-auth reset-password alice
    qfz-auth disable alice | enable alice
    qfz-auth create-key alice --name "eval runner"    # prints the token
    qfz-auth show-key 3                               # prints it again
    qfz-auth create-key bob --scopes market-data,events --read-only --expires-days 30 --rate 600
    qfz-auth revoke-key 3
    qfz-auth setup-token                              # token for the web /setup page
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time

from .store import ROLES, SCOPES, AuthError, AuthStore, ensure_setup_token


def _password(args) -> str:
    if getattr(args, "password_stdin", False):
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("password: ")
    if first != getpass.getpass("again: "):
        raise AuthError("passwords do not match")
    return first


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qfz-auth", description="manage QFinZero hub users")
    ap.add_argument("--db", help="override QFZ_AUTH_DB")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("username")
    c.add_argument("--role", choices=ROLES, default="researcher")
    c.add_argument("--display-name", default="")
    c.add_argument("--password-stdin", action="store_true")
    sub.add_parser("list")
    sr = sub.add_parser("set-role")
    sr.add_argument("username")
    sr.add_argument("role", choices=ROLES)
    rp = sub.add_parser("reset-password")
    rp.add_argument("username")
    rp.add_argument("--password-stdin", action="store_true")
    for name in ("disable", "enable", "delete"):
        sub.add_parser(name).add_argument("username")
    ck = sub.add_parser("create-key")
    ck.add_argument("username")
    ck.add_argument("--name", default="cli")
    ck.add_argument("--scopes", help=f"comma-separated, from: {', '.join(SCOPES)} (default: all)")
    ck.add_argument("--read-only", action="store_true")
    ck.add_argument("--expires-days", type=float)
    ck.add_argument("--rate", type=int, help="requests per minute")
    ck.add_argument("--note", default="")
    sub.add_parser("show-key").add_argument("key_id", type=int)
    sub.add_parser("revoke-key").add_argument("key_id", type=int)
    sub.add_parser("setup-token")
    args = ap.parse_args(argv)
    store = AuthStore(args.db)

    def user(name):
        u = store.find_user(name)
        if u is None:
            raise AuthError(f"no user {name!r}")
        return u

    try:
        if args.cmd == "create-user":
            u = store.create_user(args.username, _password(args), args.role, args.display_name)
            out = {"created": u.public()}
        elif args.cmd == "list":
            out = {"users": [u.public() for u in store.list_users()], "keys": store.list_api_keys()}
        elif args.cmd == "set-role":
            out = {"user": store.update_user(user(args.username).id, role=args.role).public()}
        elif args.cmd == "reset-password":
            store.set_password(user(args.username).id, _password(args))
            out = {"ok": True}
        elif args.cmd in ("disable", "enable"):
            out = {"user": store.update_user(user(args.username).id,
                                             disabled=args.cmd == "disable").public()}
        elif args.cmd == "delete":
            store.delete_user(user(args.username).id)
            out = {"ok": True}
        elif args.cmd == "create-key":
            meta, token = store.create_api_key(
                user(args.username).id, args.name,
                scopes=[x.strip() for x in args.scopes.split(",") if x.strip()] if args.scopes else None,
                read_only=args.read_only, rate_per_min=args.rate, note=args.note, created_by="cli",
                expires_at=time.time() + args.expires_days * 86400 if args.expires_days else None)
            out = {"key": meta, "token": token}
        elif args.cmd == "show-key":
            out = {"key": store.get_api_key(args.key_id), "token": store.reveal_api_key(args.key_id)}
            store.audit("cli", "key_revealed", str(args.key_id))
        elif args.cmd == "revoke-key":
            store.revoke_api_key(args.key_id)
            out = {"ok": True}
        else:
            out = {"setup_token": ensure_setup_token(),
                   "note": "enter it on /setup to create the first admin"}
    except AuthError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
