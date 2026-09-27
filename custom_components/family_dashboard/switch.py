"""Platform aggregator, NOT a plain 1:1 shim - Settings (per-member "shown" toggle,
always-on), Calendar (Birthdays/Holidays toggles + Add Event scratch switches, conditional
on "calendar") and Chores (per-chore Reminders toggles, conditional on "chores") all need
the `switch` platform for the same config entry. Same shape as text.py's aggregator - see
that file's docstring.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FEATURES, CONF_ROSTER
from .entity_ids import pin_entity_ids
from .modules.calendar.switch import async_setup_entry as _calendar_setup_entry
from .modules.chores.switch import async_setup_entry as _chores_setup_entry
from .modules.settings.switch import async_setup_entry as _settings_setup_entry


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities = pin_entity_ids("switch", async_add_entities)
    await _settings_setup_entry(hass, entry, async_add_entities)

    features = {f for m in entry.data[CONF_ROSTER] for f in m.get(CONF_FEATURES, [])}
    if "calendar" in features:
        await _calendar_setup_entry(hass, entry, async_add_entities)
    if "chores" in features:
        await _chores_setup_entry(hass, entry, async_add_entities)
