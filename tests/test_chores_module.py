"""Tests for the Chores & Rewards module. Covers: a chore's full claim -> approve lifecycle
awards points to the right member, a second approve without re-claiming is rejected; deny
requires a reason and logs it to the Logbook; a reward's approve deducts points and rejects
insufficient balance; the adjust_points service applies positive/negative deltas; parent-mode
unlock with correct/incorrect PIN and the lock button; sibling isolation (one member's chore
approval doesn't touch another's points).
"""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.family_dashboard.const import DOMAIN


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


async def _setup_entry(
    hass: HomeAssistant, roster: list[dict], chores=None, rewards=None
) -> MockConfigEntry:
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


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def test_points_sensor_starts_at_zero(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    await _setup_entry(hass, roster)
    assert hass.states.get("sensor.family_dashboard_ada_points").state == "0"


async def test_chore_lifecycle_awards_points_and_rejects_double_approve(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    chores = [
        {
            "chore_id": "trash",
            "name": "Trash",
            "points": 10,
            "frequency": "daily",
            "assigned_to": "ada",
        }
    ]
    await _setup_entry(hass, roster, chores=chores)

    chore_entity = "sensor.family_dashboard_trash"
    points_entity = "sensor.family_dashboard_ada_points"
    assert hass.states.get(chore_entity).state == "idle"

    await _press(hass, "button.family_dashboard_trash_claim")
    assert hass.states.get(chore_entity).state == "claimed"

    await _press(hass, "button.family_dashboard_trash_approve")
    assert hass.states.get(chore_entity).state == "approved"
    assert hass.states.get(points_entity).state == "10"

    # Not claimed anymore ("approved", not "claimed") - a second approve is rejected, no
    # double-award.
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.family_dashboard_trash_approve"},
            blocking=True,
        )
    await hass.async_block_till_done()
    assert hass.states.get(points_entity).state == "10"


async def test_deny_requires_reason_and_logs_to_logbook(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    chores = [
        {"chore_id": "dishes", "name": "Dishes", "points": 5, "frequency": "daily", "assigned_to": "ada"}
    ]
    await _setup_entry(hass, roster, chores=chores)
    logbook_calls = async_mock_service(hass, "logbook", "log")

    await _press(hass, "button.family_dashboard_dishes_claim")
    await hass.services.async_call(
        "family_dashboard",
        "deny_task",
        {"entity_id": "sensor.family_dashboard_dishes", "reason": "Not actually done"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("sensor.family_dashboard_dishes").state == "denied"
    assert hass.states.get("sensor.family_dashboard_ada_points").state == "0"
    assert len(logbook_calls) == 1
    assert "Not actually done" in logbook_calls[0].data["message"]

    # Denying again without re-claiming is rejected.
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "family_dashboard",
            "deny_task",
            {"entity_id": "sensor.family_dashboard_dishes", "reason": "again"},
            blocking=True,
        )


async def test_deny_rejects_blank_reason(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    chores = [
        {"chore_id": "dishes", "name": "Dishes", "points": 5, "frequency": "daily", "assigned_to": "ada"}
    ]
    await _setup_entry(hass, roster, chores=chores)

    await _press(hass, "button.family_dashboard_dishes_claim")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "family_dashboard",
            "deny_task",
            {"entity_id": "sensor.family_dashboard_dishes", "reason": "   "},
            blocking=True,
        )
    # Still claimed - the rejected deny didn't consume the pending review.
    assert hass.states.get("sensor.family_dashboard_dishes").state == "claimed"


async def test_deny_reason_entity_exists_and_clears_on_reclaim(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    chores = [
        {"chore_id": "dishes", "name": "Dishes", "points": 5, "frequency": "daily", "assigned_to": "ada"}
    ]
    await _setup_entry(hass, roster, chores=chores)
    async_mock_service(hass, "logbook", "log")

    reason_entity = "text.family_dashboard_dishes_deny_reason"
    assert hass.states.get(reason_entity).state == ""

    await _press(hass, "button.family_dashboard_dishes_claim")
    await hass.services.async_call(
        "text", "set_value", {"entity_id": reason_entity, "value": "Left dishes in the sink"}, blocking=True
    )
    await hass.services.async_call(
        "family_dashboard",
        "deny_task",
        {"entity_id": "sensor.family_dashboard_dishes", "reason": "Left dishes in the sink"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(reason_entity).state == "Left dishes in the sink"

    # Claiming again starts a fresh review cycle - the stale reason is cleared automatically.
    await _press(hass, "button.family_dashboard_dishes_claim")
    assert hass.states.get(reason_entity).state == ""


async def test_reward_approve_deducts_points_and_rejects_insufficient_balance(
    hass: HomeAssistant,
):
    roster = [_member("Ada", "ada")]
    rewards = [{"reward_id": "movie", "name": "Movie Night", "cost": 20, "assigned_to": "ada"}]
    await _setup_entry(hass, roster, rewards=rewards)

    reward_entity = "sensor.family_dashboard_movie_night"
    points_entity = "sensor.family_dashboard_ada_points"

    # Ada has 0 points - claim then approve should fail (insufficient balance).
    await _press(hass, "button.family_dashboard_movie_night_claim")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.family_dashboard_movie_night_approve"},
            blocking=True,
        )
    await hass.async_block_till_done()
    assert hass.states.get(points_entity).state == "0"

    # Give Ada enough points, then redeem successfully.
    await hass.services.async_call(
        "family_dashboard",
        "adjust_points",
        {"entity_id": points_entity, "delta": 25},
        blocking=True,
    )
    await _press(hass, "button.family_dashboard_movie_night_claim")
    await _press(hass, "button.family_dashboard_movie_night_approve")

    assert hass.states.get(reward_entity).state == "approved"
    assert hass.states.get(points_entity).state == "5"


async def test_parent_review_card_includes_reason_tile_and_templated_deny(hass: HomeAssistant):
    from custom_components.family_dashboard.modules.chores.dashboard import async_parent_review_card

    roster = [_member("Ada", "ada")]
    chores = [
        {"chore_id": "dishes", "name": "Dishes", "points": 5, "frequency": "daily", "assigned_to": "ada"}
    ]
    entry = await _setup_entry(hass, roster, chores=chores)
    await _press(hass, "button.family_dashboard_dishes_claim")

    card = await async_parent_review_card(hass, entry, roster)
    row = card["card"]["cards"][-1]["card"]["cards"]
    deny_card = next(c for c in row if c.get("name") == "Deny")
    reason_card = next(c for c in row if c.get("name") == "Reason")

    assert reason_card["entity"] == "text.family_dashboard_dishes_deny_reason"
    assert deny_card["type"] == "custom:button-card"
    assert "text.family_dashboard_dishes_deny_reason" in deny_card["tap_action"]["data"]["reason"]


async def test_adjust_points_positive_and_negative(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    await _setup_entry(hass, roster)
    points_entity = "sensor.family_dashboard_ada_points"

    await hass.services.async_call(
        "family_dashboard", "adjust_points", {"entity_id": points_entity, "delta": 5},
        blocking=True,
    )
    assert hass.states.get(points_entity).state == "5"

    await hass.services.async_call(
        "family_dashboard", "adjust_points", {"entity_id": points_entity, "delta": -2},
        blocking=True,
    )
    assert hass.states.get(points_entity).state == "3"


async def test_parent_mode_unlock_and_lock(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    await _setup_entry(hass, roster)

    parent_mode = "binary_sensor.family_dashboard_parent_mode"
    assert hass.states.get(parent_mode).state == "off"

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "family_dashboard",
            "unlock_parent_mode",
            {"entity_id": parent_mode, "pin": "0000"},
            blocking=True,
        )
    assert hass.states.get(parent_mode).state == "off"

    await hass.services.async_call(
        "family_dashboard",
        "unlock_parent_mode",
        {"entity_id": parent_mode, "pin": "1234"},
        blocking=True,
    )
    assert hass.states.get(parent_mode).state == "on"

    await _press(hass, "button.family_dashboard_lock_parent_mode")
    assert hass.states.get(parent_mode).state == "off"


async def _append_digit(hass: HomeAssistant, digit: str) -> None:
    await hass.services.async_call(
        "family_dashboard",
        "append_pin_digit",
        {"entity_id": "text.family_dashboard_pin_entry", "digit": digit},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_pin_entry_numpad_accumulates_and_unlocks_on_correct_pin(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    await _setup_entry(hass, roster)

    pin_entry = "text.family_dashboard_pin_entry"
    parent_mode = "binary_sensor.family_dashboard_parent_mode"
    assert hass.states.get(pin_entry).state == ""

    await _append_digit(hass, "1")
    assert hass.states.get(pin_entry).state == "1"
    await _append_digit(hass, "2")
    await _append_digit(hass, "3")
    assert hass.states.get(pin_entry).state == "123"

    # 4th digit completes the default "1234" PIN - auto-validates, unlocks, clears buffer.
    await _append_digit(hass, "4")
    assert hass.states.get(pin_entry).state == ""
    assert hass.states.get(parent_mode).state == "on"


async def test_pin_entry_numpad_clears_buffer_and_raises_on_wrong_pin(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    await _setup_entry(hass, roster)

    pin_entry = "text.family_dashboard_pin_entry"
    parent_mode = "binary_sensor.family_dashboard_parent_mode"

    for digit in "0000"[:-1]:
        await _append_digit(hass, digit)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "family_dashboard",
            "append_pin_digit",
            {"entity_id": pin_entry, "digit": "0"},
            blocking=True,
        )
    await hass.async_block_till_done()

    assert hass.states.get(pin_entry).state == ""
    assert hass.states.get(parent_mode).state == "off"


async def _append_raw(hass: HomeAssistant, digit: str) -> None:
    await hass.services.async_call(
        "family_dashboard",
        "append_pin_digit_raw",
        {"entity_id": "text.family_dashboard_pin_entry", "digit": digit},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_pin_change_flow_end_to_end(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    await _setup_entry(hass, roster)

    pin_entry = "text.family_dashboard_pin_entry"
    authorized = "binary_sensor.family_dashboard_pin_change_authorized"
    parent_pin = "text.family_dashboard_parent_pin"
    assert hass.states.get(authorized).state == "off"
    assert hass.states.get(parent_pin).state == "1234"

    # Wrong old PIN - not authorized, buffer cleared.
    for digit in "0000":
        await _append_raw(hass, digit)
    await hass.services.async_call(
        "family_dashboard", "verify_old_pin", {"entity_id": pin_entry}, blocking=True
    )
    assert hass.states.get(authorized).state == "off"
    assert hass.states.get(pin_entry).state == ""

    # Correct old PIN - opens the authorized window.
    for digit in "1234":
        await _append_raw(hass, digit)
    await hass.services.async_call(
        "family_dashboard", "verify_old_pin", {"entity_id": pin_entry}, blocking=True
    )
    assert hass.states.get(authorized).state == "on"
    assert hass.states.get(pin_entry).state == ""

    # Too-short new PIN while authorized - silent no-op, window stays open.
    for digit in "12":
        await _append_raw(hass, digit)
    await hass.services.async_call(
        "family_dashboard", "save_new_pin", {"entity_id": pin_entry}, blocking=True
    )
    assert hass.states.get(authorized).state == "on"
    assert hass.states.get(pin_entry).state == "12"

    # Save a real new PIN (6 digits) - persists, closes the window, clears the buffer.
    for digit in "3456":
        await _append_raw(hass, digit)
    assert hass.states.get(pin_entry).state == "123456"
    await hass.services.async_call(
        "family_dashboard", "save_new_pin", {"entity_id": pin_entry}, blocking=True
    )
    assert hass.states.get(parent_pin).state == "123456"
    assert hass.states.get(authorized).state == "off"
    assert hass.states.get(pin_entry).state == ""

    # The old PIN no longer unlocks parent mode; the new one does.
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "family_dashboard",
            "unlock_parent_mode",
            {"entity_id": "binary_sensor.family_dashboard_parent_mode", "pin": "1234"},
            blocking=True,
        )
    await hass.services.async_call(
        "family_dashboard",
        "unlock_parent_mode",
        {"entity_id": "binary_sensor.family_dashboard_parent_mode", "pin": "123456"},
        blocking=True,
    )
    assert hass.states.get("binary_sensor.family_dashboard_parent_mode").state == "on"


async def test_save_new_pin_is_noop_when_not_authorized(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    await _setup_entry(hass, roster)

    pin_entry = "text.family_dashboard_pin_entry"
    for digit in "9999":
        await _append_raw(hass, digit)
    await hass.services.async_call(
        "family_dashboard", "save_new_pin", {"entity_id": pin_entry}, blocking=True
    )
    # Never verified the old PIN first - save is a no-op, buffer untouched, old PIN unchanged.
    assert hass.states.get(pin_entry).state == "9999"
    assert hass.states.get("text.family_dashboard_parent_pin").state == "1234"


async def test_chore_assigned_to_member_without_chores_feature_gets_no_entities(
    hass: HomeAssistant,
):
    """Regression: task sensors/buttons used to be created for every chore/reward regardless
    of whether the assigned member currently has "chores" selected - only the points sensor
    was ever filtered by feature. A sibling still having "chores" enabled must not resurrect
    another member's own entities once their feature is off."""
    roster = [_member("Ada", "ada", features=()), _member("Grace", "grace", features=("chores",))]
    chores = [
        {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"},
        {"chore_id": "dishes", "name": "Dishes", "points": 5, "frequency": "daily", "assigned_to": "grace"},
    ]
    await _setup_entry(hass, roster, chores=chores)

    assert hass.states.get("sensor.family_dashboard_trash") is None
    assert hass.states.get("button.family_dashboard_trash_claim") is None
    assert hass.states.get("button.family_dashboard_trash_approve") is None
    assert hass.states.get("sensor.family_dashboard_ada_points") is None

    # Grace's own chore is untouched by Ada's feature being off.
    assert hass.states.get("sensor.family_dashboard_dishes") is not None
    assert hass.states.get("button.family_dashboard_dishes_claim") is not None


async def test_sibling_points_are_isolated(hass: HomeAssistant):
    roster = [_member("Ada", "ada"), _member("Grace", "grace")]
    chores = [
        {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}
    ]
    await _setup_entry(hass, roster, chores=chores)

    await _press(hass, "button.family_dashboard_trash_claim")
    await _press(hass, "button.family_dashboard_trash_approve")

    assert hass.states.get("sensor.family_dashboard_ada_points").state == "10"
    assert hass.states.get("sensor.family_dashboard_grace_points").state == "0"


async def test_chore_field_entities_created_with_initial_values(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    chores = [
        {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "weekly", "assigned_to": "ada"}
    ]
    await _setup_entry(hass, roster, chores=chores)

    assert hass.states.get("text.family_dashboard_trash_name").state == "Trash"
    assert hass.states.get("number.family_dashboard_trash_points").state == "10"
    assert hass.states.get("select.family_dashboard_trash_frequency").state == "Weekly"
    assert hass.states.get("select.family_dashboard_trash_assigned_to").state == "Ada"


async def test_editing_chore_fields_via_real_services_persists(hass: HomeAssistant):
    roster = [_member("Ada", "ada"), _member("Grace", "grace")]
    chores = [
        {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}
    ]
    entry = await _setup_entry(hass, roster, chores=chores)

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.family_dashboard_trash_points", "value": 25},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.data["chores"][0]["points"] == 25
    assert hass.states.get("number.family_dashboard_trash_points").state == "25"

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.family_dashboard_trash_assigned_to", "option": "Grace"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.data["chores"][0]["assigned_to"] == "grace"
    # unique_id/entity_id are keyed on chore_id, not assigned_to - same "never re-derive a
    # stable id from mutable data" principle as util.slugify_unique's own docstring (member_id
    # doesn't change when a member's display name is edited). Reassigning updates WHO it's
    # for, not the entity's own identity - the same sensor.family_dashboard_trash entity_id
    # persists, its "assigned_to" attribute (and friendly name on next reload) now say Grace.
    task_state = hass.states.get("sensor.family_dashboard_trash")
    assert task_state is not None
    assert task_state.attributes["assigned_to"] == "Grace"


async def test_deleting_chore_via_service_removes_it_with_confirmation_gated_dashboard(
    hass: HomeAssistant,
):
    """The dashboard's Delete tile gates this behind a native `confirmation:` tap_action -
    this test calls the service directly (as the confirmed tap would), proving deletion is a
    genuine removal end-to-end from a real entity, not just `crud.py` in isolation."""
    roster = [_member("Ada", "ada")]
    chores = [
        {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}
    ]
    entry = await _setup_entry(hass, roster, chores=chores)

    await hass.services.async_call(
        "family_dashboard",
        "delete_task",
        {"entity_id": "sensor.family_dashboard_trash"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("sensor.family_dashboard_trash") is None
    assert hass.states.get("text.family_dashboard_trash_name") is None
    assert entry.data["chores"] == []
