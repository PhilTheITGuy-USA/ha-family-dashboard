"""Tests for the Lists module - Family Dashboard's own `todo` platform. Covers: entities
are created only for roster members who opted into "lists" with their selected presets
(and nobody else), a member with "lists" enabled but no presets picked gets zero list
entities, items can be added/renamed-and-completed/removed via the real `todo.*` services,
and sibling isolation - one roster member's list is a wholly separate entity from another's,
even for the same preset.
"""
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_dashboard.const import DOMAIN


async def _setup_entry(hass: HomeAssistant, roster: list[dict]) -> MockConfigEntry:
    entry = MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Family Dashboard",
        data={"roster": roster},
        source="user",
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _member(name, member_id, features, list_presets=None, color="Blue"):
    return {
        "member_id": member_id,
        "name": name,
        "color": color,
        "features": features,
        "ha_user_id": None,
        "list_presets": list_presets or [],
    }


async def test_entities_created_only_for_opted_in_members_and_presets(hass: HomeAssistant):
    roster = [
        _member("Ada", "ada", ["lists"], ["shopping", "to_do"]),
        _member("Grace", "grace", ["lists"], ["shopping"]),
        # Chores only - no lists entities at all for Bob.
        _member("Bob", "bob", ["chores"]),
        # Opted into lists but picked no presets - zero list entities, no crash.
        _member("Cy", "cy", ["lists"], []),
    ]
    await _setup_entry(hass, roster)

    assert hass.states.get("todo.family_dashboard_ada_shopping") is not None
    assert hass.states.get("todo.family_dashboard_ada_to_do") is not None
    assert hass.states.get("todo.family_dashboard_grace_shopping") is not None
    assert hass.states.get("todo.family_dashboard_bob_shopping") is None
    assert hass.states.get("todo.family_dashboard_cy_shopping") is None


async def test_sibling_lists_are_isolated(hass: HomeAssistant):
    roster = [
        _member("Ada", "ada", ["lists"], ["shopping"]),
        _member("Grace", "grace", ["lists"], ["shopping"]),
    ]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": "todo.family_dashboard_ada_shopping", "item": "Milk"},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Ada's shopping list has one item (state = count of NEEDS_ACTION items).
    assert hass.states.get("todo.family_dashboard_ada_shopping").state == "1"
    # Grace's separate "Shopping" list is untouched.
    assert hass.states.get("todo.family_dashboard_grace_shopping").state == "0"


async def test_add_update_remove_item(hass: HomeAssistant):
    roster = [_member("Ada", "ada", ["lists"], ["to_do"])]
    await _setup_entry(hass, roster)
    entity_id = "todo.family_dashboard_ada_to_do"

    await hass.services.async_call(
        "todo", "add_item", {"entity_id": entity_id, "item": "Homework"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "1"

    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": entity_id, "item": "Homework", "rename": "Math homework", "status": "completed"},
        blocking=True,
    )
    await hass.async_block_till_done()
    # Completed items don't count toward the NEEDS_ACTION state.
    assert hass.states.get(entity_id).state == "0"

    await hass.services.async_call(
        "todo",
        "remove_item",
        {"entity_id": entity_id, "item": "Math homework"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "0"
