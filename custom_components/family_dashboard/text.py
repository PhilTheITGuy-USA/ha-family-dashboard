"""Platform aggregator, NOT a plain 1:1 shim - Settings (roster names, always-on), Chores &
Rewards (parent PIN, conditional on "chores"), and Calendar (Add Event scratch text,
conditional on "calendar") all need the `text` platform for the same config entry, and HA only
calls one async_setup_entry per (entry, platform) pair. This file calls each module's own
async_setup_entry with the same async_add_entities callback, gating each conditional one on
the feature actually being enabled anywhere (mirrors __init__.py's own platform-forwarding
logic - this just can't rely on that alone, since "text" is forwarded unconditionally for
Settings even when nobody has "chores"/"calendar").
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FEATURES, CONF_ROSTER
from .modules.calendar.text import async_setup_entry as _calendar_setup_entry
from .modules.chores.text import async_setup_entry as _chores_setup_entry
from .modules.settings.text import async_setup_entry as _settings_setup_entry


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await _settings_setup_entry(hass, entry, async_add_entities)

    features = {f for m in entry.data[CONF_ROSTER] for f in m.get(CONF_FEATURES, [])}
    if "chores" in features:
        await _chores_setup_entry(hass, entry, async_add_entities)
    if "calendar" in features:
        await _calendar_setup_entry(hass, entry, async_add_entities)
