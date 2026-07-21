"""Tests for optional day-of-week chore scheduling. Covers: the household day-of-week sensor
reflects today and registers a midnight-rollover listener; `_member_task_cards` gates a
scheduled chore's tile behind one `type: conditional` per configured day while leaving an
unscheduled chore's tile unconditional (backward-compatibility regression check); two
independent chore records with the same name, different assignees, and disjoint schedules
stay fully isolated from each other; the Manage Chores & Rewards row's Schedule pill and the
`set_chore_schedule_days` entity service (including its validation error path).
"""
from __future__ import annotations

from unittest.mock import patch

import freezegun
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_dashboard.const import DOMAIN
from custom_components.family_dashboard.dashboard.registry import async_build_dashboard_config
from custom_components.family_dashboard.modules.chores import crud
from custom_components.family_dashboard.modules.chores.dashboard import _member_task_cards


def _member(name, member_id, features=("chores",)):
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


def _views_by_path(config):
    return {v["path"]: v for v in config["strategy"]["views"]}


def _view_cards(view):
    return view["sections"][0]["cards"]


async def test_day_of_week_sensor_matches_today(hass: HomeAssistant):
    with freezegun.freeze_time("2026-07-20 12:00:00"):  # a Monday
        roster = [_member("Ada", "ada")]
        await _setup_entry(hass, roster)
        assert hass.states.get("sensor.family_dashboard_day_of_week").state == "monday"


async def test_day_of_week_sensor_registers_midnight_listener(hass: HomeAssistant):
    with patch(
        "custom_components.family_dashboard.modules.chores.sensor.async_track_time_change"
    ) as mock_track:
        roster = [_member("Ada", "ada")]
        await _setup_entry(hass, roster)

    assert mock_track.called
    _, kwargs = mock_track.call_args
    assert kwargs["hour"] == 0
    assert kwargs["minute"] == 0


