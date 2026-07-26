"""Add Event popup's submit logic - reads every scratch field (title/description, all-day
flag, Start/End Date+Hour+Minute+AM-PM, weeks/days/hours/minutes-before reminder fields,
Recurring flag + Recurrence preset, target calendar), calls the target calendar entity's
`async_create_event` DIRECTLY (see below for why, not via the `calendar.create_event`
service), appends `[[reminder:...]]` tag(s) for whichever lead-time fields were non-zero,
then clears every scratch field - mirroring the legacy `add_calendar_event` script's own
field/branching logic and post-submit reset (see `family_hub_calendar.yaml`), but built on
this integration's own owned entities instead of `input_*` helpers.

Calls the target CalendarEntity's `async_create_event` directly instead of going through
`hass.services.async_call("calendar", "create_event", ...)` - a live-verified requirement for
Recurring support: `homeassistant.components.calendar`'s own `CREATE_EVENT_SCHEMA` (checked
directly against the installed HA source) has NO `rrule` field at all, so the SERVICE call
would reject one outright even though the underlying entities happily accept it - both
`local_calendar.LocalCalendarEntity.async_create_event` and
`google.calendar.GoogleCalendarEntity.async_create_event` (the two backends this project
supports, per SETUP.md) read an `rrule` kwarg directly and hand it to their own ical/RRULE
parser. Bypassing the service is safe here since it's the same trust boundary as this
function's own direct scratch-entity manipulation elsewhere (the user never gets raw API
access, only through this one integration-owned button) - we do replicate the service
handler's own `CalendarEntityFeature.CREATE_EVENT` support check ourselves, so an
incompatible calendar backend still fails with a friendly `HomeAssistantError` instead of a
raw `NotImplementedError`.

The `family_dashboard.add_event` service is registered on `FamilyDashboardEventCalendarSelect`
(see `select.py`) since that entity already represents "which calendar" - this module holds
the actual cross-entity logic so that class stays a plain entity, not a grab-bag.
"""
from __future__ import annotations

import homeassistant.components.calendar as calendar_component
import homeassistant.components.date as date_component
import homeassistant.components.number as number_component
import homeassistant.components.select as select_component
import homeassistant.components.switch as switch_component
import homeassistant.components.text as text_component
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from ...const import CONF_CALENDAR_ENTITY_ID, CONF_ROSTER, DOMAIN
from .dashboard import _family_calendar_entity
from .event_time import (
    DEFAULT_END_HOUR,
    DEFAULT_MINUTE,
    DEFAULT_START_HOUR,
    EVENT_END_AMPM_UNIQUE_ID,
    EVENT_END_DATE_UNIQUE_ID,
    EVENT_END_HOUR_UNIQUE_ID,
    EVENT_END_MINUTE_UNIQUE_ID,
    EVENT_RECURRENCE_UNIQUE_ID,
    EVENT_RECURRING_UNIQUE_ID,
    EVENT_START_AMPM_UNIQUE_ID,
    EVENT_START_DATE_UNIQUE_ID,
    EVENT_START_HOUR_UNIQUE_ID,
    EVENT_START_MINUTE_UNIQUE_ID,
    compose_datetime,
)
from .number import (
    EVENT_REMIND_DAYS_UNIQUE_ID,
    EVENT_REMIND_HOURS_UNIQUE_ID,
    EVENT_REMIND_MINUTES_UNIQUE_ID,
    EVENT_REMIND_WEEKS_UNIQUE_ID,
)
from .switch import EVENT_ALL_DAY_UNIQUE_ID
from .text import EVENT_DESCRIPTION_UNIQUE_ID, EVENT_TITLE_UNIQUE_ID

# Bare FREQ (no BYDAY/BYMONTHDAY) anchors to DTSTART's own weekday/day-of-month per RFC5545's
# default recurrence-set expansion, so we don't need to compute those ourselves - live-verified
# against both supported calendar backends' own rrule handling (see this module's docstring).
_RECURRENCE_RRULES = {
    "Daily": "FREQ=DAILY",
    "Weekly": "FREQ=WEEKLY",
    "Monthly": "FREQ=MONTHLY",
    "Annually": "FREQ=YEARLY",
    "Every Weekday": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
}


