"""When a chore is due, and the picker's token format - pure functions, no HA imports.

A chore repeats on picked weekdays (`days_of_week`; none picked = every day), on picked day
numbers of the month (`monthly`; a day past the month's end falls on its last day), or not at
all (`one_time`). Each due day is its own claimable instance: the task sensor
(`sensor.py`) asks `is_due` whether today can be claimed, and `due_day_started_since` whether
a reviewed claim should give way to a newer instance.

The Schedule picker stores its selection in a scratch text entity as comma-separated tokens:
weekday keys (`mon,thu`) or day numbers (`1,15`), always in canonical order.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

REPEAT_DAYS_OF_WEEK = "days_of_week"
REPEAT_MONTHLY = "monthly"
REPEAT_ONE_TIME = "one_time"

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WEEKDAY_KEYS = tuple(day[:3] for day in WEEKDAYS)
_KEY_TO_WEEKDAY = dict(zip(WEEKDAY_KEYS, WEEKDAYS))

MONTHLY_NEEDS_A_DAY = "Pick at least one day of the month"

# Every recurring schedule has a due day within any 31-day span (weekly patterns within 7,
# monthly within a month), so longer gaps never need scanning.
_MAX_GAP_DAYS = 31


def _repeat(chore: dict) -> str:
    return chore.get("repeat", REPEAT_DAYS_OF_WEEK)


def _month_due_days(chore: dict, year: int, month: int) -> set[int]:
    last = calendar.monthrange(year, month)[1]
    return {min(d, last) for d in chore.get("month_days") or []}


def is_due(chore: dict, day: date) -> bool:
    repeat = _repeat(chore)
    if repeat == REPEAT_ONE_TIME:
        return True
    if repeat == REPEAT_MONTHLY:
        return day.day in _month_due_days(chore, day.year, day.month)
    days = chore.get("schedule_days")
    return not days or WEEKDAYS[day.weekday()] in days


def due_day_started_since(chore: dict, since: date, today: date) -> bool:
    """Whether any date in `(since, today]` is a due day - i.e. a newer instance than the
    one claimed on `since` has begun. Never true for a one-time chore."""
    if _repeat(chore) == REPEAT_ONE_TIME or today <= since:
        return False
    if (today - since).days >= _MAX_GAP_DAYS:
        return True
    day = since + timedelta(days=1)
    while day <= today:
        if is_due(chore, day):
            return True
        day += timedelta(days=1)
    return False


def describe(chore: dict) -> str:
    """The management row's Schedule pill text."""
    repeat = _repeat(chore)
    if repeat == REPEAT_ONE_TIME:
        return "One-time"
    if repeat == REPEAT_MONTHLY:
        return "Monthly: " + ", ".join(str(d) for d in sorted(chore.get("month_days") or []))
    days = chore.get("schedule_days")
    if not days:
        return "Every day"
    return ", ".join(day[:3].capitalize() for day in WEEKDAYS if day in days)


def _split(text: str | None) -> list[str]:
    return [t.strip().lower() for t in (text or "").split(",") if t.strip()]


def _is_month_token(token: str) -> bool:
    return token.isdigit() and 1 <= int(token) <= 31


def _weekday_tokens(text: str | None) -> list[str]:
    picked = set(_split(text))
    return [key for key in WEEKDAY_KEYS if key in picked]


def _month_tokens(text: str | None) -> list[int]:
    return sorted({int(t) for t in _split(text) if _is_month_token(t)})


def toggle_token(repeat: str, text: str | None, token: str) -> str:
    """Add or remove one picker token, returning the canonical text. Raises `ValueError`
    for a token that doesn't belong to `repeat` (e.g. "mon" while Monthly is selected)."""
    token = token.strip().lower()
    if repeat == REPEAT_DAYS_OF_WEEK and token in WEEKDAY_KEYS:
        picked = set(_weekday_tokens(text)) ^ {token}
        return ",".join(key for key in WEEKDAY_KEYS if key in picked)
    if repeat == REPEAT_MONTHLY and _is_month_token(token):
        picked = set(_month_tokens(text)) ^ {int(token)}
        return ",".join(str(d) for d in sorted(picked))
    raise ValueError(f"'{token}' isn't a valid day for this schedule")


def tokens_to_schedule(repeat: str, text: str | None) -> dict:
    """The stored schedule fields for a picker selection. Tokens of the other kind are
    ignored. Raises `ValueError(MONTHLY_NEEDS_A_DAY)` for Monthly with no day picked."""
    if repeat == REPEAT_MONTHLY:
        month_days = _month_tokens(text)
        if not month_days:
            raise ValueError(MONTHLY_NEEDS_A_DAY)
        return {"repeat": REPEAT_MONTHLY, "month_days": month_days}
    if repeat == REPEAT_ONE_TIME:
        return {"repeat": REPEAT_ONE_TIME}
    schedule = {"repeat": REPEAT_DAYS_OF_WEEK}
    days = [_KEY_TO_WEEKDAY[key] for key in _weekday_tokens(text)]
    if days:
        schedule["schedule_days"] = days
    return schedule


def chore_to_tokens(chore: dict) -> str:
    """The inverse of `tokens_to_schedule` - pre-fills the Edit Schedule popup."""
    repeat = _repeat(chore)
    if repeat == REPEAT_MONTHLY:
        return ",".join(str(d) for d in sorted(chore.get("month_days") or []))
    if repeat == REPEAT_ONE_TIME:
        return ""
    days = chore.get("schedule_days") or []
    return ",".join(day[:3] for day in WEEKDAYS if day in days)


def upgrade_chore(chore: dict) -> dict:
    """Convert a pre-scheduling chore (`frequency` daily/weekly/one_time) to the `repeat`
    shape. Returns the same object untouched if it's already upgraded."""
    if "repeat" in chore:
        return chore
    upgraded = {k: v for k, v in chore.items() if k != "frequency"}
    frequency = chore.get("frequency")
    if frequency == REPEAT_ONE_TIME:
        upgraded.pop("schedule_days", None)
        upgraded["repeat"] = REPEAT_ONE_TIME
        return upgraded
    upgraded["repeat"] = REPEAT_DAYS_OF_WEEK
    if frequency == "weekly" and not chore.get("schedule_days"):
        # No day to anchor a weekly chore to; Sunday keeps it roughly once a week.
        upgraded["schedule_days"] = ["sunday"]
    return upgraded
