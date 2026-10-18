"""``qfz-auth`` — manage hub users and API keys from the shell.

    qfz-auth create-user alice --role admin          # prompts for a password
    qfz-auth list
    qfz-auth set-role alice researcher
    qfz-auth reset-password alice
    qfz-auth disable alice | enable alice
    qfz-auth create-key alice --name "eval runner"    # prints the key once
    qfz-auth revoke-key 3
    qfz-auth setup-token                              # token for the web /setup page
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from .store import ROLES, AuthError, AuthStore, ensure_setup_token


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
            meta, token = store.create_api_key(user(args.username).id, args.name)
            out = {"key": meta, "token": token, "note": "shown once; store it now"}
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
