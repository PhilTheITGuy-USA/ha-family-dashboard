"""Platform aggregator, NOT a plain 1:1 shim - Settings (per-member "shown" toggle,
always-on) and Calendar (Birthdays/Holidays toggles + Add Event scratch switches, conditional
on "calendar") both need the `switch` platform for the same config entry. Same shape as
text.py's aggregator - see that file's docstring.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FEATURES, CONF_ROSTER
from .modules.calendar.switch import async_setup_entry as _calendar_setup_entry
from .modules.settings.switch import async_setup_entry as _settings_setup_entry


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await _settings_setup_entry(hass, entry, async_add_entities)

    if any("calendar" in member.get(CONF_FEATURES, []) for member in entry.data[CONF_ROSTER]):
        await _calendar_setup_entry(hass, entry, async_add_entities)
