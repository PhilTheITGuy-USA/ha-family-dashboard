"""A single household-wide `calendar.family_dashboard_birthdays` entity, computing each
roster member's birthday as a recurring annual all-day event straight from their stored
birthdate (`modules/settings/date.py`'s `RosterBirthdateDate`) - not proxying an external
calendar source the way `calendar.py`'s `FamilyDashboardCalendarEntity` does, and not
depending on any external "Birthdays" integration (HA has no built-in one - confirmed against
the installed source). Same "compute on demand from a live source, don't store a snapshot"
shape as HA's own built-in `holiday` integration (which computes from a country code, not a
static list) - see `modules/calendar/dashboard.py`'s `_holiday_calendar_entities` for how that
one is detected and overlaid.

Read-only: `_attr_supported_features` stays at its default (0) - there's nothing sensible to
create/update/delete here, unlike the per-member proxy entity's full read/write forwarding.

Always created (independent of any per-member "calendar" feature toggle, like the Points
sensor) - if nobody has a birthdate set yet, it just yields zero events; wired into
`calendar.py`'s `async_setup_entry` alongside the per-member proxy entities.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util

from ...const import CONF_BIRTHDATE, CONF_ROSTER, DOMAIN


def birthdays_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.entry_id}_birthdays"


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _occurrence_in_year(birth_date: date, year: int) -> date:
    """This birth_date's anniversary date in `year` - Feb 29 falls back to Feb 28 in a
    non-leap year rather than raising, since a birthday must occur every year regardless."""
    month, day = birth_date.month, birth_date.day
    if month == 2 and day == 29 and not _is_leap_year(year):
        day = 28
    return date(year, month, day)


def birthday_occurrences_in_range(
    members: list[tuple[str, date]], start_date: date, end_date: date
) -> list[CalendarEvent]:
    """One all-day `CalendarEvent` per (name, birth_date) pair whose anniversary falls within
    `[start_date, end_date)` - checks every year the window spans, not just `start_date.year`,
    since a multi-week/month window can cross a year boundary (e.g. Dec 20 - Jan 10). Pure
    function, no `hass`/entity involved, so it's directly unit-testable.
    """
    events: list[CalendarEvent] = []
    for name, birth_date in members:
        for year in range(start_date.year, end_date.year + 1):
            occurrence = _occurrence_in_year(birth_date, year)
            if start_date <= occurrence < end_date:
                age = year - birth_date.year
                events.append(
                    CalendarEvent(
                        start=occurrence,
                        end=occurrence,
                        summary=f"{name}'s Birthday (turns {age})",
                    )
                )
    events.sort(key=lambda e: e.start)
    return events


class FamilyDashboardBirthdaysCalendar(CalendarEntity):
    """Single per-config-entry entity - see module docstring."""

    _attr_has_entity_name = True
    _attr_name = "Birthdays"
    _attr_icon = "mdi:cake-variant"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = birthdays_unique_id(entry)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    def _live_member_birthdates(self, hass: HomeAssistant) -> list[tuple[str, date]]:
        """Resolves each roster member's birthdate from their OWN live `date.*_birthdate`
        entity state (not a snapshot baked in at add-time or from `entry.data`) - same
        "live-templated, not baked in at generation time" philosophy already used for roster
        colors elsewhere in this integration, so an edit via the Settings dashboard is
        reflected immediately without waiting for a reload."""
        members: list[tuple[str, date]] = []
        for member in self._entry.data.get(CONF_ROSTER, []):
            entity_id = f"date.family_dashboard_{member['member_id']}_birthdate"
            state = hass.states.get(entity_id)
            if state is None or state.state in (None, "unknown", "unavailable"):
                continue
            members.append((member["name"], date.fromisoformat(state.state)))
        return members

    @property
    def event(self) -> CalendarEvent | None:
        if self.hass is None:
            return None
        today = dt_util.now().date()
        upcoming = birthday_occurrences_in_range(
            self._live_member_birthdates(self.hass), today, today + timedelta(days=730)
        )
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return birthday_occurrences_in_range(
            self._live_member_birthdates(hass), start_date.date(), end_date.date()
        )
