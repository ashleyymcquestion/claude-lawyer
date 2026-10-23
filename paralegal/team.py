"""The agent team.

A supervising associate takes each request and hands parts of it to
specialists. Every finished piece goes to a human for review; nothing is sent
to a client or filed by the team itself.

    supervising associate
      ├── legal researcher    (searches official California sources only)
      ├── contract reviewer   (reads leases and contracts you attach)
      ├── eviction analyst    (notices, eviction papers, rent and roommate disputes)
      ├── drafter             (letters, notices, agreements, checklists)
      ├── funding scout       (grants, loans, certifications for the LLC)
      └── citation checker    (plain code, see citations.py)
"""

from __future__ import annotations

import base64
from datetime import date
from pathlib import Path
from typing import Any, Callable

import anthropic

from . import citations, config, deadlines
from .llm import Agent, run_agent

GROUND_RULES = f"""\
You are part of a legal assistant team that supports a licensed attorney or a
business owner. You work like a strong paralegal or junior associate.
Jurisdiction: {config.JURISDICTION}, United States. Practice areas: landlord-tenant
and small business.

Rules that always apply:
- Your work is a draft for human review, never final advice. Never tell anyone
  to rely on it without review by a licensed California attorney.
- Cite only statutes, regulations and cases you actually found or were given in
  this conversation. Never cite from memory. If you can't find support, say so.
- Separate what the law says (with citations) from your judgment and from facts
  you are assuming. List missing facts as questions.
- Flag every deadline you see, with the date math and the rule it comes from.
- Flag anything that needs a lawyer right away: a lawsuit or eviction already
  filed, a court date, a lockout or utility shutoff, discrimination, or an
  injury.
- Check for local ordinances (city rent control, eviction rules) and say
  whether you checked them.
- Write in plain English a non-lawyer can follow.
"""


def _knowledge() -> str:
    parts = [p.read_text() for p in sorted(config.KNOWLEDGE_DIR.glob("*.md"))]
    return "\n\n".join(parts)


def _system(role: str) -> str:
    return f"{GROUND_RULES}\n## Your role\n{role}\n\n## Reference map\n{_knowledge()}"


def _tool(name: str, description: str, **props: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
            "required": list(props),
            "additionalProperties": False,
        },
    }


def _web_tools(domains: list[str] | None) -> list[dict[str, Any]]:
    search: dict[str, Any] = {"type": "web_search_20260209", "name": "web_search", "max_uses": 15}
    fetch: dict[str, Any] = {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 15}
    if domains:
        search["allowed_domains"] = domains
        fetch["allowed_domains"] = domains
    return [search, fetch]


def _deadline(args: dict[str, Any]) -> str:
    served = date.fromisoformat(args["served"])
    if args["kind"] == "notice":
        return deadlines.notice_expires(served).report()
    return deadlines.eviction_response(served, args["method"]).report()


DEADLINE_TOOL = (
    _tool(
        "calculate_deadline",
        "Work out an eviction deadline in code. Always use this instead of counting days yourself, "
        "and copy its report into your answer.",
        kind="'notice' for a 3-day notice, 'response' for court papers (summons and complaint).",
        served="Date served, YYYY-MM-DD.",
        method="For court papers: 'personal', 'substituted' or 'posting'. Use 'personal' for a notice.",
    ),
    _deadline,
)


def legal_researcher() -> Agent:
    return Agent(
        name="legal researcher",
        effort="high",
        server_tools=_web_tools(config.LEGAL_SOURCE_DOMAINS),
        system=_system(
            "Legal researcher. Find the current statutes, regulations, cases and "
            "official guidance that answer the question. Read the actual code "
            "section text on leginfo.legislature.ca.gov before stating a rule. "
            "Return a research memo: Question, Short answer, Rules (each with a "
            "citation and link), Local ordinances checked, Open questions, and "
            "How confident you are."
        ),
    )


