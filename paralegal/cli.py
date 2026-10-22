"""Command line: python -m paralegal <command>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import matters, team


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paralegal", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="Give the team a task.")
    ask.add_argument("request", help='e.g. "My landlord kept my whole deposit. Draft a demand letter."')
    ask.add_argument("--attach", nargs="*", type=Path, default=[], help="Leases, contracts or notices (PDF or text).")

    sub.add_parser("pending", help="List work waiting for human review.")

    ok = sub.add_parser("approve", help="Mark a matter as reviewed and approved.")
    ok.add_argument("matter", type=Path)
    ok.add_argument("--reviewer", required=True, help="Name of the person who reviewed it.")
    ok.add_argument("--notes", default="")
    ok.add_argument("--force", action="store_true", help="Approve after you fixed NOT FOUND citations by hand.")

    args = parser.parse_args(argv)

    if args.command == "ask":
        for p in args.attach:
            if not p.exists():
                parser.error(f"file not found: {p}")
        output = team.handle(args.request, args.attach, log=lambda m: print(m, file=sys.stderr))
        folder = matters.save(args.request, output, [str(p) for p in args.attach])
        print(output)
        print(f"\nSaved for review: {folder / 'work_product.md'}", file=sys.stderr)
    elif args.command == "pending":
        items = matters.pending()
        print("\n".join(str(f) for f in items) or "Nothing waiting for review.")
    elif args.command == "approve":
        try:
            fn = matters.force_approve if args.force else matters.approve
            status = fn(args.matter, args.reviewer, args.notes)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Approved by {status['reviewer']} at {status['reviewed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
