"""Shared cross-platform logic for the Add Event popup's Start/End time-of-day fields.

2026-07-25: replaced the earlier single combined `datetime.family_dashboard_event_start`/
`_end` entities entirely (see git history for `datetime.py`, now deleted) with a decomposed
Date + Hour(1-12) + Minute + AM/PM set of fields per side - a live request, since HA's native
`datetime` more-info picker's 12-hour-vs-24-hour display is governed by each VIEWER's own HA
account profile setting (Settings > General > Time Format, confirmed directly against HA's
frontend source - `useAmPm`/`locale.time_format`), not anything a dashboard or integration can
force. A shared wall-mounted kiosk (this project's primary use case) can't rely on a per-viewer
account setting, so AM/PM is now built explicitly as our own fields instead, guaranteed
regardless of who's looking at it or how their account is configured.

Unique-id suffixes for all 8 fields (Start/End x Date/Hour/Minute/AM-PM) live here as the
single source of truth, even though the entity CLASSES themselves live in their own
per-platform files (`date.py`/`number.py`/`select.py`) per this codebase's usual module-per-
platform convention - centralized here instead of scattered because `async_recompute_
end_from_start` (below) needs to address all 8 by name, and because `events.py`'s submit
logic reads all 8 too. `date.py`/`number.py`/`select.py`/`events.py` all import FROM this
module; this module imports from none of them, so there's no import cycle.

`async_recompute_end_from_start` is called by each of Start's 4 own field entities after
their own `async_set_value`/`async_set_native_value`/`async_select_option` - same
"unconditionally overwrite End on every Start change, not just the first" reasoning the old
combined-datetime `_EventStartDateTime` used (see its git history): the user's own subsequent
edit to any of End's 4 fields is the last word, since nothing else re-derives them except a
further Start change. Composing/decomposing through a real Python `datetime` (rather than
doing hour-of-day arithmetic in 12-hour space by hand) is what makes the "+1 hour" correctly
roll into the next calendar day for a Start near midnight (e.g. 11:30 PM + 1h -> 12:30 AM the
NEXT day) - see `_compose_datetime`/`_decompose_datetime`.
"""
from __future__ import annotations

from datetime import date as date_type, datetime, time, timedelta

import homeassistant.components.date as date_component
import homeassistant.components.number as number_component
import homeassistant.components.select as select_component
import homeassistant.util.dt as dt_util
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ...const import DOMAIN

EVENT_START_DATE_UNIQUE_ID = "event_start_date"
EVENT_END_DATE_UNIQUE_ID = "event_end_date"
EVENT_START_HOUR_UNIQUE_ID = "event_start_hour"
EVENT_END_HOUR_UNIQUE_ID = "event_end_hour"
EVENT_START_MINUTE_UNIQUE_ID = "event_start_minute"
EVENT_END_MINUTE_UNIQUE_ID = "event_end_minute"
EVENT_START_AMPM_UNIQUE_ID = "event_start_ampm"
EVENT_END_AMPM_UNIQUE_ID = "event_end_ampm"

# The Recurring switch + Recurrence preset picker's own constants also live here rather than
# in select.py/switch.py (where their entity classes actually live) - events.py needs both,
# and select.py already imports FROM events.py (async_create_event_from_scratch_fields), so
# events.py importing back from select.py would be a circular import. This module imports
# from neither select.py nor events.py, so both can import from here with no cycle.
EVENT_RECURRING_UNIQUE_ID = "event_recurring"
EVENT_RECURRENCE_UNIQUE_ID = "event_recurrence"
# Google-Calendar-style quick presets (common cases only, per live scope decision - no
# custom interval/weekday/end-condition builder). RRULE construction from these lives in
# events.py, keyed on these exact strings.
RECURRENCE_OPTIONS = ["Daily", "Weekly", "Monthly", "Annually", "Every Weekday"]
RECURRENCE_DEFAULT = "Weekly"

# Defaults every field resets to after a submit (see events.py) and what brand-new entities
# start at - 9:00 AM / 10:00 AM so a freshly-opened popup already shows a self-consistent,
# one-hour-apart pair with no interaction needed, matching what the recompute below would
# produce anyway from those exact starting values.
DEFAULT_START_HOUR = 9
DEFAULT_END_HOUR = 10
DEFAULT_MINUTE = 0
DEFAULT_AMPM = "AM"

