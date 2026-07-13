"""Roster display-name `text` entities - one per family member, always provisioned.

Re-exported by the top-level `text.py` shim (HA requires platform files at the
integration's top level - see modules/__init__.py's docstring).
"""
from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from ...const import CONF_ROSTER, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    roster = entry.data[CONF_ROSTER]
    async_add_entities(RosterNameText(entry, member) for member in roster)


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
