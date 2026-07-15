"""Tests for `unmapped_users.py` - the Repair Issue raised for any active, non-system HA user
not linked to a Family Dashboard roster member. Covers: an unmapped user gets an issue, a
linked user doesn't, system-generated/inactive users are ignored entirely, a stale issue
clears once its user is added to the roster, and - the whole point of building this - an
"Ignore"d issue stays ignored across every future re-check.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_dashboard.const import DOMAIN
from custom_components.family_dashboard.unmapped_users import (
    _issue_id,
    async_check_unmapped_users,
)


def _member(member_id, name, ha_user_id=None):
    return {
        "member_id": member_id,
        "name": name,
        "color": "Blue",
        "features": [],
        "ha_user_id": ha_user_id,
        "calendar_entity_id": None,
        "notify_entity_id": None,
        "list_presets": [],
    }


async def _setup_entry(hass: HomeAssistant, roster: list[dict]) -> MockConfigEntry:
    entry = MockConfigEntry(
        version=1, domain=DOMAIN, title="Family Dashboard", data={"roster": roster},
        source="user", unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_unmapped_active_user_gets_issue(hass: HomeAssistant):
    user = await hass.auth.async_create_user(name="Gerald")
    await _setup_entry(hass, [])

    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, _issue_id(user.id))
    assert issue is not None
    assert issue.translation_placeholders == {"name": "Gerald"}


async def test_linked_user_gets_no_issue(hass: HomeAssistant):
    user = await hass.auth.async_create_user(name="Ada Account")
    await _setup_entry(hass, [_member("ada", "Ada", ha_user_id=user.id)])

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, _issue_id(user.id)) is None


async def test_system_generated_user_ignored(hass: HomeAssistant):
    system_user = await hass.auth.async_create_system_user(name="Supervisor")
    await _setup_entry(hass, [])

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, _issue_id(system_user.id)) is None


async def test_inactive_user_ignored(hass: HomeAssistant):
    # The first user created in a fresh test `hass` becomes the owner, and HA refuses to
    # deactivate the owner - create a throwaway one first so "Old Account" isn't it.
    await hass.auth.async_create_user(name="Owner Account")
    user = await hass.auth.async_create_user(name="Old Account")
    await hass.auth.async_deactivate_user(user)
    await _setup_entry(hass, [])

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, _issue_id(user.id)) is None


async def test_stale_issue_cleared_once_user_added_to_roster(hass: HomeAssistant):
    user = await hass.auth.async_create_user(name="Gerald")
    entry = await _setup_entry(hass, [])

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, _issue_id(user.id)) is not None

    # Link the user to a new roster member directly (mirrors what the Options Flow's
    # "Add Member" step does) and re-run the same check the way a reload would.
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "roster": [_member("gerald", "Gerald", ha_user_id=user.id)]}
    )
    await async_check_unmapped_users(hass, entry)

    assert registry.async_get_issue(DOMAIN, _issue_id(user.id)) is None


async def test_ignored_issue_stays_ignored_across_recheck(hass: HomeAssistant):
    """The whole point of this feature: dismissing an issue in Settings > Repairs is a real,
    permanent per-user off-switch - re-running the check (as every future reload does) must
    not resurrect it."""
    user = await hass.auth.async_create_user(name="Kiosk Device Account")
    entry = await _setup_entry(hass, [])

    registry = ir.async_get(hass)
    issue_id = _issue_id(user.id)
    assert registry.async_get_issue(DOMAIN, issue_id).dismissed_version is None

    ir.async_ignore_issue(hass, DOMAIN, issue_id, True)
    assert registry.async_get_issue(DOMAIN, issue_id).dismissed_version is not None

    # Re-run the check again (same as it running on every future entry reload/HA restart).
    await async_check_unmapped_users(hass, entry)
    await async_check_unmapped_users(hass, entry)

    assert registry.async_get_issue(DOMAIN, issue_id) is not None
    assert registry.async_get_issue(DOMAIN, issue_id).dismissed_version is not None
