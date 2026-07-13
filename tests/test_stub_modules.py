"""Enabling a not-yet-implemented module (Calendar/Lists/Chores & Rewards) must not crash
setup - it should just add zero entities, per each stub platform file's design (see
modules/calendar, modules/lists, modules/chores). This test exists so the scaffold stays
runnable/testable while those modules are being built out one at a time.

Replace/extend these with real per-module tests as each module gets implemented for real -
these are a placeholder floor, not final coverage. Each module should eventually get its own
test file (test_calendar_module.py, test_lists_module.py, test_chores_module.py) following
test_settings_module.py's pattern once it has real entities to test.
"""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.family_dashboard.const import DOMAIN


async def test_all_stub_modules_enabled_does_not_crash(hass: HomeAssistant):
    entry = ConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Family Dashboard",
        data={
            "roster": [{"member_id": "ada", "name": "Ada", "color": "Blue"}],
            "modules": ["calendar", "lists", "chores"],
        },
        source="user",
        options={},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Settings entities still exist even with every stub module enabled.
    assert hass.states.get("select.ada_color") is not None
    assert hass.states.get("text.ada_name") is not None

    # Stub modules add nothing yet - this will need updating as each becomes real.
    assert hass.states.get("calendar.ada") is None
    assert hass.states.get("todo.to_do") is None
