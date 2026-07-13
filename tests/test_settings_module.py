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
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.family_dashboard.const import DOMAIN


async def _setup_entry(hass: HomeAssistant, roster: list[dict]) -> ConfigEntry:
    entry = ConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Family Dashboard",
        data={"roster": roster, "modules": []},
        source="user",
        options={},
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

    color_state = hass.states.get("select.ada_color")
    assert color_state is not None
    assert color_state.state == "Blue"

    name_state = hass.states.get("text.ada_name")
    assert name_state is not None
    assert name_state.state == "Ada"

    assert hass.states.get("select.grace_color").state == "Green"
    assert hass.states.get("text.grace_name").state == "Grace"


async def test_changing_color_via_service_updates_state(hass: HomeAssistant):
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue"}]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.ada_color", "option": "Green"},
        blocking=True,
    )
    assert hass.states.get("select.ada_color").state == "Green"


async def test_changing_name_via_service_updates_state(hass: HomeAssistant):
    roster = [{"member_id": "ada", "name": "Ada", "color": "Blue"}]
    await _setup_entry(hass, roster)

    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.ada_name", "value": "Adalyn"},
        blocking=True,
    )
    assert hass.states.get("text.ada_name").state == "Adalyn"


# TODO: test_color_persists_across_restart using mock_restore_cache - see module docstring.
