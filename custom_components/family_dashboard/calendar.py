"""Platform shim - HA requires platform files at the integration's top level.

Real entity classes live in modules/calendar/calendar.py, grouped there for clarity/module
ownership. This file just delegates to the module's async_setup_entry, pinning entity IDs on
the way (see entity_ids.py).
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_ids import pin_entity_ids
from .modules.calendar.calendar import async_setup_entry as _module_setup_entry


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await _module_setup_entry(hass, entry, pin_entity_ids("calendar", async_add_entities))
