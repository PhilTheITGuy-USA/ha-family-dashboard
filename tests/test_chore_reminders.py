"""Chore reminders: at 4/6/7 PM, each kid with a phone gets one notification listing their
due-today chores that have reminders on and aren't claimed or approved yet.

Dates: Mon 2026-09-21. Chores are due every day unless a test says otherwise.
"""
from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.family_dashboard.const import DOMAIN


def _member(member_id="ada", name="Ada", notify="notify.ada_phone", **extra):
    return {
        "member_id": member_id, "name": name, "color": "Blue", "features": ["chores"],
        "ha_user_id": None, "calendar_entity_id": None, "notify_entity_id": notify,
        "list_presets": [], **extra,
    }


def _chore(chore_id, name, assigned_to="ada", reminders=True, **schedule):
    chore = {"chore_id": chore_id, "name": name, "points": 5, "assigned_to": assigned_to,
             "repeat": "days_of_week", **schedule}
    if reminders:
        chore["reminders"] = True
    return chore


async def _at(hass, freezer, hour, minute=0, day=21):
    local = datetime(2026, 9, day, hour, minute, 0, tzinfo=dt_util.get_default_time_zone())
    freezer.move_to(local)
    async_fire_time_changed(hass, local)
    await hass.async_block_till_done()


async def _setup(hass, roster, chores):
    entry = MockConfigEntry(
        version=1, domain=DOMAIN, title="Family Dashboard",
        data={"roster": roster, "chores": chores, "rewards": []},
        source="user", unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    async_mock_service(hass, "logbook", "log")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _press(hass, entity_id):
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def test_sends_one_notification_listing_outstanding_chores(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)
    calls = async_mock_service(hass, "notify", "send_message")
    await _setup(hass, [_member()], [_chore("dishes", "Dishes"), _chore("trash", "Trash")])

    await _at(hass, freezer, 16)

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["notify.ada_phone"]
    assert calls[0].data["title"] == "Chores left today"
    assert calls[0].data["message"] == "Dishes, Trash"


async def test_fires_at_4_6_and_7_only(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)
    calls = async_mock_service(hass, "notify", "send_message")
    await _setup(hass, [_member()], [_chore("dishes", "Dishes")])

    for hour in (15, 16, 17, 18, 19, 20):
        await _at(hass, freezer, hour)

    assert len(calls) == 3


async def test_skips_claimed_and_approved_but_reminds_denied(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)
    calls = async_mock_service(hass, "notify", "send_message")
    await _setup(
        hass, [_member()],
        [_chore("dishes", "Dishes"), _chore("trash", "Trash"), _chore("bed", "Bed")],
    )
    await _press(hass, "button.family_dashboard_dishes_claim")  # left pending
    await _press(hass, "button.family_dashboard_trash_claim")
    await _press(hass, "button.family_dashboard_trash_approve")
    await _press(hass, "button.family_dashboard_bed_claim")
    await hass.services.async_call(
        DOMAIN, "deny_task",
        {"entity_id": "sensor.family_dashboard_bed", "reason": "Not made"}, blocking=True,
    )

    await _at(hass, freezer, 16)

    assert [c.data["message"] for c in calls] == ["Bed"]


async def test_skips_reminders_off_not_due_and_unassigned(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)  # Monday
    calls = async_mock_service(hass, "notify", "send_message")
    await _setup(
        hass, [_member()],
        [
            _chore("dishes", "Dishes", reminders=False),
            _chore("trash", "Trash", schedule_days=["tuesday"]),
            _chore("lawn", "Lawn", assigned_to=None),
        ],
    )

    await _at(hass, freezer, 16)

    assert calls == []


async def test_skips_member_without_phone_or_disabled(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)
    calls = async_mock_service(hass, "notify", "send_message")
    await _setup(
        hass,
        [_member("ada", "Ada", notify=None), _member("bo", "Bo", notify="notify.bo", disabled=True)],
        [_chore("dishes", "Dishes"), _chore("trash", "Trash", assigned_to="bo")],
    )

    await _at(hass, freezer, 16)

    assert calls == []


async def test_one_failing_phone_does_not_stop_the_others(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)
    sent = []

    async def _send(call):
        if call.data["entity_id"] == ["notify.ada_phone"]:
            raise HomeAssistantError("gone")
        sent.append(call.data["entity_id"])

    hass.services.async_register("notify", "send_message", _send)
    await _setup(
        hass, [_member(), _member("bo", "Bo", notify="notify.bo")],
        [_chore("dishes", "Dishes"), _chore("trash", "Trash", assigned_to="bo")],
    )

    await _at(hass, freezer, 16)

    assert sent == [["notify.bo"]]
