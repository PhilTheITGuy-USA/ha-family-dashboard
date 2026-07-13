"""The Family Dashboard integration.

Settings/Roster is always-on core (see const.py's SETTINGS_PLATFORMS + the rebuild plan's
"Decided" section) - its platforms are forwarded unconditionally for every config entry.
Toggleable modules (Calendar/Lists/Chores & Rewards, per const.py's MODULES) only get their
platforms forwarded when selected in the wizard. Enabling a not-yet-implemented module today
is harmless - its stub platform file just logs a warning and adds zero entities (see
modules/calendar, modules/lists, modules/chores).

Dashboard generation/registration (dashboard/registry.py, dashboard/register.py) is
deliberately NOT wired in yet - see the TODO in async_setup_entry below.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MODULES, DOMAIN, MODULES, SETTINGS_PLATFORMS

_LOGGER = logging.getLogger(__name__)


def _platforms_for_entry(entry: ConfigEntry) -> list[str]:
    """Settings' platforms always, plus each selected module's platforms, de-duped."""
    platforms = list(SETTINGS_PLATFORMS)
    for module_key in entry.data.get(CONF_MODULES, []):
        module = MODULES.get(module_key)
        if module is None:
            _LOGGER.warning(
                "Family Dashboard: unknown module key '%s' in config entry, skipping",
                module_key,
            )
            continue
        platforms.extend(module["platforms"])

    seen: set[str] = set()
    deduped: list[str] = []
    for platform in platforms:
        if platform not in seen:
            seen.add(platform)
            deduped.append(platform)
    return deduped


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data

    platforms = _platforms_for_entry(entry)
    await hass.config_entries.async_forward_entry_setups(entry, platforms)

    # TODO(dashboard generation): once Calendar/Lists/Chores are real (not stubs), call
    # `dashboard.registry.async_build_dashboard_config(hass, entry)` and
    # `dashboard.register.async_register_dashboard(hass, entry, config)` here. Left out of
    # this scaffold deliberately - generating a dashboard around stub/empty modules would
    # just produce an empty shell, and shipping a dashboard step that doesn't reflect
    # what's actually real yet is the same class of mistake this rebuild exists to fix.
    _LOGGER.info(
        "Family Dashboard: set up entry %s with platforms %s (dashboard generation not "
        "yet wired in - see the TODO in __init__.py)",
        entry.entry_id,
        platforms,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    platforms = _platforms_for_entry(entry)
    unloaded = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
