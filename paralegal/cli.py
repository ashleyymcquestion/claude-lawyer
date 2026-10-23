"""Command line: python -m paralegal <command>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from datetime import date

from . import casefile, deadlines, matters, team


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

    dl = sub.add_parser("deadline", help="Work out an eviction deadline in plain code.")
    dl.add_argument("--served", required=True, type=date.fromisoformat, help="Date served, YYYY-MM-DD.")
    dl.add_argument("--notice", action="store_true", help="A 3-day notice, not court papers.")
    dl.add_argument("--method", choices=list(deadlines.SERVICE_DELAY_DAYS), default="personal",
                    help="How court papers were served (personal = handed to you).")

    case = sub.add_parser("case", help="A tenant case file: payment log, timeline, evidence.")
    case_sub = case.add_subparsers(dest="case_command", required=True)
    case_sub.add_parser("new", help="Start a case file in cases/.").add_argument("name")
    case_sub.add_parser("summary", help="Total the payment log and list the timeline.").add_argument("folder", type=Path)

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
    elif args.command == "deadline":
        d = deadlines.notice_expires(args.served) if args.notice else deadlines.eviction_response(args.served, args.method)
        print(d.report())
    elif args.command == "case" and args.case_command == "new":
        try:
            folder = casefile.new(args.name)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Started {folder}. Open {folder / 'README.md'} to see what goes where.")
    elif args.command == "case":
        try:
            text = casefile.summary(args.folder)
        except (FileNotFoundError, ValueError) as exc:
            print(exc, file=sys.stderr)
            return 1
        (args.folder / "summary.md").write_text(text)
        print(text)
        print(f"Saved {args.folder / 'summary.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
