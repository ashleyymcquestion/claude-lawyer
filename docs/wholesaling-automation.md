# Automating a wholesaling business (California)

> Not legal advice. Have a California real estate attorney approve your purchase
> contract, assignment agreement and seller disclosure before your first deal.

## What gets automated and what doesn't

| Step | Automated? | How |
|---|---|---|
| 1. Pull motivated-seller leads | Mostly | Saved searches in PropStream / DealMachine / BatchLeads, exported to CSV |
| 2. Run the numbers on every lead | **Yes** | `paralegal deals` (this repo) |
| 3. Match each deal to cash buyers | **Yes** | Same command, with a cash-buyer export |
| 4. Contact sellers | Partly | Mail campaigns can run on autopilot. Calls you make yourself. **No AI-voice calls or automated texts** without prior express written consent (TCPA: $500–$1,500 per call) |
| 5. Send the offer / sign the contract | **No, you** | You check comps and repairs, then send the attorney-approved contract |
| 6. Send the deal to buyers | Partly | Email the matched buyers about the *contract*, not the house (B&P 10131) |
| 7. Close | No | Title / escrow company |

The rule: software can find, sort and draft. A person approves anything that
goes to a seller and signs anything binding.

## Daily pipeline

1. In your lead tool, save a search for your county: vacant, absentee owner,
   inherited/probate, tax delinquent, high equity. Leave out pre-foreclosure
   until your attorney gives you a Civil Code 1695 contract.
2. Export your cash buyers (filter: cash purchase in the last 12 months, your
   county) and save it as `inbox/buyers.csv`. Refresh it monthly.
3. Drop each new lead export into `inbox/`.
4. A scheduled job runs:
   ```
   python -m paralegal deals --inbox inbox --fee 10000
   ```
   Every new CSV is scored and moved to `inbox/done/`. Each run makes
   `deals/<date>-<file>/report.md` (ranked list) and `deals.csv` (for your CRM
   or a spreadsheet).
5. Each morning, read the report top down. **OFFER** = numbers work at the
   seller's price. **NEGOTIATE** = seller is above your max. **ATTORNEY** =
   foreclosure, owner may live there. Skipped leads are in the CSV only.

### Scheduling it

Mac or Linux: run `crontab -e` and add (7am daily):
```
0 7 * * * cd /path/to/claude-lawyer && .venv/bin/python -m paralegal deals --inbox inbox >> deals.log 2>&1
```

Windows: Task Scheduler → Create Basic Task → Daily → Program
`C:\path\to\claude-lawyer\.venv\Scripts\python.exe`, arguments
`-m paralegal deals --inbox inbox`, start in `C:\path\to\claude-lawyer`.

## The math

```
cash buyer's price = ARV × 70% − repairs
your max offer     = cash buyer's price − your fee
```

Change the 70% with `--rule` (hot markets pay 75–80%) and the fee with `--fee`.
If the export has no repair number, repairs are estimated per square foot
(`REPAIR_PER_SQFT` in `paralegal/deals.py`, $30/$55/$90 for light/medium/heavy)
and marked `[ESTIMATED]`. Never sign on an estimate; walk the house.

The analyzer understands common column names from the big lead tools
(`Property Address`, `Estimated Value`, `Building Sqft`, `Owner Occupied`,
`Lists`...). If yours uses different names, add them to `COLUMNS` in
`paralegal/deals.py`.

## Legal guardrails built in

- **Civil Code 1695.** Foreclosure-tagged leads where the owner may live there
  are flagged ATTORNEY instead of OFFER.
- **No outreach from code.** The tool never calls, texts or emails anyone.
- **Review gate.** Every report is headed PENDING HUMAN REVIEW and ends with a
  checklist: comps, walkthrough, assignment disclosure, TCPA, licensing.

## Next pieces to add
- Attorney-review contract set: purchase agreement with assignment clause,
  assignment agreement, seller disclosure of intent to assign.
- Buyer email draft for each OFFER deal, sent only after you approve it.
- Pulling leads straight from a vendor API (if your plan includes one) instead
  of manual exports.