def contract_reviewer() -> Agent:
    return Agent(
        name="contract reviewer",
        effort="high",
        server_tools=_web_tools(config.LEGAL_SOURCE_DOMAINS),
        system=_system(
            "Contract reviewer. Read the attached lease or contract closely. "
            "Return a table of issues: clause (quote it), what it means in plain "
            "English, risk level (high/medium/low), why (with a citation if a "
            "statute limits it, e.g. an illegal deposit amount or waiver of "
            "habitability), and a suggested rewrite. Then list missing clauses "
            "and anything that is unenforceable under California law."
        ),
    )


def eviction_analyst() -> Agent:
    return Agent(
        name="eviction analyst",
        effort="high",
        tools={"calculate_deadline": DEADLINE_TOOL},
        server_tools=_web_tools(config.LEGAL_SOURCE_DOMAINS),
        system=_system(
            "Eviction defense analyst for the tenant. Read every notice, summons, "
            "complaint, lease, receipt and message you are given, then work "
            "through this checklist in order and say what you found at each step:\n"
            "1. Stage and deadline: no notice yet, notice received, or court papers "
            "served. If court papers were served, put the response deadline first, "
            "with the service date and method, using the calculate_deadline tool "
            "(never count court days yourself). Same for a 3-day notice.\n"
            "2. Who is who: everyone on the lease, everyone living there, and "
            "whether each is a co-tenant, subtenant or occupant. Say who the "
            "landlord can hold responsible for the rent and why.\n"
            "3. The money: a ledger of rent due, what the tenant paid, to whom, "
            "how, and the proof for each payment. If rent went through a "
            "roommate or co-tenant who did not pay the landlord, show exactly "
            "where the money stopped.\n"
            "4. Notice defects: notice type and period, amount demanded (rent "
            "only, no fees), names and address, service method, required "
            "language (Code of Civil Procedure 1161-1162).\n"
            "5. Just cause and local rules: whether the Tenant Protection Act "
            "(Civil Code 1946.2) and any city rent or eviction ordinance cover "
            "the unit, and whether they were followed. Say which ones you checked.\n"
            "6. Defenses and leverage: retaliation, habitability, discrimination, "
            "waiver by accepting rent, payment or tender within the notice "
            "period, relief from forfeiture. For each: the facts that support it, "
            "the citation, and how strong it is (strong/possible/weak).\n"
            "7. Claims against others: what the tenant can recover from a "
            "roommate or anyone else who took the rent money (small claims "
            "court, demand letter first, the current small claims limit), and "
            "whether a police report fits the facts.\n"
            "8. Protect the tenant now: concrete steps for this week (pay the "
            "landlord directly with a receipt, tell the landlord in writing, "
            "preserve texts and payment app records, do not move out or stop "
            "responding without advice) and local legal aid to contact.\n"
            "If a case summary from the tenant's payment log is attached, use its "
            "totals as given and point out any gaps it lists. "
            "Finish with: an evidence list (what exists, what to get), a dated "
            "timeline, and the documents the drafter should prepare, each with "
            "its purpose and the facts it should use."
        ),
    )


def drafter() -> Agent:
    return Agent(
        name="drafter",
        effort="high",
        system=_system(
            "Drafter. Write the requested document (demand letter, notice, "
            "response, agreement, checklist) using only the facts and research "
            "you are given. Put every fact you had to assume in [BRACKETS] so "
            "the reviewer can fill it in. Mark the top 'DRAFT - NOT REVIEWED BY "
            "AN ATTORNEY'. Keep the tone firm and professional, never threatening."
        ),
    )


