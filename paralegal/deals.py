"""Deal analyzer for wholesaling: score leads and match them to cash buyers.

Plain code, no model calls. Input is the CSV export from a lead tool
(PropStream, DealMachine, BatchLeads...) and, optionally, a cash-buyer export.
Output is a run folder under deals/ with a ranked report that starts as
PENDING HUMAN REVIEW. Nothing here contacts a seller or sends an offer.

The math is the usual investor rule:
    buyer's price   = ARV x rule (70%) - repairs
    your max offer  = buyer's price - your assignment fee
"""

from __future__ import annotations

import csv
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config

# Repair cost per square foot when the export has no repair estimate.
# California labor runs high; change these to your contractor's numbers.
REPAIR_PER_SQFT = {"light": 30, "medium": 55, "heavy": 90}

# Header names differ by vendor. Keys are compared lowercase with punctuation removed.
COLUMNS = {
    "address": ["address", "propertyaddress", "streetaddress", "siteaddress"],
    "city": ["city", "propertycity"],
    "zip": ["zip", "zipcode", "propertyzip", "postalcode"],
    "arv": ["arv", "afterrepairvalue", "estimatedvalue", "estvalue", "avm", "marketvalue"],
    "repairs": ["repairs", "repairestimate", "rehab", "rehabcost", "estimatedrepairs"],
    "sqft": ["sqft", "squarefeet", "buildingsqft", "livingarea", "livingsqft"],
    "condition": ["condition", "rehablevel"],
    "asking": ["asking", "askingprice", "listprice", "sellerprice"],
    "owner_occupied": ["owneroccupied", "owneroccupancy"],
    "tags": ["tags", "lists", "leadtype", "distress", "motivation"],
    # buyer lists
    "name": ["name", "buyername", "ownername", "buyer"],
    "phone": ["phone", "phonenumber", "mobile"],
    "email": ["email", "emailaddress"],
    "purchases": ["purchases", "cashpurchases", "numberofpurchases", "propertiesbought", "deals"],
    "max_price": ["maxprice", "maxpurchaseprice", "pricemax", "budget"],
    "avg_price": ["avgprice", "averagepurchaseprice", "avgpurchaseprice", "lastpurchaseprice"],
}

FORECLOSURE = re.compile(r"pre-?foreclos|foreclos|notice of default|\bnod\b|lis pendens|trustee sale|auction", re.I)


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def _read(path: Path) -> list[dict[str, str]]:
    """Read a CSV and rename its columns to the names in COLUMNS."""
    lookup = {alias: name for name, aliases in COLUMNS.items() for alias in aliases}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [
        {lookup[_key(k)]: (v or "").strip() for k, v in row.items() if k and _key(k) in lookup}
        for row in rows
    ]


def _money(value: str) -> float | None:
    cleaned = re.sub(r"[^0-9.]", "", value or "")
    return float(cleaned) if cleaned else None


def _yes(value: str) -> bool | None:
    v = (value or "").strip().lower()
    if v in {"y", "yes", "true", "1", "owner occupied"}:
        return True
    if v in {"n", "no", "false", "0", "absentee", "non-owner occupied"}:
        return False
    return None


@dataclass
class Deal:
    address: str
    city: str
    zip: str
    arv: float
    repairs: float
    repairs_estimated: bool
    asking: float | None
    buyer_price: float
    max_offer: float
    status: str
    notes: list[str] = field(default_factory=list)
    buyers: list[dict] = field(default_factory=list)

    @property
    def spread(self) -> float:
        """Equity left after repairs at the seller's price (or your max offer)."""
        return self.arv - self.repairs - (self.asking if self.asking is not None else self.max_offer)


def analyze(lead: dict[str, str], fee: float, rule: float) -> Deal | None:
    arv = _money(lead.get("arv", ""))
    if not arv:
        return None
    notes = []
    repairs = _money(lead.get("repairs", ""))
    estimated = repairs is None
    if estimated:
        level = lead.get("condition", "").lower()
        level = level if level in REPAIR_PER_SQFT else "medium"
        sqft = _money(lead.get("sqft", "")) or 0
        repairs = sqft * REPAIR_PER_SQFT[level]
        notes.append(f"[ESTIMATED] repairs at ${REPAIR_PER_SQFT[level]}/sqft ({level}); get a contractor walkthrough"
                     if sqft else "[NO REPAIR ESTIMATE] repairs assumed $0; walk the property first")
    buyer_price = arv * rule - repairs
    max_offer = buyer_price - fee
    asking = _money(lead.get("asking", ""))

    if max_offer <= 0:
        status = "skip"
        notes.append("Numbers don't work even at $0 after repairs and your fee")
    elif asking is not None and asking > max_offer:
        status = "negotiate"
        notes.append(f"Seller wants ${asking - max_offer:,.0f} more than your max offer")
    else:
        status = "offer"

    occupied = _yes(lead.get("owner_occupied", ""))
    if FORECLOSURE.search(lead.get("tags", "")) and occupied is not False:
        status = "attorney"
        notes.append("Home in foreclosure that the owner may live in: Civil Code 1695 applies "
                     "(special contract, 5-day cancellation). Use only an attorney-approved contract")
    return Deal(lead.get("address", "?"), lead.get("city", ""), lead.get("zip", ""), arv, repairs,
                estimated, asking, buyer_price, max_offer, status, notes)


