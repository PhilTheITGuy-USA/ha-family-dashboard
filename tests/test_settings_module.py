"""Tests for the Settings/Roster module - the reference implementation for "own entity
platform, no YAML." Covers: entities are created with the right initial values, and that
calling the select/text services actually changes state (proving these are real, live,
user-editable entities - not static YAML).

NOT covered here yet, flagged rather than faked: persistence ACROSS A RESTART via
RestoreEntity. That needs `pytest_homeassistant_custom_component.common.mock_restore_cache`
(or the equivalent in whatever version gets installed) to seed a prior state before the
entity is added - worth adding once this scaffold is picked up, but the exact import path
wasn't verified against a real install in this session, so it's noted as a TODO instead of
guessed at.
"""
import pytest

import homeassistant.components.select as select_component
from homeassistant.components.calendar import CalendarEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, setup_test_component_platform

from custom_components.family_dashboard.const import DOMAIN


class _FakeCalendar(CalendarEntity):
    """A minimal real (not mocked) CalendarEntity, same "real entity, not a fixture double"
    convention as test_calendar_module.py's own FakeSourceCalendar - needed here because the
    stock `select.select_option` SERVICE validates the option against the entity's own live
    `options` list before dispatching, so `RosterCalendarMapSelect`'s live-from-`calendar.*`
    options can't be satisfied by a plain string that isn't a real, registered entity."""

    _attr_name = "Some Source"
    _attr_unique_id = "some_source"
    _attr_should_poll = False

    @property
    def event(self):
        return None


async def _setup_fake_calendar(hass: HomeAssistant) -> None:
    setup_test_component_platform(hass, "calendar", [_FakeCalendar()])
    assert await async_setup_component(hass, "calendar", {"calendar": [{"platform": "test"}]})
    await hass.async_block_till_done()


def _is_gone(hass: HomeAssistant, entity_id: str) -> bool:
    """A hidden-but-still-registered entity isn't necessarily `None` in `hass.states` - HA's
    own restore-state machinery leaves a synthetic `unavailable, restored=True` placeholder
    for any entity that was previously added and still has a registry entry (exactly the
    "hidden, not deleted" behavior wanted). Absent entirely (never created) is `None`;
    hidden-after-having-existed is this placeholder - both count as "not currently live"."""
    state = hass.states.get(entity_id)
    return state is None or state.state == "unavailable"


async def _setup_entry(hass: HomeAssistant, roster: list[dict]) -> ConfigEntry:
    # MockConfigEntry (not a raw ConfigEntry()) - HA's ConfigEntry constructor gains new
    # required kwargs across releases; MockConfigEntry is the version-tolerant test helper.
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


async def test_roster_entities_created_with_initial_values(hass: HomeAssistant):
    roster = [
        {"member_id": "ada", "name": "Ada", "color": "Blue"},
        {"member_id": "grace", "name": "Grace", "color": "Green"},
    ]
    await _setup_entry(hass, roster)

    # has_entity_name=True + a shared "Family Dashboard" device means entity_id is
    # generated as <device>_<entity name>, not the bare member-only slug.
    color_state = hass.states.get("select.family_dashboard_ada_color")
    assert color_state is not None
    assert color_state.state == "Blue"

    name_state = hass.states.get("text.family_dashboard_ada_name")
    assert name_state is not None
    assert name_state.state == "Ada"

    assert hass.states.get("select.family_dashboard_grace_color").state == "Green"
    assert hass.states.get("text.family_dashboard_grace_name").state == "Grace"

    # The Kiosk bucket's toggle-filter pills (Calendar/Chores tabs) are backed by a switch
    # per member, always provisioned like color/name, defaulting on.
    assert hass.states.get("switch.family_dashboard_ada_shown").state == "on"
    assert hass.states.get("switch.family_dashboard_grace_shown").state == "on"


async def test_toggling_shown_switch_updates_state(hass: HomeAssistant):
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue"}]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.family_dashboard_ada_shown"},
        blocking=True,
    )
    assert hass.states.get("switch.family_dashboard_ada_shown").state == "off"

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.family_dashboard_ada_shown"},
        blocking=True,
    )
    assert hass.states.get("switch.family_dashboard_ada_shown").state == "on"


async def test_changing_color_via_service_updates_state(hass: HomeAssistant):
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue"}]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.family_dashboard_ada_color", "option": "Green"},
        blocking=True,
    )
    assert hass.states.get("select.family_dashboard_ada_color").state == "Green"


