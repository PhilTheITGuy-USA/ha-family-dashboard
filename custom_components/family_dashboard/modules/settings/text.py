"""Roster display-name `text` entities - one per family member, always provisioned.

Also registers the `delete_member` entity service on `RosterNameText` (every member always
has exactly one, guaranteed to exist - same reasoning `family_dashboard.delete_task` is
registered on the chores task sensor) - the Settings dashboard's "Remove Member" Delete tile
targets it, permanently removing the member (see `roster.py`'s `async_delete_member`).

Re-exported by the top-level `text.py` shim (HA requires platform files at the
integration's top level - see modules/__init__.py's docstring).
"""
from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from ...const import CONF_ROSTER, DOMAIN


BIRTHDATE_SCRATCH_UNIQUE_ID = "birthdate_scratch"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    roster = entry.data[CONF_ROSTER]
    async_add_entities(
        [
            *(RosterNameText(entry, member) for member in roster),
            _BirthdateScratchText(entry),
        ]
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service("delete_member", {}, "async_delete_member")


class RosterNameText(TextEntity, RestoreEntity):
    """The display name for one roster member. Value persists across restarts via
    RestoreEntity - the config entry's `name` is only the INITIAL value at wizard-submit
    time (and the permanent seed for that member's stable `member_id` - see
    util.slugify_unique), not re-applied on every setup.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:account"
    _attr_mode = TextMode.TEXT
    _attr_native_max = 50
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member: dict) -> None:
        self._entry = entry
        self._member_id = member["member_id"]
        self._attr_name = f"{member['name']} Name"
        self._attr_unique_id = f"{entry.entry_id}_{self._member_id}_name"
        self._attr_native_value = member["name"]

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
            self._attr_native_value = last_state.state

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()

    async def async_delete_member(self) -> None:
        """Permanently deletes this roster member - see `roster.py`'s `async_delete_member`
        for the full removal/cleanup shape. Imported locally to avoid a circular import
        (`roster.py` doesn't import this module, but keeping the import local matches this
        codebase's established convention for cross-module service delegation, e.g.
        `modules/chores/sensor.py`'s own `async_delete`)."""
        from ... import roster

        await roster.async_delete_member(self.hass, self._entry, self._member_id)


class _BirthdateScratchText(TextEntity):
    """Household-scoped (one, not per-member) scratch field for the Settings tab's
    birthdate-edit popup (`modules/settings/dashboard.py`'s `_birthdate_edit_popup`) - the
    user types a DD/MM/YYYY birthdate here, then taps Save, which calls
    `family_dashboard.set_birthdate` targeted at the specific member's own
    `RosterBirthdateDate` entity (see `modules/settings/date.py`); that service reads THIS
    field, converts/validates via `util.ddmmyyyy_to_iso`, and clears it back to "" afterward.
    Deliberately NOT `RestoreEntity` - same "never let a stale draft linger" reasoning as the
    Add Event popup's own scratch text fields (`modules/calendar/text.py`).
    """

    _attr_has_entity_name = True
    _attr_name = "Birthdate Entry"
    _attr_icon = "mdi:cake-variant"
    _attr_native_max = 10
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{BIRTHDATE_SCRATCH_UNIQUE_ID}"
        self._attr_native_value = ""

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
