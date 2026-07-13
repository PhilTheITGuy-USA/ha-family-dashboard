"""Roster color `select` entities - one per family member, always provisioned.

Re-exported by the top-level `select.py` shim (HA requires platform files at the
integration's top level - see modules/__init__.py's docstring).
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from ...const import COLOR_OPTIONS, CONF_ROSTER, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    roster = entry.data[CONF_ROSTER]
    async_add_entities(RosterColorSelect(entry, member) for member in roster)


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