async def test_unscheduled_chore_tile_is_unconditional(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    chores = [{"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}]
    entry = await _setup_entry(hass, roster, chores=chores)

    cards = await _member_task_cards(hass, entry, roster[0])
    trash_card = next(c for c in cards if c.get("entity") == "sensor.family_dashboard_trash")
    assert trash_card["type"] == "tile"


async def test_scheduled_chore_tile_is_conditional_per_day(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    chores = [
        {
            "chore_id": "trash",
            "name": "Trash",
            "points": 10,
            "frequency": "daily",
            "assigned_to": "ada",
            "schedule_days": ["monday", "wednesday", "friday"],
        }
    ]
    entry = await _setup_entry(hass, roster, chores=chores)

    cards = await _member_task_cards(hass, entry, roster[0])
    conditional_cards = [
        c
        for c in cards
        if c.get("type") == "conditional" and c["card"].get("entity") == "sensor.family_dashboard_trash"
    ]
    assert len(conditional_cards) == 3
    days = {c["conditions"][0]["state"] for c in conditional_cards}
    assert days == {"monday", "wednesday", "friday"}
    for c in conditional_cards:
        assert c["conditions"][0]["entity"] == "sensor.family_dashboard_day_of_week"

    # Not also rendered unconditionally.
    assert not any(
        c.get("type") == "tile" and c.get("entity") == "sensor.family_dashboard_trash" for c in cards
    )


async def test_same_named_chore_split_across_two_kids_stays_isolated(hass: HomeAssistant):
    roster = [_member("Tristan", "tristan"), _member("Harlee", "harlee")]
    chores = [
        {
            "chore_id": "dishes",
            "name": "Dishes",
            "points": 5,
            "frequency": "daily",
            "assigned_to": "tristan",
            "schedule_days": ["monday", "wednesday", "friday"],
        },
        {
            "chore_id": "dishes_2",
            "name": "Dishes",
            "points": 5,
            "frequency": "daily",
            "assigned_to": "harlee",
            "schedule_days": ["tuesday", "thursday", "saturday"],
        },
    ]
    entry = await _setup_entry(hass, roster, chores=chores)

    tristan_cards = await _member_task_cards(hass, entry, roster[0])
    harlee_cards = await _member_task_cards(hass, entry, roster[1])

    tristan_conditionals = [c for c in tristan_cards if c.get("type") == "conditional"]
    harlee_conditionals = [c for c in harlee_cards if c.get("type") == "conditional"]

    assert {c["card"]["entity"] for c in tristan_conditionals} == {"sensor.family_dashboard_dishes"}
    assert {c["conditions"][0]["state"] for c in tristan_conditionals} == {"monday", "wednesday", "friday"}

    assert {c["card"]["entity"] for c in harlee_conditionals} == {"sensor.family_dashboard_dishes_2"}
    assert {c["conditions"][0]["state"] for c in harlee_conditionals} == {"tuesday", "thursday", "saturday"}

    # Claiming/approving one is fully independent of the other.
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.family_dashboard_dishes_claim"}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.family_dashboard_dishes_approve"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.family_dashboard_tristan_points").state == "5"
    assert hass.states.get("sensor.family_dashboard_harlee_points").state == "0"
    assert hass.states.get("sensor.family_dashboard_dishes_2").state == "idle"


async def test_chore_row_schedule_pill_shows_every_day_or_days(hass: HomeAssistant):
    await hass.auth.async_create_user(name="Kiosk Account")
    roster = [_member("Ada", "ada")]
    chores = [
        {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"},
        {
            "chore_id": "dishes",
            "name": "Dishes",
            "points": 5,
            "frequency": "daily",
            "assigned_to": "ada",
            "schedule_days": ["monday", "wednesday", "friday"],
        },
    ]
    entry = await _setup_entry(hass, roster, chores=chores)

    config = await async_build_dashboard_config(hass, entry)
    kiosk_chores = _view_cards(_views_by_path(config)["chores-kiosk"])
    assert any("Schedule: Every day" in str(c) for c in kiosk_chores)
    assert any("Schedule: Mon, Wed, Fri" in str(c) for c in kiosk_chores)


async def test_set_schedule_days_valid_input_persists_and_clears_scratch(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    chores = [{"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}]
    entry = await _setup_entry(hass, roster, chores=chores)

    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.family_dashboard_chore_schedule_scratch", "value": "Mon, Wed, Fri"},
        blocking=True,
    )
    await hass.services.async_call(
        "family_dashboard",
        "set_chore_schedule_days",
        {"entity_id": "sensor.family_dashboard_trash"},
        blocking=True,
    )
    await hass.async_block_till_done()

    updated = next(c for c in entry.data["chores"] if c["chore_id"] == "trash")
    assert updated["schedule_days"] == ["monday", "wednesday", "friday"]
    assert hass.states.get("text.family_dashboard_chore_schedule_scratch").state == ""


async def test_set_schedule_days_invalid_input_raises_and_does_not_persist(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    chores = [{"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}]
    entry = await _setup_entry(hass, roster, chores=chores)

    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.family_dashboard_chore_schedule_scratch", "value": "Funday"},
        blocking=True,
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "family_dashboard",
            "set_chore_schedule_days",
            {"entity_id": "sensor.family_dashboard_trash"},
            blocking=True,
        )
    await hass.async_block_till_done()

    updated = next(c for c in entry.data["chores"] if c["chore_id"] == "trash")
    assert "schedule_days" not in updated


async def test_add_chore_with_schedule_scratch_field(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    entry = await _setup_entry(hass, roster)

    await hass.services.async_call(
        "text", "set_value", {"entity_id": "text.family_dashboard_new_chore_name", "value": "Dishes"}, blocking=True
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.family_dashboard_new_chore_assigned_to", "option": "Ada"},
        blocking=True,
    )
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.family_dashboard_new_chore_schedule", "value": "Tue, Thu, Sat"},
        blocking=True,
    )
    await hass.services.async_call(
        "family_dashboard", "add_chore", {"entity_id": "text.family_dashboard_new_chore_name"}, blocking=True
    )
    await hass.async_block_till_done()

    added = next(c for c in entry.data["chores"] if c["name"] == "Dishes")
    assert added["schedule_days"] == ["tuesday", "thursday", "saturday"]
    assert hass.states.get("text.family_dashboard_new_chore_schedule").state == ""


async def test_add_chore_with_blank_schedule_means_every_day(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    entry = await _setup_entry(hass, roster)

    await hass.services.async_call(
        "text", "set_value", {"entity_id": "text.family_dashboard_new_chore_name", "value": "Trash"}, blocking=True
    )
    await hass.services.async_call(
        "family_dashboard", "add_chore", {"entity_id": "text.family_dashboard_new_chore_name"}, blocking=True
    )
    await hass.async_block_till_done()

    added = next(c for c in entry.data["chores"] if c["name"] == "Trash")
    assert "schedule_days" not in added
