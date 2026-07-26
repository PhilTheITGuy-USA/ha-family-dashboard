"""Shared cross-platform logic for the Add Event popup's Start/End time fields.

2026-07-26: reverted to a single combined `datetime.family_dashboard_event_start`/`_end`
entity per side (`datetime.py`) - a live preference for v0.9.0-beta.4's compact one-row-per-
side layout over the 2026-07-25 decomposed Date+Hour(1-12)+Minute+AM/PM redesign this module
used to own (see git history), which a live report called out as "far too many clicks and
opens sub windows to enter hour, days, etc".

This module briefly also owned a separate explicit AM/PM select per side plus an
`_apply_ampm_correction`/`resolve_event_datetime` step, on the assumption that HA's native
`datetime` picker's raw stored hour couldn't be trusted across viewers whose HA accounts have
different Time Format settings (12-hour vs 24-hour). Live-verified against HA's own frontend
source (`ha-time-input`'s `_timeChanged` handler) that this assumption was wrong: the widget
ALWAYS resolves to a correct, unambiguous absolute hour before the entity ever sees it,
regardless of which format was displayed - in 12-hour mode the SAME row includes its own
built-in AM/PM toggle (baked into `ha-base-time-input`, not something this integration
controls or needs to duplicate); in 24-hour mode the hour field itself accepts 0-23, so
there's no digit that could mean two different things. The bolt-on AM/PM select duplicated a
question the native row already answers in the same tap, and could actively corrupt a
correctly-entered 24-hour value if left at its default while the native widget's own value
was already right - removed entirely, not just hidden.

`async_recompute_end_datetime_from_start` is called by Start's own `datetime` entity after
every set - same "unconditionally overwrite End on every Start change, not just the first"
reasoning the original combined-datetime `_EventStartDateTime` used before the 2026-07-25
rewrite (see git history): the user's own subsequent edit to End is the last word, since
nothing else re-derives it except a further Start change.

`async_recompute_end_date_from_start_date` is the separate, much simpler all-day-only cascade
(`date.py`'s Start Date -> End Date) - kept distinct from the timed-event cascade above since
Date and `datetime` entities serve entirely different conditional branches of the popup
(all-day vs timed), not a shared field group the way Start/End Date briefly was during the
2026-07-25 redesign.
"""
from __future__ import annotations

from datetime import timedelta

import homeassistant.components.date as date_component
import homeassistant.components.datetime as datetime_component
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ...const import DOMAIN

EVENT_START_DATE_UNIQUE_ID = "event_start_date"
EVENT_END_DATE_UNIQUE_ID = "event_end_date"
EVENT_START_UNIQUE_ID = "event_start"
EVENT_END_UNIQUE_ID = "event_end"

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

_COMPONENT_MAP = {
    "date": date_component.DATA_COMPONENT,
    "datetime": datetime_component.DATA_COMPONENT,
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


async def async_recompute_end_datetime_from_start(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Read Start's `datetime`; if set, default End to Start plus one hour. Called by Start's
    own entity after every set - see this module's docstring for why this is an unconditional
    overwrite. Start's own value is trusted as-is (already a correct, fully-resolved absolute
    time regardless of the viewer's 12-vs-24-hour display - see this module's docstring)."""
    start_entity = _sibling_entity(hass, entry, "datetime", EVENT_START_UNIQUE_ID)
    if start_entity is None or start_entity.native_value is None:
        return

    end_entity = _sibling_entity(hass, entry, "datetime", EVENT_END_UNIQUE_ID)
    if end_entity is not None:
        await end_entity.async_set_value(start_entity.native_value + timedelta(hours=1))


async def async_recompute_end_date_from_start_date(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """All-day-only cascade: if Start Date is set, default End Date to the same day. Called by
    Start Date's own entity after every set (`date.py`) - the user's own subsequent End Date
    edit is the last word until Start Date changes again, same convention as the timed-event
    cascade above."""
    start_date_entity = _sibling_entity(hass, entry, "date", EVENT_START_DATE_UNIQUE_ID)
    if start_date_entity is None or start_date_entity.native_value is None:
        return
    end_date_entity = _sibling_entity(hass, entry, "date", EVENT_END_DATE_UNIQUE_ID)
    if end_date_entity is not None:
        await end_date_entity.async_set_value(start_date_entity.native_value)