def _entity(hass: HomeAssistant, domain: str, unique_id_suffix: str, entry: ConfigEntry):
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{unique_id_suffix}"
    )
    if entity_id is None:
        return None
    component_map = {
        "text": text_component.DATA_COMPONENT,
        "switch": switch_component.DATA_COMPONENT,
        "date": date_component.DATA_COMPONENT,
        "number": number_component.DATA_COMPONENT,
        "select": select_component.DATA_COMPONENT,
    }
    component = hass.data.get(component_map[domain])
    return component.get_entity(entity_id) if component else None


def _target_calendar_entity_id(hass: HomeAssistant, entry: ConfigEntry, calendar_name: str) -> str:
    if calendar_name == "Family":
        family_calendar = _family_calendar_entity(hass)
        if family_calendar is None:
            raise HomeAssistantError("No Family calendar is configured")
        return family_calendar[0]

    roster = entry.data[CONF_ROSTER]
    member = next((m for m in roster if m["name"] == calendar_name), None)
    if member is None or not member.get(CONF_CALENDAR_ENTITY_ID):
        raise HomeAssistantError(f"'{calendar_name}' has no mapped calendar")
    return f"calendar.family_dashboard_{member['member_id']}_calendar"


def _resolve_calendar_entity(hass: HomeAssistant, entity_id: str) -> calendar_component.CalendarEntity:
    component = hass.data.get(calendar_component.DATA_COMPONENT)
    entity = component.get_entity(entity_id) if component else None
    if entity is None:
        raise HomeAssistantError(f"Calendar '{entity_id}' is not available")
    if not entity.supported_features & calendar_component.CalendarEntityFeature.CREATE_EVENT:
        raise HomeAssistantError(f"Calendar '{entity_id}' does not support creating events")
    return entity


