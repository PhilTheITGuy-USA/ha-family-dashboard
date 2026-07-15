"""Roster birthdate `date` entities - one per family member, always provisioned.

Same shape as `text.py`'s `RosterNameText`: `RestoreEntity` local state, seeded once from
`entry.data`'s `CONF_BIRTHDATE` (the wizard's/Options Flow's initial value) and never touched
again from there - cosmetic/informational like Name/Color, nothing else filters entity setup
on it, so it doesn't go through `roster.async_update_member_fields`. `modules/calendar/
birthdays.py`'s computed Birthdays calendar entity reads this field's LIVE state (via
`hass.states.get`) each time it computes events, the same "live-templated, not baked in at
generation time" approach already used for roster colors elsewhere in this codebase.

Re-exported (aggregated alongside modules/calendar/date.py) by the top-level `date.py` shim -
see that file's docstring for why aggregation (not a plain 1:1 shim) is needed here.
"""
from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from ...const import CONF_BIRTHDATE, CONF_ROSTER, DOMAIN


def birthdate_unique_id(entry: ConfigEntry, member_id: str) -> str:
    return f"{entry.entry_id}_{member_id}_birthdate"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    roster = entry.data[CONF_ROSTER]
    async_add_entities(RosterBirthdateDate(entry, member) for member in roster)


class RosterBirthdateDate(DateEntity, RestoreEntity):
    """One roster member's birthdate - optional (a member may have none set). Value persists
    across restarts via RestoreEntity, same as `RosterNameText`."""

    _attr_has_entity_name = True
    _attr_name = "Birthdate"
    _attr_icon = "mdi:cake-variant"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member: dict) -> None:
        self._entry = entry
        self._member_id = member["member_id"]
        self._attr_name = f"{member['name']} Birthdate"
        self._attr_unique_id = birthdate_unique_id(entry, self._member_id)
        stored = member.get(CONF_BIRTHDATE)
        self._attr_native_value = date.fromisoformat(stored) if stored else None

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
        if last_state is not None and last_state.state not in (None, "unknown", "unavailable"):
            self._attr_native_value = date.fromisoformat(last_state.state)

    async def async_set_value(self, value: date) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
