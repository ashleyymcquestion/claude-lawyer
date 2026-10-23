"""A tenant's case file: a payment log, a timeline and evidence, kept in cases/.

The summary is plain arithmetic over the payment log, so the totals that go to
a landlord or a small claims court never come from a model.
"""

from __future__ import annotations

import csv
import shutil
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import config

TEMPLATE = config.ROOT / "templates" / "tenant-case-file"


def new(name: str) -> Path:
    folder = config.CASES_DIR / name
    if folder.exists():
        raise ValueError(f"{folder} already exists")
    shutil.copytree(TEMPLATE, folder)
    return folder


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{k.strip().lower(): (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(f)]


def _date(text: str, where: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{where}: date {text!r} should look like 2026-08-01") from None


def _money(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def summary(folder: Path) -> str:
    payments = _rows(folder / "payment-log.csv")
    events = _rows(folder / "timeline.csv")

    totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    by_purpose: dict[str, dict[tuple[str, str], Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    problems = []
    for i, p in enumerate(payments, start=2):
        where = f"payment-log.csv line {i}"
        try:
            amount = Decimal(p.get("amount", "").replace("$", "").replace(",", ""))
            _date(p.get("date", ""), where)
        except (InvalidOperation, ValueError) as exc:
            problems.append(str(exc) if isinstance(exc, ValueError) else f"{where}: amount {p.get('amount')!r} is not a number")
            continue
        if not p.get("proof"):
            problems.append(f"{where}: no proof listed for {_money(amount)} on {p['date']}")
        pair = (p.get("from", "?"), p.get("to", "?"))
        totals[pair] += amount
        by_purpose[p.get("for") or "(not given)"][pair] += amount

    lines = ["# Case summary", "", "Totals come straight from payment-log.csv. Check them against the proof.", ""]
    lines += ["## Who paid whom", "", "| From | To | Total |", "| --- | --- | --- |"]
    lines += [f"| {a} | {b} | {_money(t)} |" for (a, b), t in sorted(totals.items())]
    lines += ["", "## By purpose", "", "| For | From | To | Amount |", "| --- | --- | --- | --- |"]
    for purpose in sorted(by_purpose):
        lines += [f"| {purpose} | {a} | {b} | {_money(t)} |" for (a, b), t in sorted(by_purpose[purpose].items())]

    lines += ["", "## Timeline", "", "| Date | What happened | Who | Proof |", "| --- | --- | --- | --- |"]
    dated = []
    for i, e in enumerate(events, start=2):
        try:
            dated.append((_date(e.get("date", ""), f"timeline.csv line {i}"), e))
        except ValueError as exc:
            problems.append(str(exc))
    for when, e in sorted(dated, key=lambda x: x[0]):
        lines.append(f"| {when} | {e.get('what happened', '')} | {e.get('who', '')} | {e.get('proof', '')} |")

    evidence = sorted(p.name for p in (folder / "evidence").glob("*") if p.name != ".gitkeep")
    lines += ["", "## Evidence files", ""] + ([f"- {n}" for n in evidence] or ["- (none yet)"])
    if problems:
        lines += ["", "## Fix before using", ""] + [f"- {p}" for p in problems]
    return "\n".join(lines) + "\n"