async def async_create_event_from_scratch_fields(
    hass: HomeAssistant, entry: ConfigEntry, calendar_name: str
) -> None:
    target_entity_id = _target_calendar_entity_id(hass, entry, calendar_name)
    calendar_entity = _resolve_calendar_entity(hass, target_entity_id)

    title_entity = _entity(hass, "text", EVENT_TITLE_UNIQUE_ID, entry)
    description_entity = _entity(hass, "text", EVENT_DESCRIPTION_UNIQUE_ID, entry)
    all_day_entity = _entity(hass, "switch", EVENT_ALL_DAY_UNIQUE_ID, entry)

    title = title_entity.native_value if title_entity else ""
    description = description_entity.native_value if description_entity else ""
    all_day = bool(all_day_entity and all_day_entity.is_on)

    weeks_entity = _entity(hass, "number", EVENT_REMIND_WEEKS_UNIQUE_ID, entry)
    days_entity = _entity(hass, "number", EVENT_REMIND_DAYS_UNIQUE_ID, entry)
    hours_entity = _entity(hass, "number", EVENT_REMIND_HOURS_UNIQUE_ID, entry)
    minutes_entity = _entity(hass, "number", EVENT_REMIND_MINUTES_UNIQUE_ID, entry)
    weeks = int(weeks_entity.native_value or 0) if weeks_entity else 0
    days = int(days_entity.native_value or 0) if days_entity else 0
    hours = int(hours_entity.native_value or 0) if hours_entity else 0
    minutes = int(minutes_entity.native_value or 0) if minutes_entity else 0

    # Each non-zero field is its own independent [[reminder:...]] tag (see reminders.py's
    # multi-tag support) - weeks/days translate to the tag format's "d" component (there's no
    # "w"), hours+minutes combine into one tag since they're the same granularity tier.
    reminder_tags = ""
    if weeks:
        reminder_tags += f" [[reminder:{weeks * 7}d]]"
    if days:
        reminder_tags += f" [[reminder:{days}d]]"
    if hours or minutes:
        hours_part = f"{hours}h" if hours else ""
        minutes_part = f"{minutes}m" if minutes else ""
        reminder_tags += f" [[reminder:{hours_part}{minutes_part}]]"

    full_description = f"{description or ''}{reminder_tags}"

    recurring_entity = _entity(hass, "switch", EVENT_RECURRING_UNIQUE_ID, entry)
    recurrence_entity = _entity(hass, "select", EVENT_RECURRENCE_UNIQUE_ID, entry)
    rrule = None
    if recurring_entity and recurring_entity.is_on and recurrence_entity:
        rrule = _RECURRENCE_RRULES.get(recurrence_entity.current_option)

    create_kwargs: dict = {"summary": title or "", "description": full_description}
    if rrule:
        create_kwargs["rrule"] = rrule

    start_date_entity = _entity(hass, "date", EVENT_START_DATE_UNIQUE_ID, entry)
    end_date_entity = _entity(hass, "date", EVENT_END_DATE_UNIQUE_ID, entry)
    start_hour_entity = _entity(hass, "number", EVENT_START_HOUR_UNIQUE_ID, entry)
    start_minute_entity = _entity(hass, "number", EVENT_START_MINUTE_UNIQUE_ID, entry)
    start_ampm_entity = _entity(hass, "select", EVENT_START_AMPM_UNIQUE_ID, entry)
    end_hour_entity = _entity(hass, "number", EVENT_END_HOUR_UNIQUE_ID, entry)
    end_minute_entity = _entity(hass, "number", EVENT_END_MINUTE_UNIQUE_ID, entry)
    end_ampm_entity = _entity(hass, "select", EVENT_END_AMPM_UNIQUE_ID, entry)

    if all_day:
        if not start_date_entity or not end_date_entity or not start_date_entity.native_value or not end_date_entity.native_value:
            raise HomeAssistantError("Event start/end date is required")
        create_kwargs["dtstart"] = start_date_entity.native_value
        create_kwargs["dtend"] = end_date_entity.native_value
    else:
        required = (
            start_date_entity, start_hour_entity, start_minute_entity, start_ampm_entity,
            end_date_entity, end_hour_entity, end_minute_entity, end_ampm_entity,
        )
        if any(e is None for e in required) or not start_date_entity.native_value or not end_date_entity.native_value:
            raise HomeAssistantError("Event start/end time is required")
        create_kwargs["dtstart"] = compose_datetime(
            start_date_entity.native_value, start_hour_entity.native_value,
            start_minute_entity.native_value, start_ampm_entity.current_option,
        )
        create_kwargs["dtend"] = compose_datetime(
            end_date_entity.native_value, end_hour_entity.native_value,
            end_minute_entity.native_value, end_ampm_entity.current_option,
        )

    await calendar_entity.async_create_event(**create_kwargs)

    if title_entity:
        await title_entity.async_set_value("")
    if description_entity:
        await description_entity.async_set_value("")
    if all_day_entity:
        await all_day_entity.async_turn_off()
    for number_entity in (weeks_entity, days_entity, hours_entity, minutes_entity):
        if number_entity:
            await number_entity.async_set_native_value(0)
    if recurring_entity:
        await recurring_entity.async_turn_off()
    if start_hour_entity:
        await start_hour_entity.async_set_native_value(DEFAULT_START_HOUR)
    if start_minute_entity:
        await start_minute_entity.async_set_native_value(DEFAULT_MINUTE)
    if start_ampm_entity:
        await start_ampm_entity.async_select_option("AM")
    if end_hour_entity:
        await end_hour_entity.async_set_native_value(DEFAULT_END_HOUR)
    if end_minute_entity:
        await end_minute_entity.async_set_native_value(DEFAULT_MINUTE)
    if end_ampm_entity:
        await end_ampm_entity.async_select_option("AM")
