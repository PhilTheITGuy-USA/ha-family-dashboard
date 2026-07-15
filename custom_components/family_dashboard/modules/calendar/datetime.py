"""Household-scoped `datetime` scratch entities for the Add Event popup's timed-event start/
end fields (the all-day variant uses `date.py` instead). Not `RestoreEntity` - cleared after
every submit, see `events.py`.

Forwarded once if any roster member has "calendar" enabled. 1:1 shim at the top-level
`datetime.py` (only Calendar uses this platform, unlike text/select/switch - no aggregation
needed).
"""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN

EVENT_START_UNIQUE_ID = "event_start"
EVENT_END_UNIQUE_ID = "event_end"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            _EventScratchDateTime(entry, EVENT_START_UNIQUE_ID, "Event Start"),
            _EventScratchDateTime(entry, EVENT_END_UNIQUE_ID, "Event End"),
        ]
    )


class _EventScratchDateTime(DateTimeEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, unique_id_suffix: str, name: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_native_value: datetime | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_value(self, value: datetime) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
