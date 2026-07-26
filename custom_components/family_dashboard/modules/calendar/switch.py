"""Household-scoped `switch` entities for Calendar: the Family calendar overlay show/hide
toggle (`RestoreEntity`-backed, same pattern as `modules/settings/switch.py`'s per-member
toggles, since it persists across restarts same as a member's own), plus the Add Event
popup's all-day flag and Recurring flag (NOT `RestoreEntity` - cleared after every submit
alongside the scratch text fields, see `events.py`). The reminder lead-time fields used to
live here too (fixed 1-week/1-day/1-hour checkboxes) - replaced 2026-07-25 by configurable
weeks/days/hours/minutes-before `number` fields, see `modules/calendar/number.py`.

Birthdays/Holidays overlay toggles ALSO used to live here (`BIRTHDAYS_SHOWN_UNIQUE_ID`/
`HOLIDAYS_SHOWN_UNIQUE_ID`) - removed 2026-07-25, a live request ("always display Holidays/
Birthdays as we currently do, but remove the button completely"). Both overlays are still
added to the calendar grid (`dashboard.py`'s `_overlay_entries`), just permanently shown now
with no backing switch at all - only Family kept its toggle.

Recurring (`EVENT_RECURRING_UNIQUE_ID`) reveals the Recurrence preset picker
(`select.py`'s `_EventRecurrenceSelect`) in the dashboard - same "switch gates a conditional
card" pattern as All Day Event already uses (a live request: "a Recurring? selector similar
to All Day Event"). See `events.py` for how the two combine into an RFC5545 `rrule`.

Forwarded once if any roster member has "calendar" enabled. Re-exported (aggregated alongside
modules/settings/switch.py) by the top-level `switch.py` shim - see that file's docstring.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from ...const import DOMAIN
from .event_time import EVENT_RECURRING_UNIQUE_ID

FAMILY_CALENDAR_SHOWN_UNIQUE_ID = "family_calendar_shown"
EVENT_ALL_DAY_UNIQUE_ID = "event_all_day"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            _OverlayShownSwitch(entry, FAMILY_CALENDAR_SHOWN_UNIQUE_ID, "Family Calendar Shown"),
            _EventScratchSwitch(entry, EVENT_ALL_DAY_UNIQUE_ID, "Event All Day"),
            _EventScratchSwitch(entry, EVENT_RECURRING_UNIQUE_ID, "Event Recurring"),
        ]
    )


class _CalendarSwitchBase(SwitchEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, unique_id_suffix: str, name: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_is_on = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()


class _OverlayShownSwitch(_CalendarSwitchBase, RestoreEntity):
    """Family calendar overlay visibility - persists across restarts, default on (matches
    every other "shown" toggle's default in this integration)."""

    _attr_icon = "mdi:eye"

    def __init__(self, entry: ConfigEntry, unique_id_suffix: str, name: str) -> None:
        super().__init__(entry, unique_id_suffix, name)
        self._attr_is_on = True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == "on"


class _EventScratchSwitch(_CalendarSwitchBase):
    """Add Event popup field - not RestoreEntity, cleared after every submit."""

    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, entry: ConfigEntry, unique_id_suffix: str, name: str) -> None:
        super().__init__(entry, unique_id_suffix, name)
        # See `number.py`'s `_CalendarScratchNumber` docstring comment for why this is
        # needed - same area-name-entity_id-prefixing gotcha, same fix, for the `switch`
        # domain. Harmless for the pre-existing "Event All Day" switch (its unique_id is
        # already registered with the correct entity_id from before this fix existed - the
        # registry lookup wins over this hint), and necessary for the new "Event Recurring"
        # switch's very first creation.
        self.entity_id = f"switch.family_dashboard_{unique_id_suffix}"
