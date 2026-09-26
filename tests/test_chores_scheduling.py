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


def _visibility_conditional(cards, sensor):
    matches = [
        c
        for c in cards
        if c.get("type") == "conditional" and c["card"].get("entity") == sensor
    ]
    assert len(matches) == 1, matches
    return matches[0]


def _shows_when_due_or_claimed(conditional, sensor):
    # Keyed on the Due Today binary sensor's plain state, not the `due_today` attribute:
    # attribute matching in dashboard conditions only arrived in HA 2026.5.
    due = sensor.replace("sensor.", "binary_sensor.", 1) + "_due_today"
    return conditional["conditions"] == [
        {
            "condition": "or",
            "conditions": [
                {"condition": "state", "entity": due, "state": "on"},
                {"condition": "state", "entity": sensor, "state": "claimed"},
            ],
        }
    ]


async def test_every_chore_tile_shows_when_due_or_claimed(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    chores = [
        {"chore_id": "trash", "name": "Trash", "points": 10, "repeat": "days_of_week", "assigned_to": "ada"},
        {
            "chore_id": "dishes",
            "name": "Dishes",
            "points": 5,
            "repeat": "days_of_week",
            "schedule_days": ["monday", "wednesday", "friday"],
            "assigned_to": "ada",
        },
        {"chore_id": "bins", "name": "Bins", "points": 5, "repeat": "monthly", "month_days": [1], "assigned_to": "ada"},
    ]
    entry = await _setup_entry(hass, roster, chores=chores)

    cards = await _member_task_cards(hass, entry, roster[0])

    for sensor in ("sensor.family_dashboard_trash", "sensor.family_dashboard_dishes", "sensor.family_dashboard_bins"):
        assert _shows_when_due_or_claimed(_visibility_conditional(cards, sensor), sensor)
        # Never also rendered unconditionally.
        assert not any(c.get("type") == "tile" and c.get("entity") == sensor for c in cards)


@freezegun.freeze_time("2026-09-21 18:00:00")  # a Monday, so Tristan's chore is due
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
    assert {c["card"]["entity"] for c in harlee_conditionals} == {"sensor.family_dashboard_dishes_2"}
    assert hass.states.get("sensor.family_dashboard_dishes").attributes["due_today"] is True
    assert hass.states.get("sensor.family_dashboard_dishes_2").attributes["due_today"] is False

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


async def _kiosk_chores(hass, entry):
    config = await async_build_dashboard_config(hass, entry)
    return _view_cards(_views_by_path(config)["chores-kiosk"])


def _find(obj, predicate):
    """Every dict nested anywhere in `obj` that satisfies `predicate`."""
    found = []
    if isinstance(obj, dict):
        if predicate(obj):
            found.append(obj)
        for value in obj.values():
            found.extend(_find(value, predicate))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_find(value, predicate))
    return found


_SCHEDULED_CHORES = [
    {"chore_id": "trash", "name": "Trash", "points": 10, "repeat": "days_of_week", "assigned_to": "ada"},
    {
        "chore_id": "dishes",
        "name": "Dishes",
        "points": 5,
        "repeat": "days_of_week",
        "schedule_days": ["monday", "wednesday", "friday"],
        "assigned_to": "ada",
    },
    {"chore_id": "bins", "name": "Bins", "points": 3, "repeat": "monthly", "month_days": [1, 15], "assigned_to": "ada"},
    {"chore_id": "garage", "name": "Garage", "points": 20, "repeat": "one_time", "assigned_to": "ada"},
]


async def test_chore_row_schedule_pill_describes_schedule(hass: HomeAssistant):
    await hass.auth.async_create_user(name="Kiosk Account")
    entry = await _setup_entry(hass, [_member("Ada", "ada")], chores=_SCHEDULED_CHORES)

    text = str(await _kiosk_chores(hass, entry))

    for label in ("Every day", "Mon, Wed, Fri", "Monthly: 1, 15", "One-time"):
        assert f"Schedule: {label}" in text
    assert "Frequency" not in text


async def test_edit_schedule_popup_prefills_and_has_pickers(hass: HomeAssistant):
    await hass.auth.async_create_user(name="Kiosk Account")
    entry = await _setup_entry(hass, [_member("Ada", "ada")], chores=_SCHEDULED_CHORES)

    cards = await _kiosk_chores(hass, entry)
    popup = _find(cards, lambda c: c.get("hash") == "#schedule-bins")[0]

    assert popup["open_action"] == {
        "action": "perform-action",
        "perform_action": "family_dashboard.load_chore_schedule",
        "target": {"entity_id": "sensor.family_dashboard_bins"},
    }
    assert _find(popup, lambda c: c.get("entity") == "select.family_dashboard_chore_schedule_repeat")

    weekday_pills = _find(popup, lambda c: c.get("tap_action", {}).get("data", {}).get("value") in {"mon", "sun"})
    month_pills = _find(popup, lambda c: c.get("tap_action", {}).get("data", {}).get("value") in {str(d) for d in range(1, 32)})
    assert len(weekday_pills) == 2
    assert len(month_pills) == 31
    for pill in weekday_pills + month_pills:
        assert pill["tap_action"]["perform_action"] == "family_dashboard.toggle_schedule_day"
        assert pill["tap_action"]["target"] == {"entity_id": "text.family_dashboard_chore_schedule_scratch"}

    # Each picker only shows for its own Repeat choice.
    shown_for = {
        c["conditions"][0]["state"]
        for c in _find(popup, lambda c: c.get("type") == "conditional")
        if c["conditions"][0].get("entity") == "select.family_dashboard_chore_schedule_repeat"
    }
    assert shown_for == {"Days of week", "Monthly"}


