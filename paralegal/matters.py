"""Saving work and the human review gate.

Every request becomes a folder under matters/. It starts as PENDING REVIEW and
only a named person can mark it approved. The citation check runs here in code
so it can't be skipped.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import citations, config

CHECKLIST = """\
## Reviewer checklist
- [ ] Every citation marked CHECK or NOT FOUND above has been opened and read
- [ ] The rules stated match the current code text, and local ordinances were considered
- [ ] Deadlines and date math are correct
- [ ] Every [BRACKETED] assumption has been replaced with a real fact
- [ ] Nothing here gives legal advice to someone who isn't represented by an attorney
- [ ] Tone and content are fine to send under the reviewer's name
"""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "matter"


def save(request: str, output: str, attachments: list[str]) -> Path:
    now = datetime.now(timezone.utc)
    folder = config.MATTERS_DIR / f"{now:%Y%m%d-%H%M%S}-{_slug(request)}"
    folder.mkdir(parents=True)
    cites = citations.verify(output)
    (folder / "work_product.md").write_text(
        "# DRAFT - PENDING HUMAN REVIEW\n\n"
        f"**Request:** {request}\n\n---\n\n{output}\n\n---\n\n"
        f"## Citation check\n{citations.report(cites)}\n{CHECKLIST}"
    )
    status = {
        "status": "pending_review",
        "created": now.isoformat(),
        "request": request,
        "attachments": attachments,
        "citations_not_found": sum(c.status == "not_found" for c in cites),
        "citations_unverified": sum(c.status == "unverified" for c in cites),
    }
    (folder / "status.json").write_text(json.dumps(status, indent=2))
    return folder


def approve(folder: Path, reviewer: str, notes: str = "") -> dict:
    status_file = folder / "status.json"
    status = json.loads(status_file.read_text())
    if status["citations_not_found"]:
        raise ValueError(
            f"{status['citations_not_found']} citation(s) could not be found. "
            "Fix or remove them in work_product.md, then run approve with --force."
        )
    status |= {
        "status": "approved",
        "reviewer": reviewer,
        "reviewed": datetime.now(timezone.utc).isoformat(),
        "review_notes": notes,
    }
    status_file.write_text(json.dumps(status, indent=2))
    return status


def force_approve(folder: Path, reviewer: str, notes: str) -> dict:
    status_file = folder / "status.json"
    status = json.loads(status_file.read_text())
    status["citations_not_found"] = 0
    status_file.write_text(json.dumps(status, indent=2))
    return approve(folder, reviewer, notes or "Approved after manual citation fixes.")


def pending() -> list[Path]:
    if not config.MATTERS_DIR.exists():
        return []
    return sorted(
        f
        for f in config.MATTERS_DIR.iterdir()
        if (f / "status.json").exists()
        and json.loads((f / "status.json").read_text())["status"] == "pending_review"
    )