def funding_scout() -> Agent:
    return Agent(
        name="funding scout",
        effort="high",
        server_tools=_web_tools(None),
        system=_system(
            "Funding scout for small businesses. Find grants, low-cost loans, "
            "pitch competitions and certifications that fit the business you're "
            "told about. Only list programs whose official page you found, and "
            "give each one: name, amount, who qualifies, deadline (or 'rolling'), "
            "fees, official link, and fit (high/medium/low) with why. Say plainly "
            "when a program is closed or you couldn't confirm the date. Warn "
            "about grant scams: real grants don't charge large fees or ask for "
            "bank logins."
        ),
    )


def supervising_associate(
    attachments: list[dict[str, Any]],
    client: anthropic.Anthropic,
    log: Callable[[str], None],
) -> Agent:
    def delegate(agent_factory: Callable[[], Agent], with_attachments: bool = False):
        def handler(args: dict[str, Any]) -> str:
            log(f"   {args['task'][:100]}")
            content: list[dict[str, Any]] = list(attachments) if with_attachments else []
            content.append({"type": "text", "text": args["task"]})
            return run_agent(agent_factory(), content, client=client, log=log)

        return handler

    task = "Everything the specialist needs: the question or instructions, the facts, and any research to rely on."
    tools = {
        "ask_legal_researcher": (
            _tool("ask_legal_researcher", "Have the legal researcher find and read the governing law.", task=task),
            delegate(legal_researcher),
        ),
        "ask_contract_reviewer": (
            _tool(
                "ask_contract_reviewer",
                "Have the contract reviewer review the documents the user attached.",
                task=task,
            ),
            delegate(contract_reviewer, with_attachments=True),
        ),
        "ask_eviction_analyst": (
            _tool(
                "ask_eviction_analyst",
                "Have the eviction analyst work up a tenant's notice, eviction case, unpaid rent "
                "or roommate rent dispute, using any documents the user attached.",
                task=task,
            ),
            delegate(eviction_analyst, with_attachments=True),
        ),
        "ask_drafter": (
            _tool("ask_drafter", "Have the drafter write a document.", task=task),
            delegate(drafter),
        ),
        "ask_funding_scout": (
            _tool("ask_funding_scout", "Have the funding scout find grants, loans and certifications.", task=task),
            delegate(funding_scout),
        ),
        "check_citations": (
            _tool("check_citations", "Check every citation in a piece of text against real sources.", text="The text to check."),
            lambda args: citations.report(citations.verify(args["text"])),
        ),
    }
    return Agent(
        name="supervising associate",
        effort="high",
        tools=tools,
        max_turns=40,
        system=_system(
            "Supervising associate. You receive the request, plan the work, and "
            "delegate to specialists with complete instructions (they can't see "
            "this conversation). Typical flow: research first, then review or "
            "draft using that research, then run check_citations on the result. "
            "For a notice, eviction, unpaid rent or roommate rent problem, start "
            "with the eviction analyst, then have the drafter prepare each "
            "document the analyst lists. "
            "Fix or remove anything the check marks NOT FOUND. "
            "Finish with a package for the human reviewer:\n"
            "1. Summary (3-5 sentences)\n"
            "2. Urgent flags and deadlines\n"
            "3. The work product (memo, review table, or draft)\n"
            "4. Facts assumed and questions for the client\n"
            "5. What the reviewer must personally check before this is used"
        ),
    )


def load_attachment(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".pdf":
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return {
            "type": "document",
            "title": path.name,
            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
        }
    return {
        "type": "document",
        "title": path.name,
        "source": {"type": "text", "media_type": "text/plain", "data": path.read_text()},
    }


def handle(
    request: str,
    attachment_paths: list[Path] = (),
    client: anthropic.Anthropic | None = None,
    log: Callable[[str], None] = print,
) -> str:
    client = client or anthropic.Anthropic()
    attachments = [load_attachment(p) for p in attachment_paths]
    lead = supervising_associate(attachments, client, log)
    names = ", ".join(p.name for p in attachment_paths)
    prompt = request + (f"\n\nAttached for the contract reviewer and eviction analyst: {names}" if names else "")
    return run_agent(lead, prompt, client=client, log=log)
