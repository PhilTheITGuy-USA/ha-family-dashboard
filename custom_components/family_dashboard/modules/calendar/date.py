"""Household-scoped `date` scratch entities for the Add Event popup's all-day-event start/end
fields (the timed variant uses `datetime.py` instead). Not `RestoreEntity` - cleared after
every submit, see `events.py`.

Forwarded once if any roster member has "calendar" enabled. Aggregated (alongside
`modules/settings/date.py`'s always-on roster-birthdate fields) by the top-level `date.py`
shim - see that file's docstring for why.
"""
from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN

EVENT_START_DATE_UNIQUE_ID = "event_start_date"
EVENT_END_DATE_UNIQUE_ID = "event_end_date"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            _EventScratchDate(entry, EVENT_START_DATE_UNIQUE_ID, "Event Start Date"),
            _EventScratchDate(entry, EVENT_END_DATE_UNIQUE_ID, "Event End Date"),
        ]
    )


class _EventScratchDate(DateEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-today"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, unique_id_suffix: str, name: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_native_value: date | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_value(self, value: date) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
