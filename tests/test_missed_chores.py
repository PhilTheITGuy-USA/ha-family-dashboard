"""The missed-chores list: a due day that ended with the chore never claimed, or denied and
not redone. Kept 30 days; a parent can dismiss one entry or clear all.

Dates: Mon 2026-09-21 .. Sun 2026-09-27. The test chore is due Mondays and Thursdays.
"""
from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache,
)

from custom_components.family_dashboard.const import DOMAIN

ENTRY_ID = "fdtest"
STORE_KEY = f"family_dashboard.{ENTRY_ID}.missed_chores"
MISSED = "sensor.family_dashboard_missed_chores"
TASK = "sensor.family_dashboard_trash"
MON, TUE, WED, THU, FRI = 21, 22, 23, 24, 25


def _member():
    return {
        "member_id": "ada", "name": "Ada", "color": "Blue", "features": ["chores"],
        "ha_user_id": None, "calendar_entity_id": None, "notify_entity_id": None,
        "list_presets": [],
    }


def _chore(**overrides):
    chore = {
        "chore_id": "trash", "name": "Trash", "points": 10, "assigned_to": "ada",
        "repeat": "days_of_week", "schedule_days": ["monday", "thursday"],
    }
    chore.update(overrides)
    return {k: v for k, v in chore.items() if v is not None or k == "assigned_to"}


def _stored(entries):
    return {"version": 1, "minor_version": 1, "key": STORE_KEY, "data": {"entries": entries}}


async def _at(hass, freezer, day, hour=12, minute=0, second=0):
    local = datetime(2026, 9, day, hour, minute, second, tzinfo=dt_util.get_default_time_zone())
    freezer.move_to(local)
    async_fire_time_changed(hass, local)
    await hass.async_block_till_done()


async def _midnight(hass, freezer, day):
    await _at(hass, freezer, day, 0, 0, 5)


async def _setup(hass, chores=None):
    entry = MockConfigEntry(
        version=1, domain=DOMAIN, title="Family Dashboard", entry_id=ENTRY_ID,
        data={"roster": [_member()], "chores": [_chore()] if chores is None else chores, "rewards": []},
        source="user", unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    async_mock_service(hass, "logbook", "log")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entries(hass):
    return hass.states.get(MISSED).attributes["entries"]


def _summary(hass):
    return [(e["date"], e["chore_name"], e["reason"]) for e in _entries(hass)]


def _entry(missed_id, day, name="Trash"):
    return {"id": missed_id, "date": day, "chore_id": name.lower(), "chore_name": name,
            "member_id": "ada", "member_name": "Ada", "reason": "not_claimed"}


async def test_loads_stored_entries_and_prunes_older_than_30_days(hass: HomeAssistant, freezer, hass_storage):
    await _at(hass, freezer, MON)
    hass_storage[STORE_KEY] = _stored([_entry("a", "2026-09-17"), _entry("b", "2026-08-01")])

    await _setup(hass)

    assert hass.states.get(MISSED).state == "1"
    assert [e["id"] for e in _entries(hass)] == ["a"]


async def test_dismiss_and_clear(hass: HomeAssistant, freezer, hass_storage):
    await _at(hass, freezer, MON)
    hass_storage[STORE_KEY] = _stored(
        [_entry("a", "2026-09-17"), _entry("b", "2026-09-18", "Dishes"), _entry("c", "2026-09-19", "Bed")]
    )
    await _setup(hass)

    await hass.services.async_call(
        DOMAIN, "dismiss_missed_chore", {"entity_id": MISSED, "missed_id": "b"}, blocking=True
    )
    await hass.async_block_till_done()
    assert [e["id"] for e in _entries(hass)] == ["c", "a"]  # newest first

    await hass.services.async_call(DOMAIN, "clear_missed_chores", {"entity_id": MISSED}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(MISSED).state == "0"


async def _press(hass, entity_id):
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def _deny(hass):
    await hass.services.async_call(
        DOMAIN, "deny_task", {"entity_id": TASK, "reason": "Not done"}, blocking=True
    )
    await hass.async_block_till_done()


async def test_never_claimed_is_recorded_next_midnight(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)

    await _midnight(hass, freezer, TUE)

    assert _summary(hass) == [("2026-09-21", "Trash", "not_claimed")]


async def test_claimed_and_approved_is_not_missed(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _press(hass, "button.family_dashboard_trash_claim")
    await _press(hass, "button.family_dashboard_trash_approve")

    await _midnight(hass, freezer, TUE)

    assert _summary(hass) == []


async def test_denied_same_day_is_recorded_next_midnight(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _press(hass, "button.family_dashboard_trash_claim")
    await _deny(hass)

    await _midnight(hass, freezer, TUE)

    assert _summary(hass) == [("2026-09-21", "Trash", "denied")]


async def test_denied_then_redone_is_not_missed(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _press(hass, "button.family_dashboard_trash_claim")
    await _deny(hass)
    await _press(hass, "button.family_dashboard_trash_claim")
    await _press(hass, "button.family_dashboard_trash_approve")

    await _midnight(hass, freezer, TUE)

    assert _summary(hass) == []


async def test_pending_at_midnight_then_denied_late(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _press(hass, "button.family_dashboard_trash_claim")

    await _midnight(hass, freezer, TUE)
    assert _summary(hass) == []

    await _at(hass, freezer, WED)
    await _deny(hass)
    assert _summary(hass) == [("2026-09-21", "Trash", "denied")]


async def test_pending_claim_blocks_later_due_day(hass: HomeAssistant, freezer):
    """Claimed Monday, not reviewed until Friday - the kid couldn't claim Thursday."""
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _press(hass, "button.family_dashboard_trash_claim")

    await _midnight(hass, freezer, FRI)

    assert _summary(hass) == []


async def test_startup_catches_up_only_due_days(hass: HomeAssistant, freezer):
    await _at(hass, freezer, FRI)
    mock_restore_cache(hass, [State(TASK, "idle", {"checked_through": "2026-09-20"})])

    await _setup(hass)

    assert _summary(hass) == [
        ("2026-09-24", "Trash", "not_claimed"),
        ("2026-09-21", "Trash", "not_claimed"),
    ]


async def test_first_start_does_not_backfill(hass: HomeAssistant, freezer):
    await _at(hass, freezer, FRI)
    await _setup(hass)

    assert _summary(hass) == []
    assert hass.states.get(TASK).attributes["checked_through"] == "2026-09-24"


async def test_monthly_chore_respects_its_day(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass, chores=[_chore(repeat="monthly", month_days=[22], schedule_days=None)])

    await _midnight(hass, freezer, WED)

    assert _summary(hass) == [("2026-09-22", "Trash", "not_claimed")]


async def test_one_time_chore_is_never_recorded(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass, chores=[_chore(repeat="one_time", schedule_days=None)])

    await _midnight(hass, freezer, WED)

    assert _summary(hass) == []


async def test_unassigned_chore_is_never_recorded(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass, chores=[_chore(assigned_to=None)])

    await _midnight(hass, freezer, TUE)

    assert _summary(hass) == []


async def test_entries_survive_deleting_the_chore(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _midnight(hass, freezer, TUE)

    await hass.services.async_call(DOMAIN, "delete_task", {"entity_id": TASK}, blocking=True)
    await hass.async_block_till_done()

    assert _summary(hass) == [("2026-09-21", "Trash", "not_claimed")]