def match_buyers(deal: Deal, buyers: list[dict[str, str]], limit: int = 5) -> list[dict]:
    """Cash buyers who bought in the same zip or city at a price this deal fits."""
    out = []
    for b in buyers:
        same_zip = deal.zip and deal.zip[:5] in re.split(r"[\s,;]+", b.get("zip", ""))
        same_city = deal.city and deal.city.lower() == b.get("city", "").lower()
        if not (same_zip or same_city):
            continue
        cap = _money(b.get("max_price", "")) or (_money(b.get("avg_price", "")) or 0) * 1.25
        if cap and deal.buyer_price > cap:
            continue
        out.append(b)
    out.sort(key=lambda b: _money(b.get("purchases", "")) or 0, reverse=True)
    return out[:limit]


ORDER = {"offer": 0, "negotiate": 1, "attorney": 2, "skip": 3}

CHECKLIST = """\
## Before any offer goes out
- [ ] ARV checked against at least 3 sold comps within 0.5 mile and 6 months
- [ ] Repair number comes from a walkthrough, not the [ESTIMATED] figure
- [ ] Contract is the attorney-approved version, with the assignment clause and
      written disclosure that you plan to assign it and may profit
- [ ] Anything marked ATTORNEY has gone to the attorney first (Civil Code 1695)
- [ ] Seller contact is by mail, door or a call you make yourself; no AI-voice
      calls or automated texts without prior express written consent (TCPA)
- [ ] You market the *contract* to buyers, not the house (licensing, B&P 10131)
"""


def run(leads_csv: Path, buyers_csv: Path | None = None, fee: float = 10_000, rule: float = 0.70) -> Path:
    buyers = _read(buyers_csv) if buyers_csv else []
    deals = [d for d in (analyze(row, fee, rule) for row in _read(leads_csv)) if d]
    for d in deals:
        if d.status != "skip":
            d.buyers = match_buyers(d, buyers)
    deals.sort(key=lambda d: (ORDER[d.status], -d.spread))

    now = datetime.now(timezone.utc)
    folder = config.DEALS_DIR / f"{now:%Y%m%d-%H%M%S}-{leads_csv.stem}"
    folder.mkdir(parents=True)
    with (folder / "deals.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["status", "address", "city", "zip", "arv", "repairs", "asking",
                    "max_offer", "buyer_price", "fee", "spread", "matched_buyers", "notes"])
        for d in deals:
            w.writerow([d.status, d.address, d.city, d.zip, round(d.arv), round(d.repairs),
                        "" if d.asking is None else round(d.asking), round(d.max_offer),
                        round(d.buyer_price), round(fee), round(d.spread),
                        "; ".join(b.get("name", "?") for b in d.buyers), " | ".join(d.notes)])
    (folder / "report.md").write_text(report(deals, leads_csv, buyers_csv, fee, rule))
    return folder


def report(deals: list[Deal], leads_csv: Path, buyers_csv: Path | None, fee: float, rule: float) -> str:
    counts = {s: sum(d.status == s for d in deals) for s in ORDER}
    lines = [
        "# DEAL LIST - PENDING HUMAN REVIEW",
        "",
        f"Leads: `{leads_csv.name}`" + (f" · Buyers: `{buyers_csv.name}`" if buyers_csv else " · no buyer list"),
        f"Rule: {rule:.0%} of ARV minus repairs · Your fee: ${fee:,.0f}",
        "",
        f"**{counts['offer']} ready to offer · {counts['negotiate']} to negotiate · "
        f"{counts['attorney']} need the attorney · {counts['skip']} skipped**",
        "",
        "Estimates only. Nothing below has been sent to anyone.",
        "",
    ]
    for d in deals:
        if d.status == "skip":
            continue
        asking = "unknown" if d.asking is None else f"${d.asking:,.0f}"
        lines += [
            f"## {d.status.upper()}: {d.address}, {d.city} {d.zip}",
            f"- ARV ${d.arv:,.0f} · repairs ${d.repairs:,.0f} · seller asking {asking}",
            f"- **Your max offer ${d.max_offer:,.0f}** · cash buyer pays ${d.buyer_price:,.0f} · your fee ${fee:,.0f}",
            *[f"- {n}" for n in d.notes],
        ]
        if d.buyers:
            lines.append("- Matched buyers: " + "; ".join(
                f"{b.get('name', '?')} ({b.get('purchases') or '?'} buys, {b.get('phone') or b.get('email') or 'no contact'})"
                for b in d.buyers))
        elif buyers_csv:
            lines.append("- No matched buyers in this area and price range yet")
        lines.append("")
    return "\n".join(lines) + "\n" + CHECKLIST


def run_inbox(inbox: Path, fee: float = 10_000, rule: float = 0.70) -> list[Path]:
    """Process every new lead CSV in a folder, then move it to inbox/done/.

    Keep your current cash-buyer export at inbox/buyers.csv; it is reused each run.
    Point a daily scheduled job at this so new exports are scored automatically.
    """
    buyers = inbox / "buyers.csv"
    done = inbox / "done"
    folders = []
    for leads in sorted(inbox.glob("*.csv")):
        if leads.name == buyers.name:
            continue
        folders.append(run(leads, buyers if buyers.exists() else None, fee, rule))
        done.mkdir(exist_ok=True)
        shutil.move(str(leads), done / leads.name)
    return folders
