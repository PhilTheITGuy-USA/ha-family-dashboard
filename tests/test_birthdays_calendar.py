"""Tests for the computed Birthdays calendar entity (modules/calendar/birthdays.py) - covers
the pure date-math helper (leap years, cross-year-boundary windows, multiple members, age
calculation) and that the real entity reads each member's birthdate LIVE (not a snapshot baked
in at add-time - editing it via the Settings dashboard's real `date` entity must be reflected
immediately, without a reload).
"""
from __future__ import annotations

from datetime import date

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_dashboard.const import DOMAIN
from custom_components.family_dashboard.modules.calendar.birthdays import (
    birthday_occurrences_in_range,
)


def test_single_occurrence_within_range():
    events = birthday_occurrences_in_range(
        [("Ada", date(2015, 6, 21))], date(2026, 6, 1), date(2026, 7, 1)
    )
    assert len(events) == 1
    assert events[0].start == date(2026, 6, 21)
    assert events[0].summary == "Ada's Birthday (turns 11)"


def test_occurrence_outside_range_excluded():
    events = birthday_occurrences_in_range(
        [("Ada", date(2015, 6, 21))], date(2026, 1, 1), date(2026, 2, 1)
    )
    assert events == []


def test_leap_year_birthday_falls_back_to_feb_28_in_non_leap_year():
    events = birthday_occurrences_in_range(
        [("Ada", date(2016, 2, 29))], date(2026, 2, 1), date(2026, 3, 1)
    )
    assert len(events) == 1
    assert events[0].start == date(2026, 2, 28)


def test_leap_year_birthday_lands_on_feb_29_in_a_leap_year():
    events = birthday_occurrences_in_range(
        [("Ada", date(2016, 2, 29))], date(2028, 2, 1), date(2028, 3, 1)
    )
    assert events[0].start == date(2028, 2, 29)


def test_cross_year_boundary_window_checks_every_spanned_year():
    # A window spanning New Year's must catch a birthday just after Jan 1 too, not just an
    # occurrence in start_date.year - the whole point of iterating every spanned year.
    events = birthday_occurrences_in_range(
        [("Ada", date(2015, 1, 5))], date(2025, 12, 20), date(2026, 1, 10)
    )
    assert len(events) == 1
    assert events[0].start == date(2026, 1, 5)


def test_multiple_members_each_get_their_own_event():
    events = birthday_occurrences_in_range(
        [("Ada", date(2015, 6, 21)), ("Grace", date(2018, 6, 25))],
        date(2026, 6, 1),
        date(2026, 7, 1),
    )
    assert {e.summary for e in events} == {
        "Ada's Birthday (turns 11)",
        "Grace's Birthday (turns 8)",
    }


def test_no_members_produces_no_events():
    assert birthday_occurrences_in_range([], date(2026, 1, 1), date(2027, 1, 1)) == []


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


async def _get_events(hass: HomeAssistant) -> list[dict]:
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": "calendar.family_dashboard_birthdays",
            "start_date_time": "2026-01-01T00:00:00",
            "duration": {"days": 365},
        },
        blocking=True,
        return_response=True,
    )
    return response["calendar.family_dashboard_birthdays"]["events"]


async def test_birthdays_entity_always_created_when_calendar_feature_enabled(
    hass: HomeAssistant,
):
    """Household-wide, not per-member - exists even though Ada hasn't mapped a source
    calendar at all (independent of any per-member calendar_entity_id)."""
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue", "features": ["calendar"]}]
    await _setup_entry(hass, roster)

    assert hass.states.get("calendar.family_dashboard_birthdays") is not None
    assert await _get_events(hass) == []


async def test_birthdays_entity_reads_live_birthdate_not_snapshot(hass: HomeAssistant):
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue", "features": ["calendar"]}]
    await _setup_entry(hass, roster)
    assert await _get_events(hass) == []

    # Set the birthdate live via the real service, AFTER the entity was already added - it
    # must reflect this immediately, proving it reads state live rather than baking in
    # whatever was in entry.data at add-time.
    await hass.services.async_call(
        "date",
        "set_value",
        {"entity_id": "date.family_dashboard_ada_birthdate", "date": "2015-06-21"},
        blocking=True,
    )
    events = await _get_events(hass)
    assert len(events) == 1
    assert "Ada's Birthday" in events[0]["summary"]
