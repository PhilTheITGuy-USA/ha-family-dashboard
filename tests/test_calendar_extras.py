"""Tests for the 2026-07-13 feature-audit additions to Calendar: the avatar picker backend,
the Add Event popup's target-calendar options, and the add_event service (real create_event
call + reminder tag generation + scratch-field reset).
"""
from __future__ import annotations

import homeassistant.components.datetime as datetime_component
from homeassistant.components.calendar import CalendarEntity, CalendarEntityFeature, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, setup_test_component_platform

from custom_components.family_dashboard.const import DOMAIN
from custom_components.family_dashboard.modules.settings.sensor import avatars_dir


def _datetime_native_value(hass: HomeAssistant, entity_id: str):
    """Fetch a `datetime` entity's real `native_value` directly rather than its formatted
    `state` string - `DateTimeEntity.state` renders as a UTC ISO string
    (`value.astimezone(UTC).isoformat(...)`), not the naive local wall-clock string a test
    might expect, so comparing against `.state` directly is timezone-fragile. Comparing
    individual fields (year/month/day/hour/minute) on the real object sidesteps that."""
    component = hass.data[datetime_component.DATA_COMPONENT]
    entity = component.get_entity(entity_id)
    return entity.native_value if entity else None


class FakeSourceCalendar(CalendarEntity):
    _attr_should_poll = False
    # events.py calls async_create_event directly (bypassing the calendar.create_event
    # SERVICE, which has no rrule/recurrence support at all) and replicates that service's own
    # CalendarEntityFeature.CREATE_EVENT support check itself - this fake needs to advertise
    # the feature too, or every add_event test would fail that check.
    _attr_supported_features = CalendarEntityFeature.CREATE_EVENT

    def __init__(self, name: str = "Fake Source", unique_id: str = "fake_source") -> None:
        self._attr_name = name
        self._attr_unique_id = unique_id
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


async def _setup_fake_source_calendar(hass: HomeAssistant, *extra: CalendarEntity) -> FakeSourceCalendar:
    fake = FakeSourceCalendar()
    setup_test_component_platform(hass, "calendar", [fake, *extra])
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


async def test_event_calendar_select_options_include_family(hass: HomeAssistant):
    # "Family" is auto-detected by calendar NAME, not member-flagged - a calendar.* entity
    # whose own name is literally "Family" is enough, independent of any roster member's own
    # mapping (see modules/calendar/dashboard.py's _family_calendar_entity).
    family_calendar = FakeSourceCalendar(name="Family", unique_id="family")
    await _setup_fake_source_calendar(hass, family_calendar)
    roster = [
        _member("Ada", "ada", calendar_entity_id="calendar.fake_source"),
        _member("Grace", "grace", calendar_entity_id="calendar.fake_source"),
    ]
    await _setup_entry(hass, roster)

    state = hass.states.get("select.family_dashboard_event_calendar")
    assert state.attributes["options"] == ["Ada", "Grace", "Family"]


async def test_add_event_creates_real_event_with_reminder_tags_and_resets_fields(hass: HomeAssistant):
    """Weeks/days/hours/minutes-before are independent configurable fields, not fixed 1-unit
    checkboxes (2026-07-25 live request) - weeks translate to the tag format's "d" component
    (there's no "w"), hours+minutes combine into one tag since they're the same tier."""
    fake = await _setup_fake_source_calendar(hass)
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
        {"entity_id": "datetime.family_dashboard_event_start", "datetime": "2026-08-01 09:00:00"},
        blocking=True,
    )
    # Start already cascaded End to 10:00 AM same day - see
    # test_start_datetime_defaults_end_to_one_hour_later for dedicated coverage of that.
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.family_dashboard_event_remind_weeks_before", "value": 2},
        blocking=True,
    )
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.family_dashboard_event_remind_hours_before", "value": 1},
        blocking=True,
    )
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.family_dashboard_event_remind_minutes_before", "value": 30},
        blocking=True,
    )

    await hass.services.async_call(
        "family_dashboard", "add_event",
        {"entity_id": "select.family_dashboard_event_calendar"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(fake._events) == 1
    created = fake._events[0]
    assert created.summary == "Dentist"
    assert "[[reminder:14d]]" in created.description  # 2 weeks -> 14 days
    assert "[[reminder:1h30m]]" in created.description  # hours+minutes combined
    # No stray days-before tag - that field was left at 0.
    assert created.description.count("[[reminder:") == 2

    assert hass.states.get("text.family_dashboard_event_title").state == ""
    assert hass.states.get("number.family_dashboard_event_remind_weeks_before").state == "0"
    assert hass.states.get("number.family_dashboard_event_remind_hours_before").state == "0"
    assert hass.states.get("number.family_dashboard_event_remind_minutes_before").state == "0"
    # Start/End datetime are reset after submit too, same hygiene as every other scratch
    # field - otherwise the NEXT event created would silently inherit stale values.
    assert hass.states.get("datetime.family_dashboard_event_start").state == "unknown"
    assert hass.states.get("datetime.family_dashboard_event_end").state == "unknown"


async def test_calendar_number_fields_round_to_whole_numbers(hass: HomeAssistant):
    """Live-reported: "1.2 days" or "1.5 hours before" is meaningless in this context - every
    Weeks/Days/Hours/Minutes-before reminder field rounds fractional input to the nearest
    whole number rather than storing it as-is."""
    await _setup_fake_source_calendar(hass)
    roster = [_member("Ada", "ada", calendar_entity_id="calendar.fake_source")]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.family_dashboard_event_remind_days_before", "value": 1.2},
        blocking=True,
    )
    assert hass.states.get("number.family_dashboard_event_remind_days_before").state == "1"

    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.family_dashboard_event_remind_hours_before", "value": 1.5},
        blocking=True,
    )
    assert hass.states.get("number.family_dashboard_event_remind_hours_before").state == "2"


