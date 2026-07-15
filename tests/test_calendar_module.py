"""Tests for the Calendar module - Family Dashboard's own `calendar` platform. Covers:
entities are created only for roster members with a mapped calendar_entity_id; the proxy's
`event`/`async_get_events` correctly reflect the mapped source; write operations
(create/update/delete) issued against the PROXY entity actually mutate the fake SOURCE entity
(not some local copy) - the clearest proof the proxy is real, not decorative; the reminder
engine fires `notify.send_message` for a tagged event whose lead time falls in the current
tick and not for one outside it, and fires multiple independent reminders for multiple tags
on one event; a member with "calendar" but no mapped entity gets zero calendar entities.
"""
from __future__ import annotations

import dataclasses
from datetime import timedelta

import freezegun
import homeassistant.components.calendar as calendar
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
    setup_test_component_platform,
)

from custom_components.family_dashboard.const import DOMAIN
from custom_components.family_dashboard.modules.calendar.reminders import (
    _async_check_reminders,
)


class FakeSourceCalendar(CalendarEntity):
    """A minimal, real (not mocked) CalendarEntity used as the "existing calendar" a roster
    member maps to - in-memory storage, real create/update/delete/get_events behavior, so
    forwarding is tested against actual CalendarEntity contract behavior."""

    _attr_name = "Fake Source"
    _attr_unique_id = "fake_source"
    _attr_should_poll = False

    def __init__(self) -> None:
        self._events: list[CalendarEvent] = []
        self._next_uid = 1

    @property
    def event(self) -> CalendarEvent | None:
        upcoming = sorted(self._events, key=lambda e: e.start_datetime_local)
        return upcoming[0] if upcoming else None

    async def async_get_events(self, hass, start_date, end_date) -> list[CalendarEvent]:
        return [
            e
            for e in self._events
            if e.start_datetime_local < end_date and e.end_datetime_local > start_date
        ]

    async def async_create_event(self, **kwargs) -> None:
        # The real async_create_event contract (confirmed against HA source: EVENT_START/
        # EVENT_END constants) uses dtstart/dtend, NOT the CalendarEvent dataclass's own
        # start/end field names - every real implementation (local_calendar, Google, etc.)
        # has to translate, same as this fake does, when called directly (e.g. also used
        # here to seed events in async_create_event(start=..., end=...) test helper calls -
        # so accept either shape).
        start = kwargs.pop("dtstart", kwargs.pop("start", None))
        end = kwargs.pop("dtend", kwargs.pop("end", None))
        kwargs.setdefault("uid", f"fake-{self._next_uid}")
        self._next_uid += 1
        self._events.append(CalendarEvent(start=start, end=end, **kwargs))

    async def async_update_event(
        self, uid, event: dict, recurrence_id=None, recurrence_range=None
    ) -> None:
        for idx, existing in enumerate(self._events):
            if existing.uid == uid:
                merged = {**dataclasses.asdict(existing), **event}
                self._events[idx] = CalendarEvent(**merged)
                return

    async def async_delete_event(self, uid, recurrence_id=None, recurrence_range=None) -> None:
        self._events = [e for e in self._events if e.uid != uid]


async def _setup_fake_source_calendar(hass: HomeAssistant) -> FakeSourceCalendar:
    fake = FakeSourceCalendar()
    setup_test_component_platform(hass, "calendar", [fake])
    assert await async_setup_component(hass, "calendar", {"calendar": [{"platform": "test"}]})
    await hass.async_block_till_done()
    return fake


def _member(name, member_id, calendar_entity_id=None, notify_entity_id=None):
    return {
        "member_id": member_id,
        "name": name,
        "color": "Blue",
        "features": ["calendar"],
        "ha_user_id": None,
        "calendar_entity_id": calendar_entity_id,
        "notify_entity_id": notify_entity_id,
        "list_presets": [],
    }


