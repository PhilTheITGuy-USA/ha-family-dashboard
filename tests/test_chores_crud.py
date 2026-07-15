"""Tests for `modules/chores/crud.py` - Add/Modify/Delete for Chores & Rewards. Covers:
adding generates a unique id and creates real entities; updating a single field persists
through reload; deleting GENUINELY removes entities (registry entry gone entirely, not just
`hidden_by`) and the item's own data, while a sibling chore/reward is completely unaffected.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_dashboard.const import DOMAIN
from custom_components.family_dashboard.modules.chores import crud


def _member(member_id, name, features=("chores",)):
    return {
        "member_id": member_id,
        "name": name,
        "color": "Blue",
        "features": list(features),
        "ha_user_id": None,
        "calendar_entity_id": None,
        "notify_entity_id": None,
        "list_presets": [],
    }


async def _setup_entry(hass: HomeAssistant, roster, chores=None, rewards=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Family Dashboard",
        data={"roster": roster, "chores": chores or [], "rewards": rewards or []},
        source="user",
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_add_chore_generates_unique_id_and_creates_entities(hass: HomeAssistant):
    roster = [_member("ada", "Ada")]
    entry = await _setup_entry(hass, roster)

    chore_id = await crud.async_add_chore(
        hass, entry, name="Trash", points=10, frequency="daily", assigned_to="ada"
    )
    await hass.async_block_till_done()

    assert chore_id == "trash"
    assert entry.data["chores"] == [
        {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}
    ]
    assert hass.states.get("sensor.family_dashboard_trash") is not None
    assert hass.states.get("text.family_dashboard_trash_name").state == "Trash"
    assert hass.states.get("number.family_dashboard_trash_points").state == "10"
    assert hass.states.get("select.family_dashboard_trash_frequency").state == "Daily"
    assert hass.states.get("select.family_dashboard_trash_assigned_to").state == "Ada"


async def test_add_chore_dedupes_id_against_existing(hass: HomeAssistant):
    roster = [_member("ada", "Ada")]
    chores = [{"chore_id": "trash", "name": "Trash", "points": 5, "frequency": "daily", "assigned_to": "ada"}]
    entry = await _setup_entry(hass, roster, chores=chores)

    chore_id = await crud.async_add_chore(
        hass, entry, name="Trash", points=8, frequency="weekly", assigned_to="ada"
    )
    await hass.async_block_till_done()

    assert chore_id == "trash_2"
    assert {c["chore_id"] for c in entry.data["chores"]} == {"trash", "trash_2"}


async def test_add_reward_creates_entities(hass: HomeAssistant):
    roster = [_member("ada", "Ada")]
    entry = await _setup_entry(hass, roster)

    reward_id = await crud.async_add_reward(hass, entry, name="Movie Night", cost=30, assigned_to="ada")
    await hass.async_block_till_done()

    assert reward_id == "movie_night"
    assert hass.states.get("sensor.family_dashboard_movie_night") is not None
    assert hass.states.get("number.family_dashboard_movie_night_cost").state == "30"


async def test_update_chore_field_persists_single_field(hass: HomeAssistant):
    roster = [_member("ada", "Ada")]
    chores = [{"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}]
    entry = await _setup_entry(hass, roster, chores=chores)

    await crud.async_update_chore_field(hass, entry, "trash", points=15)
    await hass.async_block_till_done()

    updated = next(c for c in entry.data["chores"] if c["chore_id"] == "trash")
    assert updated == {"chore_id": "trash", "name": "Trash", "points": 15, "frequency": "daily", "assigned_to": "ada"}
    assert hass.states.get("number.family_dashboard_trash_points").state == "15"


async def test_delete_chore_genuinely_removes_entities_not_hides(hass: HomeAssistant):
    roster = [_member("ada", "Ada")]
    chores = [{"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}]
    entry = await _setup_entry(hass, roster, chores=chores)

    registry = er.async_get(hass)
    sensor_entity_id = "sensor.family_dashboard_trash"
    name_entity_id = "text.family_dashboard_trash_name"
    deny_reason_entity_id = "text.family_dashboard_trash_deny_reason"
    assert registry.async_get(sensor_entity_id) is not None
    assert registry.async_get(name_entity_id) is not None
    assert registry.async_get(deny_reason_entity_id) is not None

    await crud.async_delete_chore(hass, entry, "trash")
    await hass.async_block_till_done()

    # Genuinely gone from the registry - not hidden_by, actually removed.
    assert registry.async_get(sensor_entity_id) is None
    assert registry.async_get(name_entity_id) is None
    assert registry.async_get(deny_reason_entity_id) is None
    assert hass.states.get(sensor_entity_id) is None

    # The item itself is gone from entry.data too.
    assert entry.data["chores"] == []


async def test_delete_chore_does_not_affect_sibling_chore_or_reward(hass: HomeAssistant):
    roster = [_member("ada", "Ada"), _member("grace", "Grace")]
    chores = [
        {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"},
        {"chore_id": "dishes", "name": "Dishes", "points": 5, "frequency": "daily", "assigned_to": "grace"},
    ]
    rewards = [{"reward_id": "movie_night", "name": "Movie Night", "cost": 30, "assigned_to": "ada"}]
    entry = await _setup_entry(hass, roster, chores=chores, rewards=rewards)

    await crud.async_delete_chore(hass, entry, "trash")
    await hass.async_block_till_done()

    assert hass.states.get("sensor.family_dashboard_dishes") is not None
    assert hass.states.get("sensor.family_dashboard_movie_night") is not None
    assert {c["chore_id"] for c in entry.data["chores"]} == {"dishes"}
    assert entry.data["rewards"][0]["reward_id"] == "movie_night"


async def test_delete_reward_genuinely_removes_entities(hass: HomeAssistant):
    roster = [_member("ada", "Ada")]
    rewards = [{"reward_id": "movie_night", "name": "Movie Night", "cost": 30, "assigned_to": "ada"}]
    entry = await _setup_entry(hass, roster, rewards=rewards)

    registry = er.async_get(hass)
    await crud.async_delete_reward(hass, entry, "movie_night")
    await hass.async_block_till_done()

    assert registry.async_get("sensor.family_dashboard_movie_night") is None
    assert entry.data["rewards"] == []


async def test_create_chore_from_scratch_fields_reads_and_clears(hass: HomeAssistant):
    roster = [_member("ada", "Ada")]
    entry = await _setup_entry(hass, roster)

    await hass.services.async_call(
        "text", "set_value",
        {"entity_id": "text.family_dashboard_new_chore_name", "value": "Trash"},
        blocking=True,
    )
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.family_dashboard_new_chore_points", "value": 20},
        blocking=True,
    )
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.family_dashboard_new_chore_assigned_to", "option": "Ada"},
        blocking=True,
    )

    await hass.services.async_call(
        "family_dashboard", "add_chore",
        {"entity_id": "text.family_dashboard_new_chore_name"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert any(c["name"] == "Trash" and c["points"] == 20 for c in entry.data["chores"])
    # Scratch fields reset after submit.
    assert hass.states.get("text.family_dashboard_new_chore_name").state == ""
    assert hass.states.get("number.family_dashboard_new_chore_points").state == "5"


async def test_create_chore_from_scratch_fields_blank_name_is_noop(hass: HomeAssistant):
    roster = [_member("ada", "Ada")]
    entry = await _setup_entry(hass, roster)

    await hass.services.async_call(
        "family_dashboard", "add_chore",
        {"entity_id": "text.family_dashboard_new_chore_name"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert entry.data["chores"] == []


async def test_add_chore_with_no_assignment(hass: HomeAssistant):
    roster = [_member("ada", "Ada")]
    entry = await _setup_entry(hass, roster)

    chore_id = await crud.async_add_chore(
        hass, entry, name="Water Plants", points=5, frequency="weekly", assigned_to=None
    )
    await hass.async_block_till_done()

    assert entry.data["chores"] == [
        {
            "chore_id": "water_plants",
            "name": "Water Plants",
            "points": 5,
            "frequency": "weekly",
            "assigned_to": None,
        }
    ]
    # Entities still exist (editable/deletable from Settings) even with nobody assigned.
    assert hass.states.get("sensor.family_dashboard_water_plants") is not None
    assert hass.states.get("select.family_dashboard_water_plants_assigned_to").state == "Unassigned"


async def test_create_chore_from_scratch_fields_with_unassigned_option(hass: HomeAssistant):
    roster = [_member("ada", "Ada")]
    entry = await _setup_entry(hass, roster)

    await hass.services.async_call(
        "text", "set_value",
        {"entity_id": "text.family_dashboard_new_chore_name", "value": "Water Plants"},
        blocking=True,
    )
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.family_dashboard_new_chore_assigned_to", "option": "Unassigned"},
        blocking=True,
    )
    await hass.services.async_call(
        "family_dashboard", "add_chore",
        {"entity_id": "text.family_dashboard_new_chore_name"},
        blocking=True,
    )
    await hass.async_block_till_done()

    added = next(c for c in entry.data["chores"] if c["name"] == "Water Plants")
    assert added["assigned_to"] is None


async def test_reassign_existing_chore_to_unassigned_and_back(hass: HomeAssistant):
    roster = [_member("ada", "Ada")]
    chores = [{"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}]
    entry = await _setup_entry(hass, roster, chores=chores)

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.family_dashboard_trash_assigned_to", "option": "Unassigned"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.data["chores"][0]["assigned_to"] is None
    assert hass.states.get("select.family_dashboard_trash_assigned_to").state == "Unassigned"

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.family_dashboard_trash_assigned_to", "option": "Ada"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.data["chores"][0]["assigned_to"] == "ada"
