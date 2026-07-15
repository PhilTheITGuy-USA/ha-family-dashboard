"""Tests for `holidays_setup.py` - auto-provisioning HA's built-in "Holiday" integration for
US + Philippines so the Calendar tab's Holidays overlay has something to show out of the box.
Covers: exactly one entry per country gets created when none exist; re-running is a no-op if
entries already exist (idempotent, since this runs on every entry setup/reload); a failure
driving the other integration's flow is logged and swallowed, never raised.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant

from custom_components.family_dashboard.holidays_setup import async_ensure_default_holidays


async def test_creates_one_entry_per_default_country(hass: HomeAssistant):
    await async_ensure_default_holidays(hass)
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries("holiday")
    countries = {entry.data.get("country") for entry in entries}
    assert countries == {"US", "PH"}


async def test_noop_when_entries_already_exist(hass: HomeAssistant):
    await async_ensure_default_holidays(hass)
    await hass.async_block_till_done()
    first_run_ids = {entry.entry_id for entry in hass.config_entries.async_entries("holiday")}

    await async_ensure_default_holidays(hass)
    await hass.async_block_till_done()
    second_run_ids = {entry.entry_id for entry in hass.config_entries.async_entries("holiday")}

    assert second_run_ids == first_run_ids


async def test_never_raises_if_flow_init_fails(hass: HomeAssistant):
    with patch.object(
        hass.config_entries.flow, "async_init", AsyncMock(side_effect=RuntimeError("boom"))
    ):
        await async_ensure_default_holidays(hass)  # must not raise
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries("holiday") == []