async def _setup_entry(hass: HomeAssistant, roster: list[dict]) -> MockConfigEntry:
    entry = MockConfigEntry(
        version=1, domain=DOMAIN, title="Family Dashboard", data={"roster": roster},
        source="user", unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entity_created_only_for_mapped_members(hass: HomeAssistant):
    await _setup_fake_source_calendar(hass)
    roster = [
        _member("Ada", "ada", calendar_entity_id="calendar.fake_source"),
        _member("Grace", "grace"),  # opted into "calendar", nothing mapped
    ]
    await _setup_entry(hass, roster)

    assert hass.states.get("calendar.family_dashboard_ada_calendar") is not None
    assert hass.states.get("calendar.family_dashboard_grace_calendar") is None


async def test_proxy_reads_reflect_source(hass: HomeAssistant):
    fake = await _setup_fake_source_calendar(hass)
    now = dt_util.now()
    await fake.async_create_event(
        summary="Dentist", start=now + timedelta(hours=1), end=now + timedelta(hours=2)
    )
    roster = [_member("Ada", "ada", calendar_entity_id="calendar.fake_source")]
    await _setup_entry(hass, roster)

    state = hass.states.get("calendar.family_dashboard_ada_calendar")
    assert state is not None
    assert state.attributes["message"] == "Dentist"


async def test_write_via_proxy_mutates_source(hass: HomeAssistant):
    fake = await _setup_fake_source_calendar(hass)
    roster = [_member("Ada", "ada", calendar_entity_id="calendar.fake_source")]
    await _setup_entry(hass, roster)

    now = dt_util.now()
    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": "calendar.family_dashboard_ada_calendar",
            "summary": "Soccer practice",
            "start_date_time": (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            "end_date_time": (now + timedelta(days=1, hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    # The event landed on the FAKE SOURCE, not some local copy the proxy invented.
    assert len(fake._events) == 1
    assert fake._events[0].summary == "Soccer practice"

    # Update and delete, called directly on the proxy entity (no public HA service exists
    # for these - see calendar.py's module docstring) - forwarded the same way.
    proxy = hass.data[calendar.DATA_COMPONENT].get_entity("calendar.family_dashboard_ada_calendar")
    uid = fake._events[0].uid
    await proxy.async_update_event(uid, {"summary": "Soccer practice (rescheduled)"})
    assert fake._events[0].summary == "Soccer practice (rescheduled)"

    await proxy.async_delete_event(uid)
    assert fake._events == []


async def test_member_without_mapped_calendar_has_no_entity_no_crash(hass: HomeAssistant):
    roster = [_member("Bob", "bob")]  # "calendar" feature, nothing mapped
    await _setup_entry(hass, roster)
    assert hass.states.get("calendar.family_dashboard_bob_calendar") is None


async def test_mapped_calendar_but_feature_disabled_gets_no_entity(hass: HomeAssistant):
    """Regression: the entity-creation filter used to check ONLY calendar_entity_id, never
    whether "calendar" was still in the member's own features - so disabling the feature via
    a live toggle (leaving the mapping intact so re-enabling restores it) used to have no
    effect at all on this proxy entity."""
    await _setup_fake_source_calendar(hass)
    roster = [
        {
            "member_id": "ada",
            "name": "Ada",
            "color": "Blue",
            "features": [],  # calendar mapped below, but NOT selected
            "ha_user_id": None,
            "calendar_entity_id": "calendar.fake_source",
            "notify_entity_id": None,
            "list_presets": [],
        }
    ]
    await _setup_entry(hass, roster)
    assert hass.states.get("calendar.family_dashboard_ada_calendar") is None


async def test_reminder_fires_within_tick_window(hass: HomeAssistant):
    fake = await _setup_fake_source_calendar(hass)
    calls = async_mock_service(hass, "notify", "send_message")

    now = dt_util.now()
    event_start = now + timedelta(minutes=30)
    await fake.async_create_event(
        summary="Piano lesson",
        start=event_start,
        end=event_start + timedelta(hours=1),
        description="[[reminder:30m]]",
    )
    roster = [
        _member(
            "Ada", "ada", calendar_entity_id="calendar.fake_source", notify_entity_id="notify.adas_phone"
        )
    ]
    entry = await _setup_entry(hass, roster)

    calendar_entities = hass.data[DOMAIN][entry.entry_id]["calendar_entities"]
    with freezegun.freeze_time(now):
        await _async_check_reminders(hass, roster, calendar_entities)
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["notify.adas_phone"]
    assert "Piano lesson" in calls[0].data["title"]


async def test_reminder_does_not_fire_outside_tick_window(hass: HomeAssistant):
    fake = await _setup_fake_source_calendar(hass)
    calls = async_mock_service(hass, "notify", "send_message")

    now = dt_util.now()
    event_start = now + timedelta(hours=5)  # reminder would fire hours from now, not this tick
    await fake.async_create_event(
        summary="Dentist",
        start=event_start,
        end=event_start + timedelta(hours=1),
        description="[[reminder:30m]]",
    )
    roster = [
        _member(
            "Ada", "ada", calendar_entity_id="calendar.fake_source", notify_entity_id="notify.adas_phone"
        )
    ]
    entry = await _setup_entry(hass, roster)

    calendar_entities = hass.data[DOMAIN][entry.entry_id]["calendar_entities"]
    with freezegun.freeze_time(now):
        await _async_check_reminders(hass, roster, calendar_entities)
    await hass.async_block_till_done()

    assert len(calls) == 0


async def test_disabled_member_reminders_do_not_fire_even_though_mapping_is_intact(
    hass: HomeAssistant,
):
    """Disable (roster.py's async_set_member_disabled) means "keep everything, just don't
    show it or action calendar reminders" - the member's calendar mapping/entity stays fully
    intact (still resolvable via calendar_entities), only the reminder engine's own per-tick
    scan skips them."""
    fake = await _setup_fake_source_calendar(hass)
    calls = async_mock_service(hass, "notify", "send_message")

    now = dt_util.now()
    event_start = now + timedelta(minutes=30)
    await fake.async_create_event(
        summary="Piano lesson",
        start=event_start,
        end=event_start + timedelta(hours=1),
        description="[[reminder:30m]]",
    )
    roster = [
        {
            **_member(
                "Ada", "ada", calendar_entity_id="calendar.fake_source", notify_entity_id="notify.adas_phone"
            ),
            "disabled": True,
        }
    ]
    entry = await _setup_entry(hass, roster)

    # Mapping/entity still fully intact despite being disabled.
    calendar_entities = hass.data[DOMAIN][entry.entry_id]["calendar_entities"]
    assert "ada" in calendar_entities

    with freezegun.freeze_time(now):
        await _async_check_reminders(hass, roster, calendar_entities)
    await hass.async_block_till_done()

    assert len(calls) == 0


async def test_multiple_reminders_on_one_event_fire_independently(hass: HomeAssistant):
    fake = await _setup_fake_source_calendar(hass)
    calls = async_mock_service(hass, "notify", "send_message")

    now = dt_util.now()
    # One reminder due right now (30m lead, event in 30 min), one NOT due (1d lead).
    event_start = now + timedelta(minutes=30)
    await fake.async_create_event(
        summary="Recital",
        start=event_start,
        end=event_start + timedelta(hours=1),
        description="[[reminder:30m]] [[reminder:1d]]",
    )
    roster = [
        _member(
            "Ada", "ada", calendar_entity_id="calendar.fake_source", notify_entity_id="notify.adas_phone"
        )
    ]
    entry = await _setup_entry(hass, roster)

    calendar_entities = hass.data[DOMAIN][entry.entry_id]["calendar_entities"]
    with freezegun.freeze_time(now):
        await _async_check_reminders(hass, roster, calendar_entities)
    await hass.async_block_till_done()

    # Only the 30m-lead reminder is due in this tick; the 1d-lead one isn't yet.
    assert len(calls) == 1
