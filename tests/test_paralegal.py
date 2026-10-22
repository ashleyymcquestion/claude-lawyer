import json
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest

from paralegal import citations, config, matters, team


def test_extracts_statutes_and_cases():
    text = (
        "Under Civil Code § 1950.5 and Code of Civil Procedure section 1161, "
        "see Green v. Superior Court (1974) 10 Cal.3d 616 and 123 Cal.App.4th 456. "
        "Civ. Code § 1950.5 again."
    )
    cites = citations.extract(text)
    statutes = [c for c in cites if c.kind == "statute"]
    cases = [c.text for c in cites if c.kind == "case"]
    assert len(statutes) == 2  # the repeat of 1950.5 is merged
    assert "lawCode=CIV&sectionNum=1950.5" in statutes[0].link
    assert "lawCode=CCP&sectionNum=1161" in statutes[1].link
    assert cases == ["10 Cal. 3d 616", "123 Cal. App. 4th 456"]


def test_short_cite_needs_a_full_cite():
    ok = citations.extract("Green v. Superior Court, 10 Cal.3d 616. Green, 10 Cal.3d at 630.")
    assert [c.text for c in ok] == ["10 Cal. 3d 616"]
    [orphan] = citations.extract("As held in Smith, 45 Cal.4th at 12.")
    assert "no full citation" in orphan.note


def test_cases_unverified_without_token(monkeypatch):
    monkeypatch.setattr(config, "COURTLISTENER_TOKEN", None)
    [c] = citations.verify("See 10 Cal.3d 616.")
    assert c.status == "unverified"
    assert "COURTLISTENER_API_TOKEN" in c.note


def test_courtlistener_results_mark_found_and_fake(monkeypatch):
    monkeypatch.setattr(config, "COURTLISTENER_TOKEN", "x")
    monkeypatch.setattr(
        citations,
        "_courtlistener_lookup",
        lambda _: [
            {"citation": "10 Cal.3d 616", "status": 200,
             "clusters": [{"case_name": "Green v. Superior Court", "absolute_url": "/opinion/1/green/"}]},
            {"citation": "999 Cal.App.4th 9999", "status": 404, "clusters": [], "error_message": ""},
        ],
    )
    real, fake = citations.verify("10 Cal.3d 616 and 999 Cal.App.4th 9999")
    assert real.status == "verified" and "Green" in real.note
    assert fake.status == "not_found"