async def test_changing_name_via_service_updates_state(hass: HomeAssistant):
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue"}]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.family_dashboard_ada_name", "value": "Adalyn"},
        blocking=True,
    )
    assert hass.states.get("text.family_dashboard_ada_name").state == "Adalyn"


async def test_birthdate_entity_created_with_initial_value(hass: HomeAssistant):
    roster = [
        {"member_id": "ada", "name": "Ada", "color": "Blue", "birthdate": "2015-06-21"},
        {"member_id": "grace", "name": "Grace", "color": "Green"},  # no birthdate set
    ]
    await _setup_entry(hass, roster)

    assert hass.states.get("date.family_dashboard_ada_birthdate").state == "2015-06-21"
    assert hass.states.get("date.family_dashboard_grace_birthdate").state == "unknown"


async def test_changing_birthdate_via_service_updates_state_and_persists_through_reload(
    hass: HomeAssistant,
):
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue"}]
    entry = await _setup_entry(hass, roster)

    await hass.services.async_call(
        "date",
        "set_value",
        {"entity_id": "date.family_dashboard_ada_birthdate", "date": "2012-01-05"},
        blocking=True,
    )
    assert hass.states.get("date.family_dashboard_ada_birthdate").state == "2012-01-05"

    # RestoreEntity - reloading the entry (not just restarting) still restores the edited
    # value, same as Name/Color, since it's never re-seeded from entry.data after creation.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("date.family_dashboard_ada_birthdate").state == "2012-01-05"


async def test_set_birthdate_service_reads_scratch_field_and_clears_it(hass: HomeAssistant):
    """The Settings tab's birthdate-edit popup doesn't use the native `date.set_value`
    service directly (its stock more-info dialog has the same popup-only/no-year-jump picker
    the wizard's Birthdate step already worked around) - it types DD/MM/YYYY into a shared
    scratch text field and calls `family_dashboard.set_birthdate`, targeted at the specific
    member's own birthdate entity, which reads/converts/commits the scratch value and clears
    it afterward."""
    roster = [
        {"member_id": "ada", "name": "Ada", "color": "Blue"},
        {"member_id": "grace", "name": "Grace", "color": "Green"},
    ]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.family_dashboard_birthdate_entry", "value": "21/06/2015"},
        blocking=True,
    )
    await hass.services.async_call(
        "family_dashboard",
        "set_birthdate",
        {"entity_id": "date.family_dashboard_ada_birthdate"},
        blocking=True,
    )

    assert hass.states.get("date.family_dashboard_ada_birthdate").state == "2015-06-21"
    # Untouched sibling and cleared scratch field.
    assert hass.states.get("date.family_dashboard_grace_birthdate").state == "unknown"
    assert hass.states.get("text.family_dashboard_birthdate_entry").state == ""


async def test_set_birthdate_service_rejects_invalid_text(hass: HomeAssistant):
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue"}]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.family_dashboard_birthdate_entry", "value": "not-a-date"},
        blocking=True,
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "family_dashboard",
            "set_birthdate",
            {"entity_id": "date.family_dashboard_ada_birthdate"},
            blocking=True,
        )
    # Unchanged on failure - no partial/garbage write.
    assert hass.states.get("date.family_dashboard_ada_birthdate").state == "unknown"


async def test_feature_switches_created_with_initial_state_from_entry_data(hass: HomeAssistant):
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue", "features": ["lists"]}]
    await _setup_entry(hass, roster)

    assert hass.states.get("switch.family_dashboard_ada_lists_enabled").state == "on"
    assert hass.states.get("switch.family_dashboard_ada_calendar_enabled").state == "off"
    assert hass.states.get("switch.family_dashboard_ada_chores_rewards_enabled").state == "off"


async def test_toggling_feature_switch_persists_and_creates_entities(hass: HomeAssistant):
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue", "features": []}]
    entry = await _setup_entry(hass, roster)

    assert hass.states.get("sensor.family_dashboard_ada_points") is None

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.family_dashboard_ada_chores_rewards_enabled"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert "chores" in entry.data["roster"][0]["features"]
    assert hass.states.get("sensor.family_dashboard_ada_points") is not None
    # The switch itself survives its own triggered reload with the new state.
    assert hass.states.get("switch.family_dashboard_ada_chores_rewards_enabled").state == "on"

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.family_dashboard_ada_chores_rewards_enabled"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert "chores" not in entry.data["roster"][0]["features"]
    assert _is_gone(hass, "sensor.family_dashboard_ada_points")
    assert hass.states.get("switch.family_dashboard_ada_chores_rewards_enabled").state == "off"


