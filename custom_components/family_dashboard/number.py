"""Platform aggregator, NOT a plain 1:1 shim - Chores (points/cost fields, conditional on
"chores") and Calendar (Add Event popup's reminder lead-time fields, conditional on
"calendar") both need the `number` platform for the same config entry. Same shape as
text.py's aggregator - see that file's docstring.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FEATURES, CONF_ROSTER
from .modules.calendar.number import async_setup_entry as _calendar_setup_entry
from .modules.chores.number import async_setup_entry as _chores_setup_entry


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    features = {f for m in entry.data[CONF_ROSTER] for f in m.get(CONF_FEATURES, [])}
    if "chores" in features:
        await _chores_setup_entry(hass, entry, async_add_entities)
    if "calendar" in features:
        await _calendar_setup_entry(hass, entry, async_add_entities)