async def test_start_datetime_defaults_end_to_one_hour_later(hass: HomeAssistant):
    """A live request: once Start has been entered, End should default to the same date, one
    hour later, so the common case doesn't require manually filling in End too. Start/End are
    a single combined `datetime` entity per side (2026-07-26, reverted from a decomposed
    Date+Hour+Minute+AM-PM group back to v0.9.0-beta.4's compact layout - see
    event_time.py's docstring), composed through a real `datetime` internally so a Start near
    midnight correctly rolls End over to the next calendar day. No separate AM/PM field is
    involved - the native picker's own stored value is trusted directly (see event_time.py's
    docstring for why an earlier same-day version's "correction" select was removed)."""
    await _setup_fake_source_calendar(hass)
    roster = [_member("Ada", "ada", calendar_entity_id="calendar.fake_source")]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "datetime", "set_value",
        {"entity_id": "datetime.family_dashboard_event_start", "datetime": "2026-08-01 09:00:00"},
        blocking=True,
    )
    end_value = _datetime_native_value(hass, "datetime.family_dashboard_event_end")
    assert (end_value.year, end_value.month, end_value.day, end_value.hour, end_value.minute) == (
        2026, 8, 1, 10, 0,
    )

    # A Start time near midnight correctly rolls End over to the next calendar day.
    await hass.services.async_call(
        "datetime", "set_value",
        {"entity_id": "datetime.family_dashboard_event_start", "datetime": "2026-08-01 23:30:00"},
        blocking=True,
    )
    end_value = _datetime_native_value(hass, "datetime.family_dashboard_event_end")
    assert (end_value.year, end_value.month, end_value.day, end_value.hour, end_value.minute) == (
        2026, 8, 2, 0, 30,
    )

    # The user's own subsequent End edit is the last word until Start changes again.
    await hass.services.async_call(
        "datetime", "set_value",
        {"entity_id": "datetime.family_dashboard_event_end", "datetime": "2026-08-02 03:00:00"},
        blocking=True,
    )
    end_value = _datetime_native_value(hass, "datetime.family_dashboard_event_end")
    assert (end_value.year, end_value.month, end_value.day, end_value.hour, end_value.minute) == (
        2026, 8, 2, 3, 0,
    )


async def test_add_event_uses_start_end_datetime_hour_directly(hass: HomeAssistant):
    """No separate AM/PM select exists anymore (removed 2026-07-26) - the native `datetime`
    entity's own stored value is passed straight through to `async_create_event`, since it's
    already a correct, fully-resolved absolute time regardless of which display format
    (12-hour or 24-hour) the viewer's account used to enter it."""
    fake = await _setup_fake_source_calendar(hass)
    roster = [_member("Ada", "ada", calendar_entity_id="calendar.fake_source")]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "datetime", "set_value",
        {"entity_id": "datetime.family_dashboard_event_start", "datetime": "2026-08-01 21:00:00"},
        blocking=True,
    )
    # Start's own cascade already defaulted End to 22:00 (10 PM), same day.

    await hass.services.async_call(
        "family_dashboard", "add_event",
        {"entity_id": "select.family_dashboard_event_calendar"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(fake._events) == 1
    created = fake._events[0]
    assert created.start.hour == 21  # 9:00 PM
    assert created.end.hour == 22  # 10:00 PM


async def test_start_date_defaults_end_date_to_same_day(hass: HomeAssistant):
    """Start Date/End Date are all-day-only fields (a timed event uses the separate combined
    `datetime` entity instead, see test_start_datetime_defaults_end_to_one_hour_later) - Start
    Date still defaults End Date to the same day on every set."""
    await _setup_fake_source_calendar(hass)
    roster = [_member("Ada", "ada", calendar_entity_id="calendar.fake_source")]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "date", "set_value",
        {"entity_id": "date.family_dashboard_event_start_date", "date": "2026-08-01"},
        blocking=True,
    )
    assert hass.states.get("date.family_dashboard_event_end_date").state == "2026-08-01"
