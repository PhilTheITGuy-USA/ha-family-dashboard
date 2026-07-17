"""The Family Dashboard integration.

Settings/Roster is always-on core (see const.py's SETTINGS_PLATFORMS + the rebuild plan's
"Decided" section) - its platforms are forwarded unconditionally for every config entry.
Toggleable features (Calendar/Lists/Chores & Rewards, per const.py's FEATURES) are
per-roster-member, not household-wide: a feature's platforms are forwarded once a config
entry exists if ANY roster member has opted into it, but each feature's own
`async_setup_entry` is responsible for filtering the roster down to just the members who
opted in before creating entities (not "everyone" or "no one" - see modules/__init__.py).
Enabling a not-yet-implemented feature today is harmless - its stub platform file just logs
a warning and adds zero entities (see modules/calendar, modules/lists, modules/chores).

Dashboard generation/registration (dashboard/registry.py, dashboard/register.py) runs at
the end of every entry setup - see async_setup_entry below. Currently only the Family
Calendar view is built (dashboard/registry.py is being filled in one view per session -
see its module docstring); Lists/Chores/Settings views land in later sessions without
needing to restructure this call site.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .assets import async_seed_assets
from .const import CONF_FEATURES, CONF_ROSTER, DOMAIN, FEATURES, SETTINGS_PLATFORMS
from .dashboard.register import async_register_dashboard, async_register_strategy_resource
from .dashboard.registry import async_build_dashboard_config
from .holidays_setup import async_ensure_default_holidays
from .unmapped_users import async_check_unmapped_users
from .user_watch import async_register_user_change_listener

_LOGGER = logging.getLogger(__name__)


def _platforms_for_entry(entry: ConfigEntry) -> list[str]:
    """Settings' platforms always, plus the union of every roster member's selected
    features' platforms, de-duped (each platform forwarded once even if multiple members
    opted into the feature(s) that need it).
    """
    platforms = list(SETTINGS_PLATFORMS)
    for member in entry.data.get(CONF_ROSTER, []):
        for feature_key in member.get(CONF_FEATURES, []):
            feature = FEATURES.get(feature_key)
            if feature is None:
                _LOGGER.warning(
                    "Family Dashboard: unknown feature key '%s' for roster member '%s', "
                    "skipping",
                    feature_key,
                    member.get("member_id", "?"),
                )
                continue
            platforms.extend(feature["platforms"])

    seen: set[str] = set()
    deduped: list[str] = []
    for platform in platforms:
        if platform not in seen:
            seen.add(platform)
            deduped.append(platform)
    return deduped


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # A mutable dict, not entry.data directly - modules/calendar/calendar.py's
    # async_setup_entry stashes its live calendar_entities map + reminder-engine unsub here
    # (see modules/calendar/reminders.py) so async_unload_entry below can clean it up.
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"data": entry.data}

    # Seeded BEFORE platform forwarding, and the resulting file list stashed here -
    # modules/settings/select.py's RosterAvatarSelect reads hass.data[DOMAIN][entry_id]
    # ["avatar_files"] as its deterministic startup fallback (see assets.py's
    # async_seed_assets docstring for why reading the avatars sensor's live state alone isn't
    # safe at entity-construction time).
    hass.data[DOMAIN][entry.entry_id]["avatar_files"] = await async_seed_assets(hass)

    # Best-effort - never blocks our own setup even if it fails (see its own docstring).
    await async_ensure_default_holidays(hass)

    platforms = _platforms_for_entry(entry)
    await hass.config_entries.async_forward_entry_setups(entry, platforms)

    # Registered before the dashboard config itself, so the strategy's custom element is
    # already resolvable by the time any browser tries to load a view using it.
    await async_register_strategy_resource(hass)

    dashboard_config = await async_build_dashboard_config(hass, entry)
    await async_register_dashboard(hass, entry, dashboard_config)

    # Keeps the Kiosk bucket from going stale if an HA user account is added/removed/changed
    # after this setup pass - see user_watch.py's module docstring for the live-verified gap
    # this closes (a new, unlinked user saw a blank dashboard until a manual reload).
    hass.data[DOMAIN][entry.entry_id][
        "user_change_unsub"
    ] = await async_register_user_change_listener(hass, entry)

    # Repair Issue per active, non-system HA user not linked to any roster member - see
    # unmapped_users.py's module docstring for why this doesn't need its own "ignore list"
    # (HA's own Repairs "Ignore" action already persists across every future call here).
    await async_check_unmapped_users(hass, entry)

    _LOGGER.info(
        "Family Dashboard: set up entry %s with platforms %s, dashboard registered",
        entry.entry_id,
        platforms,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    platforms = _platforms_for_entry(entry)
    unloaded = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unloaded:
        domain_data = hass.data[DOMAIN].pop(entry.entry_id, {})
        if reminder_unsub := domain_data.get("reminder_unsub"):
            reminder_unsub()
        if user_change_unsub := domain_data.get("user_change_unsub"):
            user_change_unsub()
    return unloaded
