"""Roster color and avatar `select` entities - one of each per family member, always
provisioned.

Re-exported by the top-level `select.py` shim, an AGGREGATOR (not a 1:1 shim) since Settings
(this file, always-on) and Calendar (conditional) both need the `select` platform - see that
file's docstring.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from ... import roster as roster_helpers
from ...const import (
    COLOR_OPTIONS,
    CONF_AVATAR,
    CONF_CALENDAR_ENTITY_ID,
    CONF_NOTIFY_ENTITY_ID,
    CONF_ROSTER,
    DOMAIN,
)
from .sensor import AVATARS_SENSOR_ENTITY_ID


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    roster = entry.data[CONF_ROSTER]
    async_add_entities(RosterColorSelect(entry, member) for member in roster)
    async_add_entities(RosterAvatarSelect(entry, member, hass) for member in roster)
    async_add_entities(RosterCalendarMapSelect(entry, member, hass) for member in roster)
    async_add_entities(RosterNotifyMapSelect(entry, member, hass) for member in roster)


class RosterColorSelect(SelectEntity, RestoreEntity):
    """The color assigned to one roster member. Value persists across restarts via
    RestoreEntity - the config entry's `color` is only the INITIAL value at wizard-submit
    time, not re-applied on every setup.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:palette"
    _attr_options = COLOR_OPTIONS
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member: dict) -> None:
        self._entry = entry
        self._member_id = member["member_id"]
        self._attr_name = f"{member['name']} Color"
        self._attr_unique_id = f"{entry.entry_id}_{self._member_id}_color"
        self._attr_current_option = member.get("color", COLOR_OPTIONS[0])

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


