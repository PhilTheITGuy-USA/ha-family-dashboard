"""Household-scoped `datetime` scratch entities for the Add Event popup's timed-event start/
end fields (the all-day variant uses `date.py` instead).

2026-07-26: restored this single combined Start/End `datetime` entity per side - a live
preference for v0.9.0-beta.4's compact one-row-per-side layout (native HA date+time
more-info picker, one tap to set both) over the 2026-07-25 decomposed Date+Hour+Minute+AM-PM
redesign that replaced it, which a live report called out as "far too many clicks and opens
sub windows to enter hour, days, etc". That decomposition existed on the assumption that HA's
native `datetime` picker's 12-vs-24-hour display (governed by each VIEWER's own HA account
Time Format setting) meant the same typed hour digit could mean different times to different
viewers - live-verified against HA's own frontend source (`ha-time-input`'s `_timeChanged`
handler) that this assumption was wrong: the widget always resolves to a correct, unambiguous
absolute hour before this entity ever sees it, regardless of which format was displayed (a
12-hour viewer gets an AM/PM toggle built into the SAME row; a 24-hour viewer's hour field
just accepts 0-23, no ambiguity possible). A separate explicit AM/PM select briefly lived in
`select.py` to "correct" this entity's stored value - removed the same day once that
assumption was disproven, since it only duplicated a question the native row already answers.

Not `RestoreEntity` - cleared after every submit, see `events.py`.

Forwarded once if any roster member has "calendar" enabled. 1:1 shim at the top-level
`datetime.py` (only Calendar uses this platform, unlike text/select/switch - no aggregation
needed).
"""
from __future__ import annotations

from datetime import datetime

import homeassistant.util.dt as dt_util
from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN
from .event_time import (
    EVENT_END_UNIQUE_ID,
    EVENT_START_UNIQUE_ID,
    async_recompute_end_datetime_from_start,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            _EventStartDateTime(entry, EVENT_START_UNIQUE_ID, "Event Start"),
            _EventScratchDateTime(entry, EVENT_END_UNIQUE_ID, "Event End"),
        ]
    )


class _EventScratchDateTime(DateTimeEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, unique_id_suffix: str, name: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_native_value: datetime | None = None
        # Pin explicitly rather than relying on has_entity_name + device_info to derive it -
        # see `number.py`'s `_CalendarScratchNumber` docstring comment for the live-verified
        # area-name-entity_id-prefixing gotcha this dodges; necessary here since this whole
        # module is a fresh re-creation, not a grandfathered pre-gotcha entity.
        self.entity_id = f"datetime.family_dashboard_{unique_id_suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_value(self, value: datetime | None) -> None:
        # Live-verified against the installed HA core source (`DateTimeEntity.state`):
        # it raises `ValueError` outright if `native_value` is timezone-NAIVE, but the
        # `datetime.set_value` SERVICE (what the frontend's own more-info picker calls) hands
        # us a naive value - `cv.datetime`'s own parsing never attaches one. Localizing here,
        # the moment a value is stored, is what keeps every write from crashing, and means
        # `events.py` can pass this entity's own `native_value` straight to the target
        # calendar's `async_create_event` with no further conversion needed at submit time.
        if value is not None and value.tzinfo is None:
            value = dt_util.as_local(value)
        self._attr_native_value = value
        self.async_write_ha_state()


class _EventStartDateTime(_EventScratchDateTime):
    """The Add Event popup's Start field - see `event_time.async_recompute_end_datetime_
    from_start` for what happens on every set."""

    async def async_set_value(self, value: datetime | None) -> None:
        await super().async_set_value(value)
        await async_recompute_end_datetime_from_start(self.hass, self._entry)
