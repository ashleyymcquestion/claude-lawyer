# Tenant case file

This folder holds everything about one housing problem. It stays on your computer
and is never uploaded to GitHub.

| File | What to put in it |
| --- | --- |
| `payment-log.csv` | One row for every payment: rent you gave the roommate, rent anyone paid the landlord. |
| `timeline.csv` | One row for everything that happened: payments, texts, notices, conversations. |
| `evidence-checklist.md` | What to collect. Check items off as you go. |
| `evidence/` | Screenshots, statements, photos of notices, the lease. |

Open the `.csv` files in Excel, Google Sheets or Numbers. Delete the example
rows, keep the column names. Write dates as YYYY-MM-DD (2026-08-01). In the
`from` and `to` columns, use the same names every time (Me, Roommate, Landlord).
In `for`, write what the money was for, like `rent 2026-08`.

When it's filled in:

```bash
python -m paralegal case summary cases/<this folder>
```

That adds up who paid whom, lists the timeline in order and writes
`summary.md`. Attach the summary and your evidence to a request:

```bash
python -m paralegal ask "..." --attach cases/<this folder>/summary.md cases/<this folder>/evidence/notice.pdf
```

If you got a notice or court papers, work out your deadline first:

```bash
python -m paralegal deadline --served 2026-10-20 --notice
python -m paralegal deadline --served 2026-10-20 --method personal
```
