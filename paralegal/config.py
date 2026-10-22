"""Settings shared by every agent on the team."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"
MATTERS_DIR = Path(os.environ.get("PARALEGAL_MATTERS_DIR", ROOT / "matters"))

MODEL = os.environ.get("PARALEGAL_MODEL", "claude-opus-5-5")
JURISDICTION = "California"

# On a safety refusal the API reruns the request on a fallback model it picks.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Optional. Without it, case citations can't be checked automatically and are
# flagged for the human reviewer instead. Free token: courtlistener.com/profile.
COURTLISTENER_TOKEN = os.environ.get("COURTLISTENER_API_TOKEN")

# The legal researcher may only cite what it finds on these sites.
LEGAL_SOURCE_DOMAINS = [
    "leginfo.legislature.ca.gov",  # California codes
    "courts.ca.gov",  # Judicial Council forms and self-help
    "selfhelp.courts.ca.gov",
    "courtlistener.com",  # case law
    "law.justia.com",
    "hcd.ca.gov",  # Housing and Community Development
    "dre.ca.gov",  # California Tenants guide
    "oag.ca.gov",  # Attorney General tenant guidance
    "sos.ca.gov",  # LLC filings
    "ftb.ca.gov",  # franchise tax
    "cdtfa.ca.gov",  # seller's permits, sales tax
    "calgold.ca.gov",  # permits
    "calosba.ca.gov",
    "sba.gov",
    "irs.gov",
    "dir.ca.gov",  # labor law
]
