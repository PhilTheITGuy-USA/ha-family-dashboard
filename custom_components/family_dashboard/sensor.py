"""Platform aggregator, NOT a plain 1:1 shim - Settings (avatars sensor, always-on) and
Chores & Rewards (points/task sensors, conditional on any roster member having "chores"
enabled) both need the `sensor` platform for the same config entry, and HA only calls one
async_setup_entry per (entry, platform) pair. Same shape as text.py's aggregator - see that
file's docstring.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FEATURES, CONF_ROSTER
from .modules.chores.sensor import async_setup_entry as _chores_setup_entry
from .modules.settings.sensor import async_setup_entry as _settings_setup_entry


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await _settings_setup_entry(hass, entry, async_add_entities)

    if any("chores" in member.get(CONF_FEATURES, []) for member in entry.data[CONF_ROSTER]):
        await _chores_setup_entry(hass, entry, async_add_entities)