def test_review_gate_blocks_fake_citations(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MATTERS_DIR", tmp_path)
    monkeypatch.setattr(config, "COURTLISTENER_TOKEN", "x")
    monkeypatch.setattr(
        citations, "_courtlistener_lookup",
        lambda _: [{"citation": "999 Cal.App.4th 9999", "status": 404, "clusters": []}],
    )
    folder = matters.save("deposit letter", "Per 999 Cal.App.4th 9999 ...", [])
    assert "PENDING HUMAN REVIEW" in (folder / "work_product.md").read_text()
    assert matters.pending() == [folder]
    with pytest.raises(ValueError):
        matters.approve(folder, "A. Reviewer")
    status = matters.force_approve(folder, "A. Reviewer", "removed bad cite")
    assert status["status"] == "approved"
    assert matters.pending() == []


class FakeClient:
    """Plays back scripted model responses and records each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(stream=self._stream))

    @contextmanager
    def _stream(self, **kwargs):
        self.requests.append(kwargs)
        yield NS(get_final_message=lambda: self.responses.pop(0))


def _text(t):
    return NS(stop_reason="end_turn", content=[NS(type="text", text=t)])


def _call(name, **args):
    return NS(stop_reason="tool_use", content=[NS(type="tool_use", id=f"id_{name}", name=name, input=args)])


def test_supervisor_delegates_to_researcher():
    client = FakeClient([
        _call("ask_legal_researcher", task="Deposit return deadline in CA?"),  # supervisor
        _text("Research memo: Civil Code § 1950.5 ..."),  # researcher
        _text("Final package for reviewer"),  # supervisor
    ])
    out = team.handle("How long does my landlord have to return my deposit?", client=client, log=lambda _: None)
    assert out == "Final package for reviewer"
    supervisor, researcher, supervisor_again = client.requests
    assert {t["name"] for t in supervisor["tools"]} >= {"ask_legal_researcher", "check_citations"}
    assert researcher["messages"][0]["content"][-1]["text"] == "Deposit return deadline in CA?"
    web = [t for t in researcher["tools"] if t["name"] == "web_search"][0]
    assert "leginfo.legislature.ca.gov" in web["allowed_domains"]
    # messages: request, supervisor's tool call, tool result, final answer
    tool_result = supervisor_again["messages"][2]["content"][0]
    assert "1950.5" in tool_result["content"]
    assert supervisor["fallbacks"] == "default"


def test_contract_reviewer_gets_attachment(tmp_path):
    lease = tmp_path / "lease.txt"
    lease.write_text("Tenant waives all repair rights.")
    client = FakeClient([
        _call("ask_contract_reviewer", task="Review the lease."),
        _text("Issue table"),
        _text("Done"),
    ])
    team.handle("Review my lease", [lease], client=client, log=lambda _: None)
    reviewer_content = client.requests[1]["messages"][0]["content"]
    assert reviewer_content[0]["source"]["data"] == "Tenant waives all repair rights."


def test_cli_saves_matter(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "MATTERS_DIR", tmp_path)
    monkeypatch.setattr(team, "handle", lambda *a, **k: "Draft letter")
    from paralegal import cli

    assert cli.main(["ask", "Draft a repair request"]) == 0
    [folder] = list(tmp_path.iterdir())
    assert json.loads((folder / "status.json").read_text())["status"] == "pending_review"


LEADS = """Property Address,City,Zip Code,Estimated Value,Building Sqft,Asking Price,Owner Occupied,Lists
1 Oak St,Fresno,93701,300000,1000,120000,No,Vacant
2 Elm St,Fresno,93701,300000,1000,200000,No,Absentee
3 Pine St,Fresno,93702,300000,1000,,Yes,Pre-Foreclosure
4 Ash St,Fresno,93701,80000,2000,,No,Vacant
"""

BUYERS = """Buyer Name,Phone,Zip,Cash Purchases,Max Price
Big Fund LLC,555-0001,93701,12,500000
Small Flipper,555-0002,93701,3,100000
Far Away Inc,555-0003,90210,40,900000
"""


def test_deal_math_and_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEALS_DIR", tmp_path / "out")
    leads, buyers = tmp_path / "leads.csv", tmp_path / "buyers.csv"
    leads.write_text(LEADS)
    buyers.write_text(BUYERS)
    from paralegal import deals

    folder = deals.run(leads, buyers, fee=10_000, rule=0.70)
    rows = {r["address"]: r for r in __import__("csv").DictReader((folder / "deals.csv").open())}
    oak = rows["1 Oak St"]
    # 300k x 70% - 1000 sqft x $55 = 155k buyer price, minus 10k fee
    assert (oak["status"], oak["buyer_price"], oak["max_offer"]) == ("offer", "155000", "145000")
    assert oak["matched_buyers"] == "Big Fund LLC"  # small flipper's cap too low, other is out of area
    assert rows["2 Elm St"]["status"] == "negotiate"
    assert rows["3 Pine St"]["status"] == "attorney"
    assert rows["4 Ash St"]["status"] == "skip"
    text = (folder / "report.md").read_text()
    assert "PENDING HUMAN REVIEW" in text and "1695" in text and "[ESTIMATED]" in text


def test_deals_inbox_processes_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEALS_DIR", tmp_path / "out")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "buyers.csv").write_text(BUYERS)
    (inbox / "fresno.csv").write_text(LEADS)
    from paralegal import cli

    assert cli.main(["deals", "--inbox", str(inbox)]) == 0
    assert (inbox / "done" / "fresno.csv").exists() and (inbox / "buyers.csv").exists()
    assert len(list((tmp_path / "out").iterdir())) == 1
    assert cli.main(["deals", "--inbox", str(inbox)]) == 0
    assert len(list((tmp_path / "out").iterdir())) == 1