async def test_enabled_switch_initial_state_matches_entry_data(hass: HomeAssistant):
    roster = [
        {"member_id": "ada", "name": "Ada", "color": "Blue", "features": []},
        {"member_id": "grace", "name": "Grace", "color": "Green", "features": [], "disabled": True},
    ]
    await _setup_entry(hass, roster)

    assert hass.states.get("switch.family_dashboard_ada_enabled").state == "on"
    assert hass.states.get("switch.family_dashboard_grace_enabled").state == "off"


async def test_disabling_via_enabled_switch_hides_settings_entities_and_persists(hass: HomeAssistant):
    """Disable never touches `CONF_FEATURES`, so unlike a per-feature toggle, every entity is
    still recreated live on each reload regardless - `hidden_by` here is a real registry flag
    (checked directly), but `hass.states` stays fully available throughout (it's cosmetic,
    not the actual "don't show on the dashboard" mechanism - see roster.py's docstring)."""
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue", "features": []}]
    entry = await _setup_entry(hass, roster)

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.family_dashboard_ada_enabled"}, blocking=True
    )
    await hass.async_block_till_done()

    assert entry.data["roster"][0]["disabled"] is True
    registry = er.async_get(hass)
    assert registry.entities["select.family_dashboard_ada_color"].hidden_by == er.RegistryEntryHider.INTEGRATION
    assert hass.states.get("select.family_dashboard_ada_color") is not None
    # The switch itself always survives its own triggered reload, visible.
    assert hass.states.get("switch.family_dashboard_ada_enabled").state == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.family_dashboard_ada_enabled"}, blocking=True
    )
    await hass.async_block_till_done()

    assert entry.data["roster"][0]["disabled"] is False
    assert hass.states.get("select.family_dashboard_ada_color") is not None


async def test_delete_member_service_genuinely_removes_entities(hass: HomeAssistant):
    roster = [
        {"member_id": "ada", "name": "Ada", "color": "Blue", "features": []},
        {"member_id": "grace", "name": "Grace", "color": "Green", "features": []},
    ]
    entry = await _setup_entry(hass, roster)

    await hass.services.async_call(
        "family_dashboard",
        "delete_member",
        {"entity_id": "text.family_dashboard_ada_name"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("text.family_dashboard_ada_name") is None
    assert {m["member_id"] for m in entry.data["roster"]} == {"grace"}
    # Grace's own entities are untouched.
    assert hass.states.get("text.family_dashboard_grace_name") is not None


async def test_calendar_map_select_options_and_selection(hass: HomeAssistant):
    await _setup_fake_calendar(hass)
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue", "features": ["calendar"]}]
    entry = await _setup_entry(hass, roster)

    state = hass.states.get("select.family_dashboard_ada_calendar_map")
    assert state is not None
    assert state.state == ""  # unmapped by default

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.family_dashboard_ada_calendar_map", "option": "calendar.some_source"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert entry.data["roster"][0]["calendar_entity_id"] == "calendar.some_source"
    assert hass.states.get("calendar.family_dashboard_ada_calendar") is not None

    # Selecting the synthetic "" option unmaps it again.
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.family_dashboard_ada_calendar_map", "option": ""},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert entry.data["roster"][0]["calendar_entity_id"] is None
    assert _is_gone(hass, "calendar.family_dashboard_ada_calendar")


async def test_notify_map_select_updates_entry_data(hass: HomeAssistant):
    """Unlike the calendar-map test above, this calls `async_select_option` directly on the
    entity rather than through the stock `select.select_option` SERVICE - that service
    validates the option against the entity's live `options` list first, which would require
    faking an entire `notify` platform. HA's `notify` domain still only supports the legacy
    global `get_service` platform contract for test mocking (confirmed live: `setup_test_
    component_platform` + `async_setup_component` raises "Invalid notify platform" - `notify`
    doesn't support the modern entity-platform mock the calendar test above uses), so a real
    live `notify.*` entity isn't practical to stand up here. `test_roster.py`'s own
    `test_set_member_notify_updates_entry_data` already covers the underlying persistence
    directly; this test's job is just proving the ENTITY wires up to that same helper."""
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue"}]
    entry = await _setup_entry(hass, roster)

    assert hass.states.get("select.family_dashboard_ada_notify_map").state == ""

    entity = hass.data[select_component.DATA_COMPONENT].get_entity(
        "select.family_dashboard_ada_notify_map"
    )
    await entity.async_select_option("notify.adas_phone")
    await hass.async_block_till_done()

    assert entry.data["roster"][0]["notify_entity_id"] == "notify.adas_phone"


# TODO: test_color_persists_across_restart using mock_restore_cache - see module docstring.
