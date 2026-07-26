"""Household-scoped `select` entities for Calendar:

- The Add Event popup's target-calendar picker.
- Start/End AM-PM fields - the fourth of each side's Date+Hour+Minute+AM-PM group (`date.py`/
  `number.py` own the other three) - see `event_time.py`'s docstring for why this replaced a
  single combined `datetime` entity per side. Start's own AM/PM field triggers
  `event_time.async_recompute_end_from_start` on every set, same as Start's other 3 fields.
- The Recurrence preset picker (Daily/Weekly/Monthly/Annually/Every Weekday) - read at submit
  time only when the Recurring switch (`switch.py`) is on; see `events.py` for how a preset
  becomes an RFC5545 `rrule` string.

All single, config-entry-scoped entities (not per-member) - forwarded once if any roster
member has "calendar" enabled, same as the other calendar scratch/display platforms (see
const.py's FEATURES entry for "calendar").

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

from ...const import CONF_CALENDAR_ENTITY_ID, CONF_ROSTER, DOMAIN
from .dashboard import _family_calendar_entity
from .event_time import (
    DEFAULT_AMPM,
    EVENT_END_AMPM_UNIQUE_ID,
    EVENT_RECURRENCE_UNIQUE_ID,
    EVENT_START_AMPM_UNIQUE_ID,
    RECURRENCE_DEFAULT,
    RECURRENCE_OPTIONS,
    async_recompute_end_from_start,
)
from .events import async_create_event_from_scratch_fields


def event_calendar_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.entry_id}_event_calendar"


def _pin_entity_id(entity: SelectEntity, unique_id_suffix: str) -> None:
    """See `number.py`'s `_CalendarScratchNumber` docstring comment for why this is needed -
    same area-name-entity_id-prefixing gotcha, same fix, just for the `select` domain."""
    entity.entity_id = f"select.family_dashboard_{unique_id_suffix}"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            FamilyDashboardEventCalendarSelect(hass, entry),
            _EventStartAmPmSelect(entry, EVENT_START_AMPM_UNIQUE_ID, "Event Start AM/PM"),
            _EventAmPmSelect(entry, EVENT_END_AMPM_UNIQUE_ID, "Event End AM/PM"),
            _EventRecurrenceSelect(entry),
        ]
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service("add_event", {}, "async_add_event")


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


class _EventAmPmSelect(SelectEntity):
    """One side's AM/PM field - see `event_time.py`'s docstring for the whole
    Date+Hour+Minute+AM-PM group this belongs to."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"
    _attr_options = ["AM", "PM"]
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, unique_id_suffix: str, name: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_current_option = DEFAULT_AMPM
        _pin_entity_id(self, unique_id_suffix)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()


class _EventStartAmPmSelect(_EventAmPmSelect):
    """Start's AM/PM field - see `event_time.async_recompute_end_from_start` for what happens
    on every set."""

    async def async_select_option(self, option: str) -> None:
        await super().async_select_option(option)
        await async_recompute_end_from_start(self.hass, self._entry)


class _EventRecurrenceSelect(SelectEntity):
    """Which Google-Calendar-style preset a Recurring event repeats on - only read at submit
    time if the Recurring switch (`switch.py`) is on. Not reset to its default after submit
    (unlike the Recurring switch itself) - see `events.py`'s reset block for why leaving this
    at whatever it was last set to is harmless (it's inert whenever Recurring is off)."""

    _attr_has_entity_name = True
    _attr_name = "Event Recurrence"
    _attr_icon = "mdi:repeat"
    _attr_options = RECURRENCE_OPTIONS
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{EVENT_RECURRENCE_UNIQUE_ID}"
        self._attr_current_option = RECURRENCE_DEFAULT
        _pin_entity_id(self, EVENT_RECURRENCE_UNIQUE_ID)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()