async def test_add_chore_popup_has_repeat_and_pickers(hass: HomeAssistant):
    await hass.auth.async_create_user(name="Kiosk Account")
    entry = await _setup_entry(hass, [_member("Ada", "ada")], chores=_SCHEDULED_CHORES)

    cards = await _kiosk_chores(hass, entry)
    popup = _find(cards, lambda c: c.get("hash") == "#addchore")[0]

    assert _find(popup, lambda c: c.get("entity") == "select.family_dashboard_new_chore_repeat")
    pills = _find(popup, lambda c: c.get("tap_action", {}).get("perform_action") == "family_dashboard.toggle_schedule_day")
    assert len(pills) == 7 + 31
    assert {p["tap_action"]["target"]["entity_id"] for p in pills} == {"text.family_dashboard_new_chore_schedule"}
    assert _find(popup, lambda c: c.get("tap_action", {}).get("perform_action") == "family_dashboard.add_chore")


async def test_parent_review_has_reset_for_chores_and_rewards(hass: HomeAssistant):
    await hass.auth.async_create_user(name="Kiosk Account")
    entry = await _setup_entry(
        hass,
        [_member("Ada", "ada")],
        chores=_SCHEDULED_CHORES[:1],
        rewards=[{"reward_id": "movie", "name": "Movie", "cost": 5, "assigned_to": "ada"}],
    )

    cards = await _kiosk_chores(hass, entry)
    resets = _find(cards, lambda c: c.get("tap_action", {}).get("perform_action") == "family_dashboard.reset_claim")

    assert {r["tap_action"]["target"]["entity_id"] for r in resets} == {
        "sensor.family_dashboard_trash",
        "sensor.family_dashboard_movie",
    }


NEW_REPEAT = "select.family_dashboard_new_chore_repeat"
NEW_DAYS = "text.family_dashboard_new_chore_schedule"
EDIT_REPEAT = "select.family_dashboard_chore_schedule_repeat"
EDIT_DAYS = "text.family_dashboard_chore_schedule_scratch"


async def _select(hass, entity_id, option):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, "option": option}, blocking=True
    )
    await hass.async_block_till_done()


async def _toggle(hass, entity_id, *values):
    for value in values:
        await hass.services.async_call(
            DOMAIN, "toggle_schedule_day", {"entity_id": entity_id, "value": value}, blocking=True
        )
    await hass.async_block_till_done()


async def _save_schedule(hass, sensor="sensor.family_dashboard_trash"):
    await hass.services.async_call(
        DOMAIN, "set_chore_schedule_days", {"entity_id": sensor}, blocking=True
    )
    await hass.async_block_till_done()


async def _add_chore(hass):
    await hass.services.async_call(
        DOMAIN, "add_chore", {"entity_id": "text.family_dashboard_new_chore_name"}, blocking=True
    )
    await hass.async_block_till_done()


def _trash(entry):
    return next(c for c in entry.data["chores"] if c["chore_id"] == "trash")


_TRASH = {"chore_id": "trash", "name": "Trash", "points": 10, "assigned_to": "ada"}


async def test_toggle_schedule_day_adds_and_removes(hass: HomeAssistant):
    await _setup_entry(hass, [_member("Ada", "ada")])

    await _toggle(hass, NEW_DAYS, "thu", "mon")
    assert hass.states.get(NEW_DAYS).state == "mon,thu"

    await _toggle(hass, NEW_DAYS, "mon")
    assert hass.states.get(NEW_DAYS).state == "thu"


async def test_toggle_rejects_token_of_other_kind(hass: HomeAssistant):
    await _setup_entry(hass, [_member("Ada", "ada")])
    await _select(hass, NEW_REPEAT, "Monthly")

    with pytest.raises(HomeAssistantError):
        await _toggle(hass, NEW_DAYS, "mon")
    assert hass.states.get(NEW_DAYS).state == ""


async def test_repeat_change_clears_days(hass: HomeAssistant):
    await _setup_entry(hass, [_member("Ada", "ada")], chores=[{**_TRASH, "repeat": "days_of_week"}])

    await _toggle(hass, NEW_DAYS, "mon", "thu")
    await _select(hass, NEW_REPEAT, "Monthly")
    assert hass.states.get(NEW_DAYS).state == ""

    await _toggle(hass, EDIT_DAYS, "sat")
    await _select(hass, EDIT_REPEAT, "Monthly")
    assert hass.states.get(EDIT_DAYS).state == ""


