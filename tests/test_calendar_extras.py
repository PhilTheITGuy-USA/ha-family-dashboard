"""Tests for the 2026-07-13 feature-audit additions to Calendar: the avatar picker backend,
the calendar view-granularity selector, the Add Event popup's target-calendar options, and the
add_event service (real create_event call + reminder tag generation + scratch-field reset).
"""
from __future__ import annotations

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, setup_test_component_platform

from custom_components.family_dashboard.const import DOMAIN
from custom_components.family_dashboard.modules.settings.sensor import avatars_dir


class FakeSourceCalendar(CalendarEntity):
    _attr_name = "Fake Source"
    _attr_unique_id = "fake_source"
    _attr_should_poll = False

    def __init__(self) -> None:
        self._events: list[CalendarEvent] = []

    @property
    def event(self):
        return None

    async def async_get_events(self, hass, start_date, end_date):
        return self._events

    async def async_create_event(self, **kwargs) -> None:
        kwargs.pop("entity_id", None)
        self._events.append(CalendarEvent(**_normalize(kwargs)))


def _normalize(kwargs: dict) -> dict:
    # The real calendar.create_event service normalizes start_date_time/end_date_time (or
    # start_date/end_date) into dtstart/dtend before calling the entity - CalendarEvent's
    # constructor wants start/end instead.
    out = dict(kwargs)
    for src in ("start_date_time", "start_date", "dtstart"):
        if src in out:
            out["start"] = out.pop(src)
    for src in ("end_date_time", "end_date", "dtend"):
        if src in out:
            out["end"] = out.pop(src)
    return out


async def _setup_fake_source_calendar(hass: HomeAssistant) -> FakeSourceCalendar:
    fake = FakeSourceCalendar()
    setup_test_component_platform(hass, "calendar", [fake])
    assert await async_setup_component(hass, "calendar", {"calendar": [{"platform": "test"}]})
    await hass.async_block_till_done()
    return fake


def _member(name, member_id, calendar_entity_id=None):
    return {
        "member_id": member_id,
        "name": name,
        "color": "Blue",
        "features": ["calendar"],
        "ha_user_id": None,
        "calendar_entity_id": calendar_entity_id,
        "notify_entity_id": None,
        "list_presets": [],
    }


async def _setup_entry(hass: HomeAssistant, roster: list[dict], family_calendar_member_id=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Family Dashboard",
        data={"roster": roster, "family_calendar_member_id": family_calendar_member_id},
        source="user",
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_avatar_select_options_come_from_seeded_folder(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    # Seed one extra custom PNG directly into the avatars dir before setup, alongside
    # whatever the integration's own first-run asset seeding (assets.py) adds automatically -
    # both should end up in the picker's options, not just one or the other.
    avatars_dir(hass).mkdir(parents=True, exist_ok=True)
    (avatars_dir(hass) / "custom.png").write_bytes(b"")

    await _setup_entry(hass, roster)

    avatar_state = hass.states.get("select.family_dashboard_ada_avatar")
    assert avatar_state is not None
    options = avatar_state.attributes["options"]
    assert "/local/family_dashboard/avatars/custom.png" in options
    # The two shipped defaults (assets.py/www/avatars/*.png) were seeded automatically.
    assert "/local/family_dashboard/avatars/person-solid.png" in options
    assert "/local/family_dashboard/avatars/people-group-solid.png" in options
    assert avatar_state.state in options


async def test_calendar_view_selector_cycles(hass: HomeAssistant):
    roster = [_member("Ada", "ada")]
    await _setup_entry(hass, roster)

    entity_id = "select.family_dashboard_calendar_view"
    assert hass.states.get(entity_id).state == "Week"

    await hass.services.async_call("select", "select_next", {"entity_id": entity_id}, blocking=True)
    assert hass.states.get(entity_id).state == "Biweek"


async def test_event_calendar_select_options_include_family(hass: HomeAssistant):
    await _setup_fake_source_calendar(hass)
    roster = [
        _member("Ada", "ada", calendar_entity_id="calendar.fake_source"),
        _member("Grace", "grace", calendar_entity_id="calendar.fake_source"),
    ]
    await _setup_entry(hass, roster, family_calendar_member_id="grace")

    state = hass.states.get("select.family_dashboard_event_calendar")
    assert state.attributes["options"] == ["Ada", "Grace", "Family"]


async def test_add_event_creates_real_event_with_reminder_tags_and_resets_fields(hass: HomeAssistant):
    await _setup_fake_source_calendar(hass)
    roster = [_member("Ada", "ada", calendar_entity_id="calendar.fake_source")]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "text", "set_value",
        {"entity_id": "text.family_dashboard_event_title", "value": "Dentist"},
        blocking=True,
    )
    await hass.services.async_call(
        "text", "set_value",
        {"entity_id": "text.family_dashboard_event_description", "value": "Checkup"},
        blocking=True,
    )
    await hass.services.async_call(
        "datetime", "set_value",
        {"entity_id": "datetime.family_dashboard_event_start", "datetime": "2026-08-01T10:00:00+00:00"},
        blocking=True,
    )
    await hass.services.async_call(
        "datetime", "set_value",
        {"entity_id": "datetime.family_dashboard_event_end", "datetime": "2026-08-01T11:00:00+00:00"},
        blocking=True,
    )
    await hass.services.async_call(
        "switch", "turn_on",
        {"entity_id": "switch.family_dashboard_event_remind_1_day_before"},
        blocking=True,
    )

    await hass.services.async_call(
        "family_dashboard", "add_event",
        {"entity_id": "select.family_dashboard_event_calendar"},
        blocking=True,
    )
    await hass.async_block_till_done()

    events = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": "calendar.fake_source", "duration": {"days": 365}},
        blocking=True, return_response=True,
    )
    created = events["calendar.fake_source"]["events"]
    assert len(created) == 1
    assert created[0]["summary"] == "Dentist"
    assert "[[reminder:1d]]" in created[0]["description"]

    assert hass.states.get("text.family_dashboard_event_title").state == ""
    assert hass.states.get("switch.family_dashboard_event_remind_1_day_before").state == "off"
