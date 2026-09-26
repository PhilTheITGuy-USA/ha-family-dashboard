"""A chore's status over time: each due day is its own claimable instance.

Covers claim only on due days; reviewed chores reset at the next due day's midnight (and at
startup, if HA was off at midnight); an unreviewed claim waits for review and, if a newer due
day started meanwhile, resets as soon as it's reviewed; Reset undoes a pending claim; rewards
are redeemable again right after approval; one-time chores stay done.

Dates: Mon 2026-09-21 .. Sun 2026-09-27. The test chore is due Mondays and Thursdays.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache,
)

from custom_components.family_dashboard.const import DOMAIN

TASK = "sensor.family_dashboard_trash"
POINTS = "sensor.family_dashboard_ada_points"
MON, TUE, THU = 21, 22, 24


def _member():
    return {
        "member_id": "ada",
        "name": "Ada",
        "color": "Blue",
        "features": ["chores"],
        "ha_user_id": None,
        "calendar_entity_id": None,
        "notify_entity_id": None,
        "list_presets": [],
    }


def _chore(**schedule):
    schedule = schedule or {"repeat": "days_of_week", "schedule_days": ["monday", "thursday"]}
    return {"chore_id": "trash", "name": "Trash", "points": 10, "assigned_to": "ada", **schedule}


async def _at(hass: HomeAssistant, freezer, day: int, hour=12, minute=0, second=0) -> None:
    """Move the clock to a local time in the test week and let time listeners fire."""
    local = datetime(2026, 9, day, hour, minute, second, tzinfo=dt_util.get_default_time_zone())
    freezer.move_to(local)
    async_fire_time_changed(hass, local)
    await hass.async_block_till_done()


async def _midnight(hass: HomeAssistant, freezer, day: int) -> None:
    await _at(hass, freezer, day, 0, 0, 5)


async def _setup(hass: HomeAssistant, chores=None, rewards=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Family Dashboard",
        data={
            "roster": [_member()],
            "chores": [_chore()] if chores is None else chores,
            "rewards": rewards or [],
        },
        source="user",
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    async_mock_service(hass, "logbook", "log")  # Deny logs its reason
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def _claim(hass, item="trash"):
    await _press(hass, f"button.family_dashboard_{item}_claim")


async def _approve(hass, item="trash"):
    await _press(hass, f"button.family_dashboard_{item}_approve")


async def _service(hass: HomeAssistant, service: str, entity_id: str = TASK, **data) -> None:
    await hass.services.async_call(
        DOMAIN, service, {"entity_id": entity_id, **data}, blocking=True
    )
    await hass.async_block_till_done()


def _state(hass):
    return hass.states.get(TASK)


async def test_claim_refused_when_not_due(hass: HomeAssistant, freezer):
    await _at(hass, freezer, TUE)
    await _setup(hass)

    assert _state(hass).attributes["due_today"] is False
    with pytest.raises(HomeAssistantError, match="isn't due today"):
        await _claim(hass)
    assert _state(hass).state == "idle"


async def test_claim_sets_claimed_on_and_refuses_double_claim(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)

    assert _state(hass).attributes["due_today"] is True
    await _claim(hass)
    assert _state(hass).state == "claimed"
    assert _state(hass).attributes["claimed_on"] == "2026-09-21"

    with pytest.raises(HomeAssistantError, match="already claimed"):
        await _claim(hass)


async def test_approve_same_day_stays_approved_until_next_due_day(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _claim(hass)
    await _approve(hass)
    assert _state(hass).state == "approved"
    assert hass.states.get(POINTS).state == "10"

    with pytest.raises(HomeAssistantError, match="already approved"):
        await _claim(hass)

    await _midnight(hass, freezer, TUE)
    assert _state(hass).state == "approved"
    assert _state(hass).attributes["due_today"] is False

    await _midnight(hass, freezer, THU)
    assert _state(hass).state == "idle"
    assert _state(hass).attributes["due_today"] is True
    assert "claimed_on" not in _state(hass).attributes

    await _claim(hass)
    assert _state(hass).attributes["claimed_on"] == "2026-09-24"


async def test_claimed_survives_midnight(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _claim(hass)

    await _midnight(hass, freezer, THU)

    assert _state(hass).state == "claimed"
    assert _state(hass).attributes["claimed_on"] == "2026-09-21"


async def test_late_review_resets_immediately(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _claim(hass)
    await _midnight(hass, freezer, THU)

    await _approve(hass)

    # Monday's points still count, and Thursday's instance is claimable straight away.
    assert hass.states.get(POINTS).state == "10"
    assert _state(hass).state == "idle"
    await _claim(hass)
    assert _state(hass).attributes["claimed_on"] == "2026-09-24"


async def test_late_denial_resets_immediately(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _claim(hass)
    await _midnight(hass, freezer, THU)

    await _service(hass, "deny_task", reason="Not done")

    assert _state(hass).state == "idle"


async def test_late_review_waits_if_no_new_due_day(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _claim(hass)
    await _midnight(hass, freezer, TUE)

    await _approve(hass)

    assert _state(hass).state == "approved"


async def test_denied_is_reclaimable_same_day(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _claim(hass)
    await _service(hass, "deny_task", reason="Missed a spot")
    assert _state(hass).state == "denied"

    await _claim(hass)

    assert _state(hass).state == "claimed"


async def test_reset_claim_only_from_claimed(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)

    with pytest.raises(HomeAssistantError, match="no pending claim"):
        await _service(hass, "reset_claim")

    await _claim(hass)
    await _service(hass, "reset_claim")

    assert _state(hass).state == "idle"
    assert "claimed_on" not in _state(hass).attributes
    assert hass.states.get(POINTS).state == "0"


async def test_reward_approve_returns_to_idle_and_deducts(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(
        hass,
        rewards=[{"reward_id": "movie", "name": "Movie", "cost": 4, "assigned_to": "ada"}],
    )
    await _service(hass, "adjust_points", POINTS, delta=10)

    await _claim(hass, "movie")
    await _approve(hass, "movie")

    assert hass.states.get("sensor.family_dashboard_movie").state == "idle"
    assert hass.states.get(POINTS).state == "6"
    await _claim(hass, "movie")
    assert hass.states.get("sensor.family_dashboard_movie").state == "claimed"


async def test_reset_claim_works_for_rewards(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(
        hass,
        rewards=[{"reward_id": "movie", "name": "Movie", "cost": 4, "assigned_to": "ada"}],
    )
    await _claim(hass, "movie")

    await _service(hass, "reset_claim", "sensor.family_dashboard_movie")

    assert hass.states.get("sensor.family_dashboard_movie").state == "idle"


async def test_startup_catch_up_after_gap(hass: HomeAssistant, freezer):
    """Approved last Monday, HA off since - this Monday it must be claimable again."""
    await _at(hass, freezer, MON)
    mock_restore_cache(hass, [State(TASK, "approved", {"claimed_on": "2026-09-14"})])

    await _setup(hass)

    assert _state(hass).state == "idle"


async def test_restored_claim_keeps_claimed_on(hass: HomeAssistant, freezer):
    await _at(hass, freezer, THU)
    mock_restore_cache(hass, [State(TASK, "claimed", {"claimed_on": "2026-09-21"})])

    await _setup(hass)

    assert _state(hass).state == "claimed"
    assert _state(hass).attributes["claimed_on"] == "2026-09-21"


async def test_stale_approved_without_claimed_on_upgrades_to_idle(hass: HomeAssistant, freezer):
    """Installs from before scheduling have chores stuck `approved` with no instance date."""
    await _at(hass, freezer, MON)
    mock_restore_cache(hass, [State(TASK, "approved", {})])

    await _setup(hass)

    assert _state(hass).state == "idle"


async def test_stale_approved_waits_for_a_due_day(hass: HomeAssistant, freezer):
    await _at(hass, freezer, TUE)
    mock_restore_cache(hass, [State(TASK, "approved", {})])
    await _setup(hass)
    assert _state(hass).state == "approved"

    await _midnight(hass, freezer, THU)

    assert _state(hass).state == "idle"


async def test_one_time_approved_stays_approved(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass, chores=[_chore(repeat="one_time")])
    await _claim(hass)
    await _approve(hass)

    await _midnight(hass, freezer, THU)

    assert _state(hass).state == "approved"


async def test_monthly_chore_due_on_its_day(hass: HomeAssistant, freezer):
    await _at(hass, freezer, THU)  # the 24th
    await _setup(hass, chores=[_chore(repeat="monthly", month_days=[24])])

    await _claim(hass)

    assert _state(hass).state == "claimed"
