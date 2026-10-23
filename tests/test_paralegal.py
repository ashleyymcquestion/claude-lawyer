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


def test_eviction_analyst_gets_notice_and_rules(tmp_path):
    notice = tmp_path / "notice.txt"
    notice.write_text("3-day notice to pay rent or quit: $2,400.")
    client = FakeClient([
        _call("ask_eviction_analyst", task="Roommate kept the rent. Work up the notice."),
        _text("Checklist and document list"),
        _text("Done"),
    ])
    team.handle("My roommate kept the rent money", [notice], client=client, log=lambda _: None)
    supervisor, analyst, _ = client.requests
    assert "ask_eviction_analyst" in {t["name"] for t in supervisor["tools"]}
    assert analyst["messages"][0]["content"][0]["source"]["data"].startswith("3-day notice")
    assert "relief from forfeiture" in analyst["system"]
    web = [t for t in analyst["tools"] if t["name"] == "web_search"][0]
    assert "leginfo.legislature.ca.gov" in web["allowed_domains"]


def test_response_deadline_counts_court_days():
    from datetime import date
    from paralegal import deadlines

    # Tuesday, no holidays: 10 court days later is Tuesday Nov 3.
    assert deadlines.eviction_response(date(2026, 10, 20)).safe_date == date(2026, 11, 3)
    # Veterans Day (Wed Nov 11) is skipped.
    assert deadlines.eviction_response(date(2026, 11, 5)).safe_date == date(2026, 11, 20)
    # Substituted service completes 10 calendar days later (Oct 30), then Nov 11 is skipped.
    assert deadlines.eviction_response(date(2026, 10, 20), "substituted").safe_date == date(2026, 11, 16)


def test_uncertain_holiday_gives_the_earlier_date():
    from datetime import date
    from paralegal import deadlines

    # July 4, 2026 is a Saturday; courts may close Friday July 3. Count it as open to be safe.
    d = deadlines.eviction_response(date(2026, 7, 2))
    assert (d.safe_date, d.possibly_later) == (date(2026, 7, 16), date(2026, 7, 17))
    assert "Thursday, July 16, 2026" in d.report()


def test_three_day_notice_skips_weekend():
    from datetime import date
    from paralegal import deadlines

    assert deadlines.notice_expires(date(2026, 10, 23)).safe_date == date(2026, 10, 28)


def test_case_file_totals_payments(tmp_path, monkeypatch):
    from paralegal import casefile

    monkeypatch.setattr(config, "CASES_DIR", tmp_path)
    folder = casefile.new("rent")
    (folder / "payment-log.csv").write_text(
        "date,from,to,amount,method,for,proof,notes\n"
        "2026-08-01,Me,Roommate,\"$1,200.00\",Venmo,rent 2026-08,venmo-aug.png,\n"
        "2026-09-01,Me,Roommate,1200,Zelle,rent 2026-09,,\n"
        "2026-09-03,Roommate,Landlord,500,check,rent 2026-09,ledger.pdf,\n"
        "bad,Me,Roommate,10,cash,,x,\n"
    )
    text = casefile.summary(folder)
    assert "| Me | Roommate | $2,400.00 |" in text
    assert "| Roommate | Landlord | $500.00 |" in text
    assert "line 3: no proof listed" in text
    assert "line 5: date 'bad'" in text
    with pytest.raises(ValueError):
        casefile.new("rent")


def test_cli_deadline(capsys):
    from paralegal import cli

    assert cli.main(["deadline", "--served", "2026-10-23", "--notice"]) == 0
    assert "Wednesday, October 28, 2026" in capsys.readouterr().out


def test_analyst_can_calculate_deadlines():
    analyst = team.eviction_analyst()
    report = analyst.tools["calculate_deadline"][1]({"kind": "response", "served": "2026-10-20", "method": "personal"})
    assert "Tuesday, November 3, 2026" in report
