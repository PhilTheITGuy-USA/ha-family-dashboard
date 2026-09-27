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
