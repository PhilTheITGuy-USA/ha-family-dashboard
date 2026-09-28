"""Tests for `user_watch.py` - the entry reloads when an HA user change affects the
generated dashboard: Kiosk-bucket membership, or a linked member's admin status (which
decides whether their own Settings tab carries the Features & Mapping controls)."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.family_dashboard.const import DOMAIN


def _member(member_id, name, ha_user_id):
    return {
        "member_id": member_id,
        "name": name,
        "color": "Blue",
        "features": ["lists"],
        "ha_user_id": ha_user_id,
        "calendar_entity_id": None,
        "notify_entity_id": None,
        "list_presets": ["shopping"],
    }


async def _setup(hass: HomeAssistant, roster) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={"roster": roster}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _settle(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()


async def test_linked_member_admin_change_reloads_entry(hass: HomeAssistant):
    await hass.auth.async_create_user(name="Kiosk Account")
    phil = await hass.auth.async_create_user(name="Phil Account", group_ids=[GROUP_ID_USER])
    entry = await _setup(hass, [_member("phil", "Phil", phil.id)])

    with patch.object(hass.config_entries, "async_reload") as reload:
        await hass.auth.async_update_user(phil, group_ids=[GROUP_ID_ADMIN])
        await _settle(hass)
    reload.assert_called_once_with(entry.entry_id)


async def test_irrelevant_user_update_does_not_reload(hass: HomeAssistant):
    await hass.auth.async_create_user(name="Kiosk Account")
    phil = await hass.auth.async_create_user(name="Phil Account", group_ids=[GROUP_ID_ADMIN])
    await _setup(hass, [_member("phil", "Phil", phil.id)])

    with patch.object(hass.config_entries, "async_reload") as reload:
        await hass.auth.async_update_user(phil, name="Phil Renamed")
        await _settle(hass)
    reload.assert_not_called()
