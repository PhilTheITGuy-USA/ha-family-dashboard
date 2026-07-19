"""Roster birthdate `date` entities - one per family member, always provisioned.

Same shape as `text.py`'s `RosterNameText`: `RestoreEntity` local state, seeded once from
`entry.data`'s `CONF_BIRTHDATE` (the wizard's/Options Flow's initial value) and never touched
again from there - cosmetic/informational like Name/Color, nothing else filters entity setup
on it, so it doesn't go through `roster.async_update_member_fields`. `modules/calendar/
birthdays.py`'s computed Birthdays calendar entity reads this field's LIVE state (via
`hass.states.get`) each time it computes events, the same "live-templated, not baked in at
generation time" approach already used for roster colors elsewhere in this codebase.

Also registers the `set_birthdate` entity service (targeted at a specific member's own
entity, same convention as `text.py`'s `delete_member`) - the Settings tab's birthdate-edit
popup's Save button calls it instead of relying on tapping straight into this entity's stock
`date`-domain more-info dialog, which has the exact same popup-only/no-year-jump limitation
the wizard's own Birthdate step already worked around (see `util.ddmmyyyy_to_iso`'s
docstring). Reads the shared scratch text field `text.py`'s `_BirthdateScratchText` provides.

Re-exported (aggregated alongside modules/calendar/date.py) by the top-level `date.py` shim -
see that file's docstring for why aggregation (not a plain 1:1 shim) is needed here.
"""
from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from ...const import CONF_BIRTHDATE, CONF_ROSTER, DOMAIN
from ...util import InvalidBirthdateText, ddmmyyyy_to_iso
from .text import BIRTHDATE_SCRATCH_UNIQUE_ID


def birthdate_unique_id(entry: ConfigEntry, member_id: str) -> str:
    return f"{entry.entry_id}_{member_id}_birthdate"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    roster = entry.data[CONF_ROSTER]
    async_add_entities(RosterBirthdateDate(entry, member) for member in roster)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service("set_birthdate", {}, "async_set_birthdate")


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

    async def async_set_birthdate(self) -> None:
        """Reads the shared scratch text field's typed DD/MM/YYYY value (blank clears the
        birthdate, same optionality the wizard's own Birthdate step allows), converts it,
        sets THIS member's birthdate, and clears the scratch field so the next popup open
        starts fresh. Raises `HomeAssistantError` with a user-facing message on malformed
        text, matching this integration's other user-facing validation failures (e.g.
        `modules/chores/crud.py`'s deny-reason check)."""
        registry = er.async_get(self.hass)
        scratch_entity_id = registry.async_get_entity_id(
            "text", DOMAIN, f"{self._entry.entry_id}_{BIRTHDATE_SCRATCH_UNIQUE_ID}"
        )
        scratch_state = self.hass.states.get(scratch_entity_id) if scratch_entity_id else None
        raw_value = scratch_state.state if scratch_state else None
        try:
            iso_value = ddmmyyyy_to_iso(raw_value)
        except InvalidBirthdateText as err:
            raise HomeAssistantError(str(err)) from err

        self._attr_native_value = date.fromisoformat(iso_value) if iso_value else None
        self.async_write_ha_state()

        if scratch_entity_id:
            await self.hass.services.async_call(
                "text", "set_value", {"entity_id": scratch_entity_id, "value": ""}, blocking=True
            )
