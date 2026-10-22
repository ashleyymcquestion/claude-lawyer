# claude-lawyer

A team of AI agents that works like a strong paralegal or junior associate for
**California landlord-tenant** and **small business** matters. Everything it
produces is a draft that a human reviews before anyone relies on it.

> This is not a lawyer and does not give legal advice. Have a licensed
> California attorney review its work before it is sent, signed or filed.

## The team

```
you ──> supervising associate ──┬── legal researcher   searches official CA sources only (leginfo, courts.ca.gov, CourtListener...)
                                ├── contract reviewer  reads leases/contracts you attach, flags risky or illegal clauses
                                ├── drafter            demand letters, notices, responses, agreements
                                ├── funding scout      grants, loans and certifications for your business
                                └── citation checker   plain code: checks every case cited with CourtListener
                                         │
                                         v
                        matters/<date>-<topic>/work_product.md   (PENDING HUMAN REVIEW)
                                         │
                            you review, then: paralegal approve
```

Built-in safeguards:
- The researcher can only search and cite official legal sites (`paralegal/config.py`).
- Every finished piece goes through a citation check in code. Case citations are found with
  [eyecite](https://github.com/freelawproject/eyecite) (Free Law Project). A case CourtListener
  can't find is marked **NOT FOUND**, and the matter can't be approved until it's fixed.
- Statute citations get a direct leginfo link so the reviewer can read the actual text.
- Assumed facts are put in `[BRACKETS]`, and deadlines and urgent problems are flagged at the top.
- Every request is saved with a reviewer checklist and an approval record.

## Setup

1. Install Python 3.10 or newer.
2. In this folder, create a virtual environment and install:
   ```
   python3 -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -U pip setuptools
   pip install -e ".[dev]"
   ```
   Run `source .venv/bin/activate` again in each new terminal before using the tool.
3. Get an API key at https://console.anthropic.com and set it:
   ```
   export ANTHROPIC_API_KEY=sk-ant-...
   ```
4. Recommended: get a free CourtListener token (https://www.courtlistener.com/profile/)
   so case citations are checked automatically:
   ```
   export COURTLISTENER_API_TOKEN=...
   ```

## Use

```bash
# Research a question
python -m paralegal ask "How long does a California landlord have to return a security deposit, and what can they deduct?"

# Review a lease
python -m paralegal ask "Review this lease for a tenant in Los Angeles. Flag anything illegal or risky." --attach lease.pdf

# Draft a document
python -m paralegal ask "Draft a security deposit demand letter. Tenant moved out 30 days ago, landlord kept the full deposit with no itemized statement."

# Small business
python -m paralegal ask "What does Midnight 06 LLC need to stay in good standing in California and to sell apparel online?"

# Funding
python -m paralegal ask "Find grants for Midnight 06 LLC, a woman- and minority-owned creative/apparel LLC in California, open in the next 90 days."

# Review queue
python -m paralegal pending
python -m paralegal approve matters/20261022-... --reviewer "Jane Attorney"
```

## Customizing

- `knowledge/*.md`: the reference map every agent reads. Add your local rules, templates and firm preferences here.
- `paralegal/config.py`: model, jurisdiction and the list of allowed legal source sites.
- `paralegal/team.py`: each agent's role and instructions. Add new specialists here.

## Tests

```
python -m pytest
```

The tests use a fake model, so they don't need an API key.

## Funding for Midnight 06 LLC

See [docs/midnight06-funding.md](docs/midnight06-funding.md).