async def test_load_chore_schedule_fills_scratch(hass: HomeAssistant):
    chore = {**_TRASH, "repeat": "monthly", "month_days": [1, 15]}
    await _setup_entry(hass, [_member("Ada", "ada")], chores=[chore])

    await hass.services.async_call(
        DOMAIN, "load_chore_schedule", {"entity_id": "sensor.family_dashboard_trash"}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get(EDIT_REPEAT).state == "Monthly"
    assert hass.states.get(EDIT_DAYS).state == "1,15"


async def test_set_schedule_saves_days_of_week_and_clears_scratch(hass: HomeAssistant):
    entry = await _setup_entry(hass, [_member("Ada", "ada")], chores=[{**_TRASH, "repeat": "days_of_week"}])
    await _select(hass, EDIT_REPEAT, "Days of week")
    await _toggle(hass, EDIT_DAYS, "fri", "mon", "wed")

    await _save_schedule(hass)

    assert _trash(entry)["repeat"] == "days_of_week"
    assert _trash(entry)["schedule_days"] == ["monday", "wednesday", "friday"]
    assert hass.states.get(EDIT_DAYS).state == ""


async def test_set_schedule_saves_monthly(hass: HomeAssistant):
    chore = {**_TRASH, "repeat": "days_of_week", "schedule_days": ["monday"]}
    entry = await _setup_entry(hass, [_member("Ada", "ada")], chores=[chore])
    await _select(hass, EDIT_REPEAT, "Monthly")
    await _toggle(hass, EDIT_DAYS, "15", "1")

    await _save_schedule(hass)

    assert _trash(entry)["repeat"] == "monthly"
    assert _trash(entry)["month_days"] == [1, 15]
    assert "schedule_days" not in _trash(entry)


async def test_set_schedule_monthly_without_days_raises(hass: HomeAssistant):
    entry = await _setup_entry(hass, [_member("Ada", "ada")], chores=[{**_TRASH, "repeat": "days_of_week"}])
    await _select(hass, EDIT_REPEAT, "Monthly")

    with pytest.raises(HomeAssistantError, match="at least one day"):
        await _save_schedule(hass)

    assert _trash(entry) == {**_TRASH, "repeat": "days_of_week"}


async def test_add_chore_from_scratch_uses_repeat_and_days(hass: HomeAssistant):
    entry = await _setup_entry(hass, [_member("Ada", "ada")])
    await hass.services.async_call(
        "text", "set_value", {"entity_id": "text.family_dashboard_new_chore_name", "value": "Bins"}, blocking=True
    )
    await _select(hass, "select.family_dashboard_new_chore_assigned_to", "Ada")
    await _select(hass, NEW_REPEAT, "Monthly")
    await _toggle(hass, NEW_DAYS, "1")

    await _add_chore(hass)

    added = next(c for c in entry.data["chores"] if c["name"] == "Bins")
    assert added["repeat"] == "monthly"
    assert added["month_days"] == [1]
    assert hass.states.get(NEW_DAYS).state == ""
    assert hass.states.get(NEW_REPEAT).state == "Days of week"


async def test_add_chore_days_of_week_from_pills(hass: HomeAssistant):
    entry = await _setup_entry(hass, [_member("Ada", "ada")])
    await hass.services.async_call(
        "text", "set_value", {"entity_id": "text.family_dashboard_new_chore_name", "value": "Dishes"}, blocking=True
    )
    await _toggle(hass, NEW_DAYS, "tue", "thu", "sat")

    await _add_chore(hass)

    added = next(c for c in entry.data["chores"] if c["name"] == "Dishes")
    assert added["schedule_days"] == ["tuesday", "thursday", "saturday"]


async def test_add_chore_monthly_without_days_raises(hass: HomeAssistant):
    entry = await _setup_entry(hass, [_member("Ada", "ada")])
    await hass.services.async_call(
        "text", "set_value", {"entity_id": "text.family_dashboard_new_chore_name", "value": "Bins"}, blocking=True
    )
    await _select(hass, NEW_REPEAT, "Monthly")

    with pytest.raises(HomeAssistantError, match="at least one day"):
        await _add_chore(hass)
    assert not any(c["name"] == "Bins" for c in entry.data["chores"])


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


async def test_one_time_chore_tile_hides_once_approved(hass: HomeAssistant):
    """A finished one-time chore drops off the kid's view; recurring chores don't need this
    (they come back on their next due day)."""
    chores = [
        {"chore_id": "garage", "name": "Garage", "points": 20, "repeat": "one_time", "assigned_to": "ada"},
        {"chore_id": "trash", "name": "Trash", "points": 10, "repeat": "days_of_week", "assigned_to": "ada"},
    ]
    entry = await _setup_entry(hass, [_member("Ada", "ada")], chores=chores)

    cards = await _member_task_cards(hass, entry, _member("Ada", "ada"))

    garage = _visibility_conditional(cards, "sensor.family_dashboard_garage")
    assert {
        "condition": "state",
        "entity": "sensor.family_dashboard_garage",
        "state_not": "approved",
    } in garage["conditions"]
    trash = _visibility_conditional(cards, "sensor.family_dashboard_trash")
    assert len(trash["conditions"]) == 1
