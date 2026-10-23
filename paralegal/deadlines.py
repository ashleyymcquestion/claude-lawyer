"""Eviction deadlines in plain code, so the date math never depends on a model.

Court days skip Saturdays, Sundays and California judicial holidays. When we
aren't sure a court is closed on a day, we count it as open: that gives the
earlier (safer) date, and the report says the real deadline may be later.

The rules below change. Before relying on a result, check the current text of
Code of Civil Procedure 1161, 1167, 415.20 and 415.45 on leginfo, and the
court's own holiday calendar.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

# CCP 1167: time to respond to an eviction (unlawful detainer) summons.
# 10 court days since AB 2347 (effective Jan 1, 2025); it was 5 before that.
RESPONSE_COURT_DAYS = 10
# CCP 1161(2), (3): notice to pay rent or quit / perform covenant or quit.
NOTICE_COURT_DAYS = 3
# CCP 415.20 (substituted) and 415.45 (posting): service is complete 10
# calendar days after the copy is mailed.
SERVICE_DELAY_DAYS = {"personal": 0, "substituted": 10, "posting": 10}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    days = [d for d in calendar.Calendar().itermonthdates(year, month) if d.month == month and d.weekday() == weekday]
    return days[n]


def judicial_holidays(year: int) -> tuple[dict[date, str], dict[date, str]]:
    """Return (certain, uncertain) court holidays for a year, from Government Code 6700 and CCP 135."""
    mon, thu, fri = 0, 3, 4
    fixed = {
        date(year, 1, 1): "New Year's Day",
        date(year, 2, 12): "Lincoln's Birthday",
        date(year, 3, 31): "Cesar Chavez Day",
        date(year, 6, 19): "Juneteenth",
        date(year, 7, 4): "Independence Day",
        date(year, 11, 11): "Veterans Day",
        date(year, 12, 25): "Christmas Day",
    }
    thanksgiving = _nth_weekday(year, 11, thu, 3)
    certain = {
        _nth_weekday(year, 1, mon, 2): "Martin Luther King Jr. Day",
        _nth_weekday(year, 2, mon, 2): "Presidents' Day",
        _nth_weekday(year, 5, mon, -1): "Memorial Day",
        _nth_weekday(year, 9, mon, 0): "Labor Day",
        thanksgiving: "Thanksgiving",
        thanksgiving + timedelta(days=1): "Day after Thanksgiving",
    }
    uncertain = {_nth_weekday(year, 9, fri, 3): "Native American Day (check whether this court closes)"}
    for day, name in fixed.items():
        if day.weekday() == 6:  # Sunday holiday: observed Monday
            certain[day + timedelta(days=1)] = f"{name} (observed)"
        elif day.weekday() == 5:  # Saturday holiday: courts usually close the Friday before
            uncertain[day - timedelta(days=1)] = f"{name} (observed Friday; check the court calendar)"
        else:
            certain[day] = name
    return certain, uncertain


def _holidays_around(start: date, end: date) -> tuple[dict[date, str], dict[date, str]]:
    certain: dict[date, str] = {}
    uncertain: dict[date, str] = {}
    for year in range(start.year, end.year + 1):
        c, u = judicial_holidays(year)
        certain |= c
        uncertain |= u
    return certain, uncertain


def _day(d: date) -> str:
    return f"{d:%A, %B} {d.day}, {d.year}"


@dataclass
class Deadline:
    what: str
    start: date
    court_days: int
    safe_date: date  # counts uncertain holidays as open days
    possibly_later: date  # counts them as closed
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            f"**{self.what}**",
            f"- Counting starts the day after {_day(self.start)}.",
            f"- {self.court_days} court days (no weekends or court holidays).",
            f"- **Last day: {_day(self.safe_date)}.** Treat this as the deadline.",
        ]
        if self.possibly_later != self.safe_date:
            lines.append(
                f"- It may be {_day(self.possibly_later)} if the court was closed on a day "
                "marked 'check' below. Don't rely on the later date without confirming with the clerk."
            )
        if self.skipped:
            lines.append("- Holidays in the count: " + "; ".join(self.skipped))
        lines += [f"- {n}" for n in self.notes]
        lines.append("- Confirm with the court clerk or self-help center. Rules and holidays change.")
        return "\n".join(lines)


def add_court_days(start: date, n: int, what: str = "Deadline") -> Deadline:
    """Count n court days after start (the start day itself is not counted)."""
    certain, uncertain = _holidays_around(start, start + timedelta(days=n * 3 + 30))

    def count(closed: dict[date, str]) -> date:
        day, left = start, n
        while left:
            day += timedelta(days=1)
            if day.weekday() < 5 and day not in closed:
                left -= 1
        return day

    safe = count(certain)
    later = count(certain | uncertain)
    skipped = [
        f"{d:%b} {d.day} {name}" for d, name in sorted((certain | uncertain).items()) if start < d <= later
    ]
    return Deadline(what, start, n, safe, later, skipped)


def eviction_response(served: date, method: str = "personal") -> Deadline:
    """Last day to file a response (such as an Answer, UD-105) after an eviction summons is served."""
    if method not in SERVICE_DELAY_DAYS:
        raise ValueError(f"method must be one of {', '.join(SERVICE_DELAY_DAYS)}")
    delay = SERVICE_DELAY_DAYS[method]
    complete = served + timedelta(days=delay)
    d = add_court_days(complete, RESPONSE_COURT_DAYS, "Last day to respond to the eviction lawsuit")
    if delay:
        d.notes.append(
            f"Served by {method} service on {served:%B} {served.day}: service counts as complete {delay} "
            f"calendar days after the copy was mailed ({complete:%B} {complete.day}). Use the mailing date, "
            "and if unsure, use the earlier date."
        )
    d.notes.append(f"Rule used: {RESPONSE_COURT_DAYS} court days (Code of Civil Procedure 1167).")
    return d


def notice_expires(served: date) -> Deadline:
    """When a 3-day notice to pay rent or quit runs out. The tenant can pay through this day."""
    d = add_court_days(served, NOTICE_COURT_DAYS, "3-day notice: last day to pay or fix the problem")
    d.notes.append("Rule used: 3 days not counting weekends or court holidays (Code of Civil Procedure 1161).")
    d.notes.append("If the notice was posted or mailed, ask whether extra days apply; use this earlier date to be safe.")
    return d
