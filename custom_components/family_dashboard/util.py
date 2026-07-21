"""Small shared helpers used across Family Dashboard's modules."""
from __future__ import annotations

import re
from datetime import date as date_cls


class InvalidBirthdateText(ValueError):
    """Raised by `ddmmyyyy_to_iso` for text that isn't a valid DD/MM/YYYY date."""


_DD_MM_YYYY_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")
BIRTHDATE_FORMAT_ERROR = "Enter a date as DD/MM/YYYY, e.g. 21/06/2015"


def ddmmyyyy_to_iso(value: str | None) -> str | None:
    """Converts a typed DD/MM/YYYY birthdate into the ISO string `CONF_BIRTHDATE` (and every
    `date` entity) stores. Shared by `config_flow.py` (the wizard's Birthdate step) and
    `modules/settings/date.py` (the Settings tab's birthdate-edit popup) - both replaced HA's
    built-in `date` selector/widget with a typed text field for the SAME live-reported reason:
    the stock date picker is popup-only (no way to type directly) with no year-jump in its
    calendar grid (confirmed by reading `DateSelectorConfig`'s source - zero configurable
    options - and live-testing the popup itself), making it unusable for old birthdates
    (2026 back to the 1970s-80s is ~500 "previous month" clicks). Raises
    `InvalidBirthdateText` (message `BIRTHDATE_FORMAT_ERROR`) if the text doesn't parse as a
    real calendar date; returns `None` for blank/missing input (a member may have no
    birthdate on file)."""
    if not value:
        return None
    match = _DD_MM_YYYY_RE.match(value)
    if not match:
        raise InvalidBirthdateText(BIRTHDATE_FORMAT_ERROR)
    day, month, year = (int(group) for group in match.groups())
    try:
        return date_cls(year, month, day).isoformat()
    except ValueError as err:
        raise InvalidBirthdateText(BIRTHDATE_FORMAT_ERROR) from err


def iso_to_ddmmyyyy(value: str) -> str:
    parsed = date_cls.fromisoformat(value)
    return f"{parsed.day:02d}/{parsed.month:02d}/{parsed.year:04d}"


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WEEKDAY_ABBREVS = {day[:3]: day for day in WEEKDAYS}


class InvalidScheduleDaysText(ValueError):
    """Raised by `parse_schedule_days_text` for text that isn't a recognizable list of
    weekdays."""


SCHEDULE_DAYS_FORMAT_ERROR = (
    "Enter comma-separated days (Mon, Tue, Wed, Thu, Fri, Sat, Sun), or leave blank for every day"
)


def parse_schedule_days_text(value: str | None) -> list[str] | None:
    """Converts a typed comma/space-separated list of weekday names or 3-letter abbreviations
    (case-insensitive) into a `schedule_days` list, normalized to full lowercase names and
    ordered Monday->Sunday regardless of input order. Blank/whitespace-only input means "every
    day" - a chore's optional schedule is opt-in, so an empty field is a valid, common case,
    not an error (mirrors `ddmmyyyy_to_iso`'s own "blank means no value" convention). Raises
    `InvalidScheduleDaysText` (message `SCHEDULE_DAYS_FORMAT_ERROR`) for any unrecognized
    token."""
    if not value or not value.strip():
        return None
    tokens = [t.strip().lower() for t in re.split(r"[,\s]+", value.strip()) if t.strip()]
    days: set[str] = set()
    for token in tokens:
        if token in WEEKDAYS:
            days.add(token)
        elif token[:3] in _WEEKDAY_ABBREVS:
            days.add(_WEEKDAY_ABBREVS[token[:3]])
        else:
            raise InvalidScheduleDaysText(SCHEDULE_DAYS_FORMAT_ERROR)
    return [day for day in WEEKDAYS if day in days] or None


def format_schedule_days(days: list[str] | None) -> str:
    """The inverse display helper - `_chore_row`'s "Schedule" pill text."""
    if not days:
        return "Every day"
    return ", ".join(day[:3].capitalize() for day in days)


def slugify_unique(name: str, existing: set[str]) -> str:
    """Turn a display name into a stable, unique snake_case id.

    Used once, at wizard-submit time, to generate each roster member's permanent
    `member_id`. This id does NOT change later even if the member's display name is edited
    afterward via the Settings dashboard - the editable name lives in a separate `text`
    entity's state, while `member_id` backs every entity's `unique_id` for that member
    across every module (Settings, and eventually Calendar/Lists/Chores). `unique_id` must
    stay stable for HA's entity registry to keep treating it as the same entity after a
    rename - regenerating it from the (now-changed) name would silently orphan the old
    entity and create a new one.

    `existing` is mutated in place (the caller's dedup set) so repeated calls in a loop
    correctly avoid collisions across the whole roster.
    """
    base = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "member"
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}_{n}"
        n += 1
    existing.add(slug)
    return slug
