"""Tests for `modules/calendar/reminders.py`'s `async_resolve_member_notify_targets` - who
gets a member's reminders. Covers: an explicit manual `notify_entity_id` always wins; absent
that, a linked HA user's live `mobile_app` device notify entity is auto-resolved (found via
that device's config entry `user_id`, matching the real `mobile_app` integration's own data
shape - not stored anywhere, so a NEW device registered later for the same user is picked up
without any config change); no target when neither applies.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_dashboard.modules.calendar.reminders import (
    async_resolve_member_notify_targets,
)


async def test_manual_mapping_wins_even_when_linked_to_ha_user(hass: HomeAssistant):
    user = await hass.auth.async_create_user(name="Ada Account")
    member = {"ha_user_id": user.id, "notify_entity_id": "notify.manual_target"}
    assert await async_resolve_member_notify_targets(hass, member) == ["notify.manual_target"]


async def test_auto_resolves_linked_users_mobile_app_device(hass: HomeAssistant):
    user = await hass.auth.async_create_user(name="Ada Account")
    mobile_entry = MockConfigEntry(
        domain="mobile_app", data={"user_id": user.id, "device_id": "ada-iphone"}
    )
    mobile_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "notify", "mobile_app", "ada-iphone", config_entry=mobile_entry
    )

    member = {"ha_user_id": user.id, "notify_entity_id": None}
    targets = await async_resolve_member_notify_targets(hass, member)
    assert targets == [entry.entity_id]


async def test_auto_resolution_finds_a_new_device_registered_later(hass: HomeAssistant):
    """The "update if they change phones" requirement: nothing about the resolved target is
    stored - a second mobile_app entry appearing for the same user (e.g. a new phone) is
    found on the very next call, no config change needed."""
    user = await hass.auth.async_create_user(name="Ada Account")
    registry = er.async_get(hass)

    old_entry = MockConfigEntry(
        domain="mobile_app", data={"user_id": user.id, "device_id": "ada-old-phone"}
    )
    old_entry.add_to_hass(hass)
    old_registry_entry = registry.async_get_or_create(
        "notify", "mobile_app", "ada-old-phone", config_entry=old_entry
    )

    member = {"ha_user_id": user.id, "notify_entity_id": None}
    assert await async_resolve_member_notify_targets(hass, member) == [
        old_registry_entry.entity_id
    ]

    new_entry = MockConfigEntry(
        domain="mobile_app", data={"user_id": user.id, "device_id": "ada-new-phone"}
    )
    new_entry.add_to_hass(hass)
    new_registry_entry = registry.async_get_or_create(
        "notify", "mobile_app", "ada-new-phone", config_entry=new_entry
    )

    targets = await async_resolve_member_notify_targets(hass, member)
    assert set(targets) == {old_registry_entry.entity_id, new_registry_entry.entity_id}


async def test_no_target_when_unlinked_and_unmapped(hass: HomeAssistant):
    member = {"ha_user_id": None, "notify_entity_id": None}
    assert await async_resolve_member_notify_targets(hass, member) == []


async def test_no_target_when_linked_but_no_mobile_app_device(hass: HomeAssistant):
    user = await hass.auth.async_create_user(name="Ada Account")
    member = {"ha_user_id": user.id, "notify_entity_id": None}
    assert await async_resolve_member_notify_targets(hass, member) == []