class RosterAvatarSelect(SelectEntity, RestoreEntity):
    """The avatar image path assigned to one roster member. Options normally come live from
    `sensor.family_dashboard_avatars`' `file_list` attribute (a fast, in-memory state lookup),
    not a fixed enum - dropping a new PNG into the avatars folder makes it selectable as soon
    as that sensor's own poll picks it up. Falls back to `hass.data[DOMAIN][entry_id]
    ["avatar_files"]` (computed synchronously during asset seeding, BEFORE any platform is
    forwarded - see `assets.py`/`__init__.py`) whenever the sensor has no state yet - "select"
    and "sensor" platform setup aren't guaranteed to complete in a fixed order (or even
    sequentially - they may run concurrently), so a freshly-constructed instance of this class
    can't assume the sensor's own first poll has already landed. Live-verified via a real
    (occasionally-flaking) pytest run that this is a genuine race, not a hypothetical one.

    Deliberately NOT reading the avatars folder directly (`Path.glob()`) the way an earlier
    version of this file did - live-verified against the real HA instance that doing blocking
    file I/O inside a `SelectEntity.options` property is a genuine bug, not just a lint
    nitpick: HA flagged it as a blocking call inside the event loop (a real
    `homeassistant.util.loop` warning + traceback, not assumed).

    A `SelectEntity`'s `options`/other computed properties are only actually re-read when
    THIS entity itself calls `async_write_ha_state()` - `hass.states.get(...)` returns a
    snapshot from the last such write, not a live re-evaluation. So this entity subscribes to
    the avatars sensor's state changes (`async_track_state_change_event`) and re-publishes its
    own state whenever it changes, keeping `options` in sync as avatar files are added/removed
    after startup.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:face-man-profile"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member: dict, hass: HomeAssistant) -> None:
        self._entry = entry
        self._member_id = member["member_id"]
        self._attr_name = f"{member['name']} Avatar"
        self._attr_unique_id = f"{entry.entry_id}_{self._member_id}_avatar"
        self._hass = hass
        self._attr_current_option = member.get(CONF_AVATAR) or self._default_option()
        self._avatars_unsub = None

    def _default_option(self) -> str:
        options = self.options
        return options[0] if options else ""

    @property
    def options(self) -> list[str]:
        state = self._hass.states.get(AVATARS_SENSOR_ENTITY_ID)
        if state is not None and state.attributes.get("file_list"):
            return list(state.attributes["file_list"])
        domain_data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return list(domain_data.get("avatar_files", []))

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
        if last_state is not None and last_state.state in self.options:
            self._attr_current_option = last_state.state

        self._avatars_unsub = async_track_state_change_event(
            self.hass, [AVATARS_SENSOR_ENTITY_ID], self._async_avatars_changed
        )
        # The avatars sensor may already have a real state by the time THIS entity finishes
        # setting up (or may not - platform setup order isn't guaranteed) - republish once
        # now so options reflects reality immediately rather than waiting for that sensor's
        # NEXT poll if it already ran first.
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._avatars_unsub is not None:
            self._avatars_unsub()
            self._avatars_unsub = None
        await super().async_will_remove_from_hass()

    @callback
    def _async_avatars_changed(self, _event) -> None:
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()


_UNMAPPED_OPTION = ""


class RosterCalendarMapSelect(SelectEntity):
    """Which existing `calendar.*` entity this member's own Family Dashboard calendar proxy
    (`modules/calendar/calendar.py`) forwards to - lets this be changed live from the Settings
    dashboard instead of only at initial setup/Add Member. Kiosk/parent-only (see
    `modules/settings/dashboard.py`).

    Options are the live entity_ids of every `calendar.*` entity currently on this HA instance
    (matching `RosterAvatarSelect`'s own "raw value, not a display label" options convention -
    the dashboard's own picker popup is what shows a friendlier label per option, same as the
    avatar picker shows an image rather than a raw file path), plus `_UNMAPPED_OPTION` (an
    empty-string sentinel the dashboard renders as a "None" tile, translated back to `None`
    before being persisted).

    Deliberately NOT a `RestoreEntity` - see `RosterFeatureSwitch`'s docstring for why: this
    entity's state must derive fresh from `entry.data` every time it's (re)constructed by the
    reload its own selection triggers, not from locally-persisted state.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-sync"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member: dict, hass: HomeAssistant) -> None:
        self._entry = entry
        self._member_id = member["member_id"]
        self._attr_name = f"{member['name']} Calendar Map"
        self._attr_unique_id = f"{entry.entry_id}_{self._member_id}_calendar_map"
        self._hass = hass
        self._attr_current_option = member.get(CONF_CALENDAR_ENTITY_ID) or _UNMAPPED_OPTION

    @property
    def options(self) -> list[str]:
        return [
            _UNMAPPED_OPTION,
            *sorted(state.entity_id for state in self._hass.states.async_all("calendar")),
        ]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_select_option(self, option: str) -> None:
        await roster_helpers.async_set_member_calendar(
            self.hass, self._entry, self._member_id, option or None
        )


class RosterNotifyMapSelect(SelectEntity):
    """Which existing `notify.*` entity gets this member's calendar reminders - the MANUAL
    override; see `modules/calendar/reminders.py`'s `async_resolve_member_notify_targets` for
    how this interacts with auto-resolving a linked HA user's mobile-app device live (manual,
    when set, always wins). Same shape as `RosterCalendarMapSelect` in every other respect
    (live options, `_UNMAPPED_OPTION` sentinel, no `RestoreEntity`, Kiosk/parent-only).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-ring"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member: dict, hass: HomeAssistant) -> None:
        self._entry = entry
        self._member_id = member["member_id"]
        self._attr_name = f"{member['name']} Notify Map"
        self._attr_unique_id = f"{entry.entry_id}_{self._member_id}_notify_map"
        self._hass = hass
        self._attr_current_option = member.get(CONF_NOTIFY_ENTITY_ID) or _UNMAPPED_OPTION

    @property
    def options(self) -> list[str]:
        return [
            _UNMAPPED_OPTION,
            *sorted(state.entity_id for state in self._hass.states.async_all("notify")),
        ]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_select_option(self, option: str) -> None:
        await roster_helpers.async_set_member_notify(
            self.hass, self._entry, self._member_id, option or None
        )
