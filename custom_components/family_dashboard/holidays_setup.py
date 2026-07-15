"""Auto-provisions HA's own built-in "Holiday" integration for the United States and the
Philippines, so the Calendar tab's Holidays overlay has something to show out of the box -
explicit user request ("we need to populate Holidays with pre-filled US and Philippines
Holidays each year"). The Holiday integration computes holidays live from a country code via
the `holidays` Python package (confirmed against the installed source:
`homeassistant/components/holiday/config_flow.py` uses `holidays.country_holidays`), so this
is a ONE-TIME setup action, not an ongoing sync - it self-updates every year with no
maintenance from us.

Best-effort: creating another integration's config entry is outside our own domain, so any
failure here is logged and swallowed, never allowed to block our own `async_setup_entry`.
Idempotent: checks for an existing Holiday entry for each country BEFORE starting a flow
(rather than relying solely on the Holiday integration's own `_async_abort_entries_match`),
so re-running this on every entry setup/reload never creates duplicates.
"""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

_LOGGER = logging.getLogger(__name__)

_HOLIDAY_DOMAIN = "holiday"
_DEFAULT_COUNTRIES = ("US", "PH")


async def async_ensure_default_holidays(hass: HomeAssistant) -> None:
    existing_countries = {
        entry.data.get("country") for entry in hass.config_entries.async_entries(_HOLIDAY_DOMAIN)
    }
    for country in _DEFAULT_COUNTRIES:
        if country in existing_countries:
            continue
        try:
            await _async_create_holiday_entry(hass, country)
        except Exception:  # noqa: BLE001 - never let another integration's setup block ours
            _LOGGER.warning(
                "Family Dashboard: could not auto-provision the Holiday integration for "
                "country '%s' - add it manually via Settings > Devices & Services if wanted",
                country,
                exc_info=True,
            )


async def _async_create_holiday_entry(hass: HomeAssistant, country: str) -> None:
    result = await hass.config_entries.flow.async_init(
        _HOLIDAY_DOMAIN, context={"source": "user"}, data={"country": country}
    )
    # The US (and possibly other countries) have a real province/category options schema, so
    # the flow stops at its "options" step instead of creating the entry directly - submit
    # nothing selected (nationwide public holidays only, no province filter), same default a
    # user clicking straight through the form would get.
    if result["type"] == FlowResultType.FORM:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    if result["type"] not in (FlowResultType.CREATE_ENTRY, FlowResultType.ABORT):
        _LOGGER.warning(
            "Family Dashboard: unexpected result provisioning Holiday integration for '%s': %s",
            country,
            result,
        )
