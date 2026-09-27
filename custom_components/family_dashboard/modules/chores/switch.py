"""Chores & Rewards' `switch` entities - each chore's Reminders toggle (`ChoreRemindersSwitch`,
persisted on the chore record like its other field entities) and the Add Chore popup's scratch
toggle (`NewChoreRemindersSwitch`, reset after each submit). See `reminders.py` for what the
flag does.

Aggregated (alongside Settings and Calendar) by the top-level `switch.py`.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import CONF_CHORES, DOMAIN
from . import crud


def new_chore_reminders_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.entry_id}_new_chore_reminders"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entities: list = [NewChoreRemindersSwitch(entry)]
    entities.extend(ChoreRemindersSwitch(entry, chore) for chore in entry.data.get(CONF_CHORES, []))
    async_add_entities(entities)


class _ChoreSwitchBase(SwitchEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-ring-outline"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )


class NewChoreRemindersSwitch(_ChoreSwitchBase):
    """Add Chore popup's scratch toggle - not a RestoreEntity, reset to off after each submit
    (see `crud.async_create_chore_from_scratch_fields`)."""

    _attr_name = "New Chore Reminders"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = new_chore_reminders_unique_id(entry)
        self._attr_is_on = False

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()


class ChoreRemindersSwitch(_ChoreSwitchBase):
    """One EXISTING chore's Reminders flag. Not a RestoreEntity - derives from `entry.data`
    each time the reload its own edit triggers rebuilds it (same as `ChorePointsNumber`)."""

    def __init__(self, entry: ConfigEntry, chore: dict) -> None:
        super().__init__(entry)
        self._chore_id = chore["chore_id"]
        self._attr_name = f"{chore['name']} Reminders"
        self._attr_unique_id = f"{entry.entry_id}_{self._chore_id}_reminders"
        self._attr_is_on = bool(chore.get("reminders"))

    async def async_turn_on(self, **kwargs) -> None:
        await crud.async_update_chore_field(self.hass, self._entry, self._chore_id, reminders=True)

    async def async_turn_off(self, **kwargs) -> None:
        await crud.async_update_chore_field(self.hass, self._entry, self._chore_id, reminders=False)
