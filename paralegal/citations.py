"""Find every legal citation in a draft and check it against real sources.

This is plain code, not an AI, so it can't be talked into approving a made-up
case. Anything it can't confirm is flagged for the human reviewer.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

import eyecite
from eyecite.models import FullCaseCitation, ShortCaseCitation

from . import config

# eyecite logs harmless "Unknown overlap case" warnings on dense legal text.
logging.getLogger("eyecite").setLevel(logging.ERROR)

# Code name as written -> leginfo lawCode.
CA_CODES = {
    "civil code": "CIV",
    "civ. code": "CIV",
    "code of civil procedure": "CCP",
    "code civ. proc.": "CCP",
    "ccp": "CCP",
    "government code": "GOV",
    "gov. code": "GOV",
    "corporations code": "CORP",
    "corp. code": "CORP",
    "revenue and taxation code": "RTC",
    "rev. & tax. code": "RTC",
    "health and safety code": "HSC",
    "health & saf. code": "HSC",
    "labor code": "LAB",
    "lab. code": "LAB",
    "business and professions code": "BPC",
    "bus. & prof. code": "BPC",
    "evidence code": "EVID",
    "evid. code": "EVID",
}

_code_names = "|".join(re.escape(k) for k in sorted(CA_CODES, key=len, reverse=True))
STATUTE_RE = re.compile(
    rf"\b({_code_names})\s*(?:§§?|sections?|sec\.)\s*(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)
# Case citations are found with eyecite (Free Law Project), which knows every
# US reporter abbreviation and spacing variant.


@dataclass
class Citation:
    kind: str  # "statute" or "case"
    text: str
    status: str = "unverified"  # verified | not_found | unverified
    link: str = ""
    note: str = ""


def extract(text: str) -> list[Citation]:
    found: dict[str, Citation] = {}
    for m in STATUTE_RE.finditer(text):
        code = CA_CODES[m.group(1).lower()]
        section = m.group(2)
        key = f"{code} {section}"
        if key not in found:
            found[key] = Citation(
                kind="statute",
                text=m.group(0),
                link=(
                    "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?"
                    + urllib.parse.urlencode({"lawCode": code, "sectionNum": section})
                ),
                note="Open the link and confirm the section says what the draft claims.",
            )
    cases = eyecite.get_citations(text)
    full = {
        (c.groups["volume"], _norm(c.groups["reporter"])) for c in cases if isinstance(c, FullCaseCitation)
    }
    for c in cases:
        if isinstance(c, FullCaseCitation):
            cite = c.corrected_citation()
            found.setdefault(cite, Citation(kind="case", text=cite))
        elif isinstance(c, ShortCaseCitation):
            # "10 Cal.3d at 630" should point back to a full citation in the draft.
            if (c.groups["volume"], _norm(c.groups["reporter"])) not in full:
                cite = c.matched_text()
                found.setdefault(
                    cite,
                    Citation(
                        kind="case",
                        text=cite,
                        note="Short-form cite with no full citation earlier in the draft.",
                    ),
                )
    return list(found.values())


def verify(text: str) -> list[Citation]:
    """Extract citations and check case citations with CourtListener."""
    cites = extract(text)
    # Orphaned short cites already carry a note and can't be looked up alone.
    cases = [c for c in cites if c.kind == "case" and not c.note]
    if not cases:
        return cites
    if not config.COURTLISTENER_TOKEN:
        for c in cases:
            c.note = "Not checked: set COURTLISTENER_API_TOKEN to verify cases automatically."
        return cites
    try:
        results = _courtlistener_lookup(" ; ".join(c.text for c in cases))
    except Exception as exc:
        for c in cases:
            c.note = f"Not checked: CourtListener lookup failed ({exc})."
        return cites
    by_cite = {}
    for r in results:
        for norm in r.get("normalized_citations") or [r.get("citation", "")]:
            by_cite[_norm(norm)] = r
        by_cite[_norm(r.get("citation", ""))] = r
    for c in cases:
        r = by_cite.get(_norm(c.text))
        if r is None:
            c.note = "CourtListener did not return a result for this citation."
        elif r.get("status") == 200 and r.get("clusters"):
            cluster = r["clusters"][0]
            c.status = "verified"
            c.link = "https://www.courtlistener.com" + cluster.get("absolute_url", "")
            c.note = f"Matches: {cluster.get('case_name', 'unknown case')}"
        else:
            c.status = "not_found"
            c.note = r.get("error_message") or "No case found with this citation. Possibly made up."
    return cites


def _norm(s: str) -> str:
    return re.sub(r"[\s.]", "", s).lower()


def _courtlistener_lookup(text: str) -> list[dict]:
    req = urllib.request.Request(
        "https://www.courtlistener.com/api/rest/v4/citation-lookup/",
        data=urllib.parse.urlencode({"text": text}).encode(),
        headers={"Authorization": f"Token {config.COURTLISTENER_TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def report(cites: list[Citation]) -> str:
    if not cites:
        return "No citations found in this draft.\n"
    icon = {"verified": "OK", "not_found": "NOT FOUND", "unverified": "CHECK"}
    lines = ["| Status | Citation | Note | Link |", "|---|---|---|---|"]
    for c in cites:
        lines.append(f"| {icon[c.status]} | {c.text} | {c.note} | {c.link} |")
    return "\n".join(lines) + "\n"
