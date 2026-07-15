"""Platform aggregator, NOT a plain 1:1 shim - Settings (roster birthdates, always-on) and
Calendar (Add Event scratch start/end dates, conditional on "calendar") both need the `date`
platform for the same config entry, and HA only calls one async_setup_entry per (entry,
platform) pair. Same shape as the top-level `text.py`'s own aggregator.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FEATURES, CONF_ROSTER
from .modules.calendar.date import async_setup_entry as _calendar_setup_entry
from .modules.settings.date import async_setup_entry as _settings_setup_entry


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await _settings_setup_entry(hass, entry, async_add_entities)

    features = {f for m in entry.data[CONF_ROSTER] for f in m.get(CONF_FEATURES, [])}
    if "calendar" in features:
        await _calendar_setup_entry(hass, entry, async_add_entities)
