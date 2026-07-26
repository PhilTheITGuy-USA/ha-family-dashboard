"""Household-scoped `date` scratch entities for the Add Event popup's Start/End DATE fields -
shared between all-day and timed events alike (only the time-of-day portion differs; see
`number.py`/`select.py` for the Hour/Minute/AM-PM fields timed events layer on top). Not
`RestoreEntity` - cleared after every submit, see `events.py`.

Forwarded once if any roster member has "calendar" enabled. Aggregated (alongside
`modules/settings/date.py`'s always-on roster-birthdate fields) by the top-level `date.py`
shim - see that file's docstring for why.

The Start Date field (`_EventStartDate`) triggers `event_time.async_recompute_end_from_start`
on every set, same as Start's Hour/Minute/AM-PM fields (`number.py`/`select.py`) - see that
function's own docstring for the full "unconditional overwrite" reasoning. Unique-id constants
for this whole 8-field group live in `event_time.py`, not here - see its own docstring for why.
"""
from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN
from .event_time import (
    EVENT_END_DATE_UNIQUE_ID,
    EVENT_START_DATE_UNIQUE_ID,
    async_recompute_end_from_start,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            _EventStartDate(entry, EVENT_START_DATE_UNIQUE_ID, "Event Start Date"),
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


class _EventStartDate(_EventScratchDate):
    """The Add Event popup's Start Date field - see `event_time.async_recompute_end_from_start`
    for what happens on every set."""

    async def async_set_value(self, value: date) -> None:
        await super().async_set_value(value)
        await async_recompute_end_from_start(self.hass, self._entry)
