"""Household-scoped `select` entities for Calendar - the view-granularity selector (2026-07-13
feature audit, ported from legacy `input_select.calendar_view`) and the Add Event popup's
target-calendar picker. Both are single, config-entry-scoped entities (not per-member) -
forwarded once if any roster member has "calendar" enabled, same as the other calendar
scratch/display platforms (see const.py's FEATURES entry for "calendar").

Re-exported (aggregated alongside modules/settings/select.py) by the top-level `select.py`
shim - see that file's docstring.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from ...const import (
    CALENDAR_VIEW_DEFAULT,
    CALENDAR_VIEW_OPTIONS,
    CONF_CALENDAR_ENTITY_ID,
    CONF_ROSTER,
    DOMAIN,
)
from .dashboard import _family_calendar_entity
from .events import async_create_event_from_scratch_fields


def calendar_view_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.entry_id}_calendar_view"


def event_calendar_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.entry_id}_event_calendar"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            FamilyDashboardCalendarViewSelect(entry),
            FamilyDashboardEventCalendarSelect(hass, entry),
        ]
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service("add_event", {}, "async_add_event")


class FamilyDashboardCalendarViewSelect(SelectEntity, RestoreEntity):
    """How far out the Kiosk bucket's calendar grid renders - Today/Tomorrow/Week/Biweek/
    Month. Cycled via a nav pill calling `select.select_next` (same tap-to-cycle pattern as
    the legacy dashboard), read by `modules/calendar/dashboard.py` to set week-planner-card's
    `days`/`startingDay`.
    """

    _attr_has_entity_name = True
    _attr_name = "Calendar View"
    _attr_icon = "mdi:calendar-expand-horizontal"
    _attr_options = CALENDAR_VIEW_OPTIONS
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = calendar_view_unique_id(entry)
        self._attr_current_option = CALENDAR_VIEW_DEFAULT

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in (self._attr_options or []):
            self._attr_current_option = last_state.state

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()


class FamilyDashboardEventCalendarSelect(SelectEntity, RestoreEntity):
    """Which calendar the Add Event popup targets - every calendar-mapped member's name, plus
    "Family" if a Family calendar is auto-detected (see `dashboard.py`'s
    `_family_calendar_entity`). Options are computed once at setup time (the roster's calendar
    mappings, and whether a Family calendar exists, don't change without a reconfigure/
    restart, unlike the avatar folder's live contents).
    """

    _attr_has_entity_name = True
    _attr_name = "Event Calendar"
    _attr_icon = "mdi:calendar-account"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = event_calendar_unique_id(entry)

        roster = entry.data[CONF_ROSTER]
        options = [m["name"] for m in roster if m.get(CONF_CALENDAR_ENTITY_ID)]
        if _family_calendar_entity(hass) is not None:
            options.append("Family")
        self._attr_options = options or ["Family"]
        self._attr_current_option = self._attr_options[0]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in (self._attr_options or []):
            self._attr_current_option = last_state.state

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()

    async def async_add_event(self) -> None:
        """The Add Event popup's submit action - see events.py's module docstring for the
        full field-reading/create_event/reminder-tag/reset logic this delegates to."""
        await async_create_event_from_scratch_fields(self.hass, self._entry, self.current_option)