_COMPONENT_MAP = {
    "date": date_component.DATA_COMPONENT,
    "number": number_component.DATA_COMPONENT,
    "select": select_component.DATA_COMPONENT,
}


def _sibling_entity(hass: HomeAssistant, entry: ConfigEntry, domain: str, unique_id_suffix: str):
    """Look up another of THIS integration's own entities by domain + unique-id suffix - same
    registry-lookup + component-data-fetch mechanism `events.py`'s own `_entity` helper uses,
    duplicated locally rather than imported from there to avoid a circular import (events.py
    imports the unique-id constants from this module, not the other way around)."""
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{unique_id_suffix}"
    )
    if entity_id is None:
        return None
    component = hass.data.get(_COMPONENT_MAP[domain])
    return component.get_entity(entity_id) if component else None


def _to_24_hour(hour12: int, ampm: str) -> int:
    hour12 = int(hour12) % 12  # 12 AM/PM -> 0
    return hour12 + (12 if ampm == "PM" else 0)


def _to_12_hour(hour24: int) -> tuple[int, str]:
    ampm = "PM" if hour24 >= 12 else "AM"
    hour12 = hour24 % 12
    return (hour12 or 12), ampm


def compose_datetime(date_value: date_type, hour12: float, minute: float, ampm: str) -> datetime:
    """Combine a Date + Hour(1-12) + Minute + AM/PM field group into a real, timezone-AWARE
    `datetime` (HA's configured local zone) - required now that `events.py` calls the target
    calendar entity's `async_create_event` directly instead of through the `calendar.
    create_event` SERVICE, which normally does this localization step itself before the
    entity ever sees the value (live-verified: a naive datetime passed directly raises
    `Failed to validate CalendarEvent: Expected all values to have a timezone`).
    `dt_util.as_local` on an already-naive value attaches the local zone directly rather than
    treating it as UTC-and-converting - exactly "this wall-clock time IS local time", which is
    what a Date+Hour+Minute+AM-PM group means."""
    naive = datetime.combine(date_value, time(hour=_to_24_hour(hour12, ampm), minute=int(minute)))
    return dt_util.as_local(naive)


def _decompose_datetime(value: datetime) -> tuple[date_type, int, int, str]:
    hour12, ampm = _to_12_hour(value.hour)
    return value.date(), hour12, value.minute, ampm


async def async_recompute_end_from_start(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Read Start's Date/Hour/Minute/AM-PM; if Start Date is set, write End's own four fields
    to Start plus one hour. Called by each of Start's 4 field entities after their own value
    changes - see this module's docstring for why this is an unconditional overwrite."""
    start_date_entity = _sibling_entity(hass, entry, "date", EVENT_START_DATE_UNIQUE_ID)
    start_hour_entity = _sibling_entity(hass, entry, "number", EVENT_START_HOUR_UNIQUE_ID)
    start_minute_entity = _sibling_entity(hass, entry, "number", EVENT_START_MINUTE_UNIQUE_ID)
    start_ampm_entity = _sibling_entity(hass, entry, "select", EVENT_START_AMPM_UNIQUE_ID)
    if start_date_entity is None or start_date_entity.native_value is None:
        return
    if start_hour_entity is None or start_minute_entity is None or start_ampm_entity is None:
        return

    start_dt = compose_datetime(
        start_date_entity.native_value,
        start_hour_entity.native_value,
        start_minute_entity.native_value,
        start_ampm_entity.current_option,
    )
    end_date, end_hour, end_minute, end_ampm = _decompose_datetime(start_dt + timedelta(hours=1))

    end_date_entity = _sibling_entity(hass, entry, "date", EVENT_END_DATE_UNIQUE_ID)
    end_hour_entity = _sibling_entity(hass, entry, "number", EVENT_END_HOUR_UNIQUE_ID)
    end_minute_entity = _sibling_entity(hass, entry, "number", EVENT_END_MINUTE_UNIQUE_ID)
    end_ampm_entity = _sibling_entity(hass, entry, "select", EVENT_END_AMPM_UNIQUE_ID)
    if end_date_entity is not None:
        await end_date_entity.async_set_value(end_date)
    if end_hour_entity is not None:
        await end_hour_entity.async_set_native_value(end_hour)
    if end_minute_entity is not None:
        await end_minute_entity.async_set_native_value(end_minute)
    if end_ampm_entity is not None:
        await end_ampm_entity.async_select_option(end_ampm)
