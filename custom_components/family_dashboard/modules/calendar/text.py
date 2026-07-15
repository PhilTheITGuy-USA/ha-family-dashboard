"""Household-scoped `text` scratch entities for the Add Event popup - title and description.
Deliberately NOT `RestoreEntity` - cleared after every submit (see `events.py`'s
`async_add_event`), mirroring the legacy `add_calendar_event` script's own post-submit reset,
so a stale draft never lingers into the next time someone opens the popup.

Forwarded once if any roster member has "calendar" enabled (see const.py's FEATURES entry).
Re-exported (aggregated alongside modules/chores/text.py and modules/settings/text.py) by the
top-level `text.py` shim - see that file's docstring.
"""
from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN


EVENT_TITLE_UNIQUE_ID = "event_title"
EVENT_DESCRIPTION_UNIQUE_ID = "event_description"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            _EventScratchText(entry, EVENT_TITLE_UNIQUE_ID, "Event Title"),
            _EventScratchText(entry, EVENT_DESCRIPTION_UNIQUE_ID, "Event Description"),
        ]
    )


class _EventScratchText(TextEntity):
    _attr_has_entity_name = True
    _attr_native_max = 200
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, unique_id_suffix: str, name: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_native_value = ""

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
