"""Add Event popup's submit logic - reads every scratch field (title/description, all-day
flag, start/end date-or-datetime, target calendar, Week/Day/Hour reminder checkboxes), calls
the target calendar's `create_event`, appends `[[reminder:...]]` tag(s) for whichever lead
times were checked, then clears every scratch field - mirroring the legacy
`add_calendar_event` script's own field/branching logic and post-submit reset (see
`family_hub_calendar.yaml`), but built on this integration's own owned entities instead of
`input_*` helpers.

The `family_dashboard.add_event` service is registered on `FamilyDashboardEventCalendarSelect`
(see `select.py`) since that entity already represents "which calendar" - this module holds
the actual cross-entity logic so that class stays a plain entity, not a grab-bag.
"""
from __future__ import annotations

import homeassistant.components.date as date_component
import homeassistant.components.datetime as datetime_component
import homeassistant.components.switch as switch_component
import homeassistant.components.text as text_component
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from ...const import (
    CONF_CALENDAR_ENTITY_ID,
    CONF_ROSTER,
    DOMAIN,
    REMINDER_LEAD_TIMES,
)
from .dashboard import _family_calendar_entity
from .date import EVENT_END_DATE_UNIQUE_ID, EVENT_START_DATE_UNIQUE_ID
from .datetime import EVENT_END_UNIQUE_ID, EVENT_START_UNIQUE_ID
from .switch import EVENT_ALL_DAY_UNIQUE_ID, reminder_switch_unique_id
from .text import EVENT_DESCRIPTION_UNIQUE_ID, EVENT_TITLE_UNIQUE_ID


def _entity(hass: HomeAssistant, domain: str, unique_id_suffix: str, entry: ConfigEntry):
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{unique_id_suffix}"
    )
    if entity_id is None:
        return None
    component_map = {
        "text": text_component.DATA_COMPONENT,
        "switch": switch_component.DATA_COMPONENT,
        "datetime": datetime_component.DATA_COMPONENT,
        "date": date_component.DATA_COMPONENT,
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


async def async_create_event_from_scratch_fields(
    hass: HomeAssistant, entry: ConfigEntry, calendar_name: str
) -> None:
    target_entity_id = _target_calendar_entity_id(hass, entry, calendar_name)

    title_entity = _entity(hass, "text", EVENT_TITLE_UNIQUE_ID, entry)
    description_entity = _entity(hass, "text", EVENT_DESCRIPTION_UNIQUE_ID, entry)
    all_day_entity = _entity(hass, "switch", EVENT_ALL_DAY_UNIQUE_ID, entry)

    title = title_entity.native_value if title_entity else ""
    description = description_entity.native_value if description_entity else ""
    all_day = bool(all_day_entity and all_day_entity.is_on)

    reminder_tags = ""
    reminder_switches = []
    for key, tag_value in REMINDER_LEAD_TIMES.items():
        switch_entity = _entity(hass, "switch", reminder_switch_unique_id(key), entry)
        reminder_switches.append(switch_entity)
        if switch_entity and switch_entity.is_on:
            reminder_tags += f" [[reminder:{tag_value}]]"

    full_description = f"{description or ''}{reminder_tags}"

    service_data: dict = {"summary": title or "", "description": full_description}
    if all_day:
        start_entity = _entity(hass, "date", EVENT_START_DATE_UNIQUE_ID, entry)
        end_entity = _entity(hass, "date", EVENT_END_DATE_UNIQUE_ID, entry)
        if start_entity is None or end_entity is None or not start_entity.native_value or not end_entity.native_value:
            raise HomeAssistantError("Event start/end date is required")
        service_data["start_date"] = start_entity.native_value
        service_data["end_date"] = end_entity.native_value
    else:
        start_entity = _entity(hass, "datetime", EVENT_START_UNIQUE_ID, entry)
        end_entity = _entity(hass, "datetime", EVENT_END_UNIQUE_ID, entry)
        if start_entity is None or end_entity is None or not start_entity.native_value or not end_entity.native_value:
            raise HomeAssistantError("Event start/end time is required")
        service_data["start_date_time"] = start_entity.native_value
        service_data["end_date_time"] = end_entity.native_value

    await hass.services.async_call(
        "calendar", "create_event", service_data, target={"entity_id": target_entity_id}, blocking=True
    )

    if title_entity:
        await title_entity.async_set_value("")
    if description_entity:
        await description_entity.async_set_value("")
    if all_day_entity:
        await all_day_entity.async_turn_off()
    for switch_entity in reminder_switches:
        if switch_entity:
            await switch_entity.async_turn_off()
