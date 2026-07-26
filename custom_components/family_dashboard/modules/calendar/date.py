"""Household-scoped `date` scratch entities for the Add Event popup's Start/End Date fields -
used ONLY for all-day events (a timed event uses `datetime.py`'s combined Start/End field
instead; see `event_time.py`'s docstring for why the two are separate branches again as of
2026-07-26, not a shared field group the way they briefly were during the 2026-07-25
decomposed-time redesign). Not `RestoreEntity` - cleared after every submit, see `events.py`.

Forwarded once if any roster member has "calendar" enabled. Aggregated (alongside
`modules/settings/date.py`'s always-on roster-birthdate fields) by the top-level `date.py`
shim - see that file's docstring for why.

The Start Date field (`_EventStartDate`) triggers `event_time.async_recompute_end_date_from_
start_date` on every set (defaulting End Date to the same day) - see that function's own
docstring.
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
    async_recompute_end_date_from_start_date,
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
    """The Add Event popup's Start Date field (all-day only) - see `event_time.
    async_recompute_end_date_from_start_date` for what happens on every set."""

    async def async_set_value(self, value: date) -> None:
        await super().async_set_value(value)
        await async_recompute_end_date_from_start_date(self.hass, self._entry)
