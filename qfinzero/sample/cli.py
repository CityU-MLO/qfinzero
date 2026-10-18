"""``qfz-sample`` — generate the synthetic dataset."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qfz-sample", description="synthetic QFinZero dataset")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="write UPQ storage + ESP data to a directory")
    g.add_argument("--out", required=True, help="target directory (its upq/ and esp/ are replaced)")
    g.add_argument("--no-esp", action="store_true", help="market data only")
    args = ap.parse_args(argv)
    from . import generate
    print(json.dumps(generate(args.out, with_esp=not args.no_esp), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
