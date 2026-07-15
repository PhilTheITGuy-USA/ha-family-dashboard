"""Platform aggregator, NOT a plain 1:1 shim - Settings (roster color/avatar, always-on),
Calendar (view selector + Add Event's target-calendar picker, conditional on any roster member
having "calendar" enabled), and Chores (frequency/assigned-to fields, conditional on any
roster member having "chores" enabled) all need the `select` platform for the same config
entry. Same shape as text.py's aggregator - see that file's docstring.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FEATURES, CONF_ROSTER
from .modules.calendar.select import async_setup_entry as _calendar_setup_entry
from .modules.chores.select import async_setup_entry as _chores_setup_entry
from .modules.settings.select import async_setup_entry as _settings_setup_entry


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await _settings_setup_entry(hass, entry, async_add_entities)

    if any("calendar" in member.get(CONF_FEATURES, []) for member in entry.data[CONF_ROSTER]):
        await _calendar_setup_entry(hass, entry, async_add_entities)

    if any("chores" in member.get(CONF_FEATURES, []) for member in entry.data[CONF_ROSTER]):
        await _chores_setup_entry(hass, entry, async_add_entities)
