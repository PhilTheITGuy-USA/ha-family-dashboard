"""Chores & Rewards' `number` entities - the first (and, as of this module, only) use of the
`number` domain in this integration. Points/cost were previously only ever plain integers
parsed in the setup wizard (`vol.Coerce(int)`) - a `number` entity (native slider/box, tap to
edit) is the right live-editable fit, better than reusing `text` with string-to-int parsing.

Owns: `NewChorePointsNumber`/`NewRewardCostNumber` (the Add Chore/Add Reward popups' scratch
fields, reset to their default after each submit - see `crud.py`) and `ChorePointsNumber`/
`RewardCostNumber` (one per EXISTING chore/reward, tap → native number more-info dialog,
persists via `crud.async_update_chore_field`/`async_update_reward_field`).

Re-exported (aggregated alongside `modules/calendar/number.py`) by the top-level `number.py`
shim - see that file's docstring.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import CONF_CHORES, CONF_REWARDS, DOMAIN
from . import crud

_DEFAULT_POINTS = 5
_DEFAULT_COST = 50


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entities: list = [NewChorePointsNumber(entry), NewRewardCostNumber(entry)]
    entities.extend(ChorePointsNumber(entry, chore) for chore in entry.data.get(CONF_CHORES, []))
    entities.extend(RewardCostNumber(entry, reward) for reward in entry.data.get(CONF_REWARDS, []))
    async_add_entities(entities)


class NewChorePointsNumber(NumberEntity):
    """Add Chore popup's scratch points field - reset to `_DEFAULT_POINTS` after each submit
    (see `crud.async_create_chore_from_scratch_fields`), same "cleared, not RestoreEntity"
    convention as the Add Event popup's own scratch fields."""

    _attr_has_entity_name = True
    _attr_name = "New Chore Points"
    _attr_icon = "mdi:star"
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_new_chore_points"
        self._attr_native_value = _DEFAULT_POINTS

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()


class NewRewardCostNumber(NumberEntity):
    """Same shape as `NewChorePointsNumber`, for the Add Reward popup."""

    _attr_has_entity_name = True
    _attr_name = "New Reward Cost"
    _attr_icon = "mdi:gift"
    _attr_native_min_value = 1
    _attr_native_max_value = 500
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_new_reward_cost"
        self._attr_native_value = _DEFAULT_COST

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()


class ChorePointsNumber(NumberEntity):
    """Editable points field for one EXISTING chore - tap opens the native number more-info
    dialog showing its real current value. Not a `RestoreEntity` - same reasoning as
    `ChoreNameText` (modules/chores/text.py): state must derive fresh from `entry.data` each
    time this is reconstructed by the reload its own edit triggers."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:star"
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, chore: dict) -> None:
        self._entry = entry
        self._chore_id = chore["chore_id"]
        self._attr_name = f"{chore['name']} Points"
        self._attr_unique_id = f"{entry.entry_id}_{self._chore_id}_points"
        self._attr_native_value = chore["points"]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_native_value(self, value: float) -> None:
        await crud.async_update_chore_field(self.hass, self._entry, self._chore_id, points=int(value))


class RewardCostNumber(NumberEntity):
    """Same shape as `ChorePointsNumber`, for one existing reward."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:gift"
    _attr_native_min_value = 1
    _attr_native_max_value = 500
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, reward: dict) -> None:
        self._entry = entry
        self._reward_id = reward["reward_id"]
        self._attr_name = f"{reward['name']} Cost"
        self._attr_unique_id = f"{entry.entry_id}_{self._reward_id}_cost"
        self._attr_native_value = reward["cost"]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_native_value(self, value: float) -> None:
        await crud.async_update_reward_field(self.hass, self._entry, self._reward_id, cost=int(value))
