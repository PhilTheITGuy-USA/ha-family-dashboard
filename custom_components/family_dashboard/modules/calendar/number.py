"""Household-scoped `number` entities for Calendar:

- Reminder lead-time fields: how many weeks/days/hours/minutes before an event to notify.
  Replaces the earlier fixed 1-week/1-day/1-hour checkboxes (`modules/calendar/switch.py`,
  removed 2026-07-25) with a live-requested "let me choose X weeks/days/hours/minutes before,
  not just a static 1" - each field is independent and 0 means "no reminder at this
  granularity", same "multiple independent reminders per event" semantics `reminders.py`'s
  `[[reminder:...]]` tag already supports (see `events.py`'s tag-building for how these four
  values become 1-3 tags).
- Start/End Hour fields (1-12) and Minute fields - two of the four fields in each side's
  Date+Hour+Minute+AM-PM group (`select.py` owns the AM/PM half) - see `event_time.py`'s
  docstring for why this replaced a single combined `datetime` entity per side. Start's own
  Hour/Minute fields trigger `event_time.async_recompute_end_from_start` on every set, same as
  Start's Date field (`date.py`) and AM/PM field (`select.py`).

Not `RestoreEntity` - cleared (reset to their defaults) after every submit alongside the
other scratch fields, see `events.py`.

Forwarded once if any roster member has "calendar" enabled. Aggregated (alongside
`modules/chores/number.py`) by the top-level `number.py` shim - see that file's docstring.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN
from .event_time import (
    DEFAULT_END_HOUR,
    DEFAULT_MINUTE,
    DEFAULT_START_HOUR,
    EVENT_END_HOUR_UNIQUE_ID,
    EVENT_END_MINUTE_UNIQUE_ID,
    EVENT_START_HOUR_UNIQUE_ID,
    EVENT_START_MINUTE_UNIQUE_ID,
    async_recompute_end_from_start,
)

EVENT_REMIND_WEEKS_UNIQUE_ID = "event_remind_weeks_before"
EVENT_REMIND_DAYS_UNIQUE_ID = "event_remind_days_before"
EVENT_REMIND_HOURS_UNIQUE_ID = "event_remind_hours_before"
EVENT_REMIND_MINUTES_UNIQUE_ID = "event_remind_minutes_before"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            _CalendarScratchNumber(
                entry, EVENT_REMIND_WEEKS_UNIQUE_ID, "Event Remind Weeks Before", 0, 8, 0,
                icon="mdi:bell-ring-outline",
            ),
            _CalendarScratchNumber(
                entry, EVENT_REMIND_DAYS_UNIQUE_ID, "Event Remind Days Before", 0, 31, 0,
                icon="mdi:bell-ring-outline",
            ),
            _CalendarScratchNumber(
                entry, EVENT_REMIND_HOURS_UNIQUE_ID, "Event Remind Hours Before", 0, 23, 0,
                icon="mdi:bell-ring-outline",
            ),
            _CalendarScratchNumber(
                entry, EVENT_REMIND_MINUTES_UNIQUE_ID, "Event Remind Minutes Before", 0, 59, 0,
                icon="mdi:bell-ring-outline",
            ),
            _EventStartTimeNumber(
                entry, EVENT_START_HOUR_UNIQUE_ID, "Event Start Hour", 1, 12, DEFAULT_START_HOUR,
            ),
            _EventStartTimeNumber(
                entry, EVENT_START_MINUTE_UNIQUE_ID, "Event Start Minute", 0, 59, DEFAULT_MINUTE,
            ),
            _CalendarScratchNumber(
                entry, EVENT_END_HOUR_UNIQUE_ID, "Event End Hour", 1, 12, DEFAULT_END_HOUR,
                icon="mdi:calendar-clock",
            ),
            _CalendarScratchNumber(
                entry, EVENT_END_MINUTE_UNIQUE_ID, "Event End Minute", 0, 59, DEFAULT_MINUTE,
                icon="mdi:calendar-clock",
            ),
        ]
    )


class _CalendarScratchNumber(NumberEntity):
    """Generic Add Event popup scratch number field, reset to its own default after submit.
    Whole numbers only - live-reported: "1.2 days" or "1.5 hours" is meaningless for a
    reminder lead time or a clock hour/minute. `_attr_native_step = 1` alone only constrains
    the frontend's spinner/HTML5 step validation, which doesn't reliably block manual keyboard
    entry (especially a kiosk's on-screen numeric keypad) - `async_set_native_value` rounds
    explicitly so a fractional value can never actually get stored, regardless of how it was
    typed in."""

    _attr_has_entity_name = True
    _attr_step = 1
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        unique_id_suffix: str,
        name: str,
        min_value: int,
        max_value: int,
        default: int,
        icon: str = "mdi:calendar-clock",
    ) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_value = default
        # Pin the entity_id explicitly rather than letting HA derive it from has_entity_name +
        # device_info - live-verified against HA's own entity_registry source
        # (_async_get_full_entity_name): if the shared "Family Dashboard" device has already
        # been assigned to an AREA (a normal thing to do for a kiosk device) by the time a
        # brand-new entity is first registered, HA prefixes its suggested object_id with the
        # AREA name too (e.g. "living_room_family_dashboard_..."), not just the device name -
        # every OTHER entity in this integration dodged this only by luck of having been
        # created before any area was ever assigned. Setting entity_id directly here (an
        # HA-supported mechanism - see entity_platform.py's own "an entity may suggest the
        # entity_id by setting entity_id itself") keeps it exactly matching what
        # dashboard.py's Add Event popup card hardcodes, on every install.
        self.entity_id = f"number.family_dashboard_{unique_id_suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = round(value)
        self.async_write_ha_state()


class _EventStartTimeNumber(_CalendarScratchNumber):
    """Start's Hour or Minute field - see `event_time.async_recompute_end_from_start` for what
    happens on every set."""

    async def async_set_native_value(self, value: float) -> None:
        await super().async_set_native_value(value)
        await async_recompute_end_from_start(self.hass, self._entry)
