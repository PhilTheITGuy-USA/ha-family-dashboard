"""Family Dashboard's own `calendar` platform - one `FamilyDashboardCalendarEntity` per
roster member who mapped an existing calendar entity during the wizard's `calendar` step
(see config_flow.py's `async_step_calendar`). A FULL proxy (read AND write), not just a
display wrapper: the dashboard (and any future automation) only ever needs to know this
member's stable `calendar.family_dashboard_<member>` id, never whichever real calendar type
(Google, Local, etc.) they actually mapped - the "no hardcoded external entity references"
principle this rebuild exists to fix (v1 hardcoded `calendar.PERSON_1`).

Read (`event`, `async_get_events`) and write (`async_create_event`, `async_update_event`,
`async_delete_event`) all forward to the mapped source entity via
`homeassistant.helpers.entity_component.EntityComponent.get_entity()` - NOT a service-call
round-trip. Checked directly against HA source before choosing this: there is no public
`calendar.update_event`/`calendar.delete_event` *service* (only `create_event` and
`get_events` are registered service-side; update/delete only exist as abstract
`CalendarEntity` methods the frontend's websocket calendar-edit UI calls directly) - so
`EntityComponent.get_entity()` (the same mechanism HA's own websocket handlers use
internally) is the real, stable way to reach another domain's entity object uniformly for
all five methods, not a mix of services-for-some/entity-access-for-others.

Re-exported by the top-level `calendar.py` shim (HA requires platform files at the
integration's top level - see modules/__init__.py's docstring).
"""
from __future__ import annotations

import homeassistant.components.calendar as calendar
from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import CONF_CALENDAR_ENTITY_ID, CONF_FEATURES, CONF_ROSTER, DOMAIN
from .birthdays import FamilyDashboardBirthdaysCalendar
from .reminders import async_start_reminder_engine


def member_feature_entity_ids(entry: ConfigEntry, member_id: str) -> list[tuple[str, str]]:
    """(domain, unique_id) pairs for this member's Calendar-feature entities - used by
    `roster.async_set_member_features` to hide/un-hide them in the entity registry when the
    feature is toggled off/on, without `roster.py` needing to know this module's own entity
    shape."""
    return [("calendar", f"{entry.entry_id}_{member_id}_calendar")]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entities: dict[str, FamilyDashboardCalendarEntity] = {
        member["member_id"]: FamilyDashboardCalendarEntity(entry, member)
        for member in entry.data[CONF_ROSTER]
        if member.get(CONF_CALENDAR_ENTITY_ID) and "calendar" in member.get(CONF_FEATURES, [])
    }
    # Birthdays is household-wide, not per-member - always added alongside the per-member
    # proxies whenever this platform is forwarded (i.e. whenever any member has "calendar"
    # enabled), independent of whose calendar is/isn't mapped.
    async_add_entities([*entities.values(), FamilyDashboardBirthdaysCalendar(entry)])

    domain_data = hass.data[DOMAIN][entry.entry_id]
    domain_data["calendar_entities"] = entities
    domain_data["reminder_unsub"] = async_start_reminder_engine(hass, entry, entities)


class FamilyDashboardCalendarEntity(CalendarEntity):
    """One roster member's calendar - a full proxy in front of whichever real calendar
    entity they mapped."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
    )

    def __init__(self, entry: ConfigEntry, member: dict) -> None:
        self._entry = entry
        self._member_id = member["member_id"]
        self._source_entity_id = member[CONF_CALENDAR_ENTITY_ID]
        self._attr_name = f"{member['name']} Calendar"
        self._attr_unique_id = f"{entry.entry_id}_{self._member_id}_calendar"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    def _source(self) -> CalendarEntity | None:
        component = self.hass.data.get(calendar.DATA_COMPONENT)
        if component is None:
            return None
        return component.get_entity(self._source_entity_id)

    @property
    def event(self) -> CalendarEvent | None:
        source = self._source()
        return source.event if source is not None else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date, end_date
    ) -> list[CalendarEvent]:
        source = self._source()
        if source is None:
            return []
        return await source.async_get_events(hass, start_date, end_date)

    def _require_source(self) -> CalendarEntity:
        """Reads degrade quietly to "no event"/empty list when the mapped source is gone
        (see `event`/`async_get_events` above), but a write has nowhere to go and should
        fail loudly rather than silently no-op.
        """
        source = self._source()
        if source is None:
            raise HomeAssistantError(f"Mapped calendar '{self._source_entity_id}' is not available")
        return source

    async def async_create_event(self, **kwargs) -> None:
        # The service-call dispatcher includes targeting metadata (entity_id) alongside the
        # real CalendarEvent fields (summary/start/end/description/location) in **kwargs -
        # that's routing information for finding THIS entity, not a valid field to forward
        # to the source's own async_create_event.
        kwargs.pop("entity_id", None)
        await self._require_source().async_create_event(**kwargs)

    async def async_update_event(
        self,
        uid: str,
        event: dict,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        await self._require_source().async_update_event(
            uid, event, recurrence_id, recurrence_range
        )

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        await self._require_source().async_delete_event(uid, recurrence_id, recurrence_range)
