"""Chores & Rewards' `select` entities - frequency and assigned-to fields, for both the Add
Chore/Add Reward popups' scratch fields and each EXISTING chore/reward's own live-editable
fields. Chores didn't own the `select` platform before this - it's forwarded now whenever any
roster member has "chores" enabled (see const.py's FEATURES entry), aggregated alongside
Settings/Calendar by the top-level `select.py` shim (see that file's docstring).

Options are plain native dropdowns (a handful of text choices) - no custom swatch-grid popup
needed, unlike the 16-color case (`modules/settings/dashboard.py`'s `_color_picker_popup`).
Assigned-to options are roster member NAMES plus `_UNASSIGNED_OPTION` ("Unassigned" - a chore/
reward can genuinely have no owner, explicit user request), matching the wizard's own
name-then-resolve-to-`member_id` convention (`config_flow.py`'s `async_step_confirm`) - a name
collision between two roster members is a pre-existing, unaddressed limitation, not something
new here. Options are computed once at construction time from `entry.data`, same convention as
`modules/calendar/select.py`'s `FamilyDashboardEventCalendarSelect` - by the time any of these
entities is (re)constructed, a roster change has already gone through its own reload, so
`entry.data` is current.

An unassigned item is deliberately Settings-only: `modules/chores/dashboard.py`'s per-member
Chores-tab filtering (`item["assigned_to"] == member["member_id"]`) never matches `None`, so an
unassigned chore/reward simply never appears on anyone's Chores-tab column or in Parent Review
until it's assigned - no separate code path needed there. Its task sensor/buttons ARE still
created (see `sensor.py`'s `_assigned_member_has_chores`, which treats "unassigned" as always
eligible, not gated on any member's own chores toggle) so it stays editable/deletable from
Settings, and approving it is a safe no-op for points (there's no member's points sensor to
find - see `FamilyDashboardTaskSensor._points_sensor`'s existing `is not None` guards).
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import CHORE_FREQUENCIES, CONF_CHORES, CONF_REWARDS, CONF_ROSTER, DOMAIN
from . import crud
from .crud import UNASSIGNED_OPTION
from .crud import member_display_name as _member_name
from .crud import resolve_assigned_to as _resolve_assigned_to

_FREQUENCY_OPTIONS = list(CHORE_FREQUENCIES.values())


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    member_names = [m["name"] for m in entry.data[CONF_ROSTER]]
    entities: list = [
        NewChoreFrequencySelect(entry),
        NewChoreAssignedToSelect(entry, member_names),
        NewRewardAssignedToSelect(entry, member_names),
    ]
    entities.extend(
        ChoreFrequencySelect(entry, chore) for chore in entry.data.get(CONF_CHORES, [])
    )
    entities.extend(
        ChoreAssignedToSelect(entry, chore, member_names)
        for chore in entry.data.get(CONF_CHORES, [])
    )
    entities.extend(
        RewardAssignedToSelect(entry, reward, member_names)
        for reward in entry.data.get(CONF_REWARDS, [])
    )
    async_add_entities(entities)


class NewChoreFrequencySelect(SelectEntity):
    """Add Chore popup's scratch frequency field - reset to the default after each submit
    (see `crud.async_create_chore_from_scratch_fields`)."""

    _attr_has_entity_name = True
    _attr_name = "New Chore Frequency"
    _attr_icon = "mdi:calendar-refresh"
    _attr_options = _FREQUENCY_OPTIONS
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_new_chore_frequency"
        self._attr_current_option = CHORE_FREQUENCIES["daily"]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()


class NewChoreAssignedToSelect(SelectEntity):
    """Add Chore popup's scratch assigned-to field."""

    _attr_has_entity_name = True
    _attr_name = "New Chore Assigned To"
    _attr_icon = "mdi:account-arrow-right"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member_names: list[str]) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_new_chore_assigned_to"
        self._attr_options = [*member_names, UNASSIGNED_OPTION]
        self._attr_current_option = member_names[0] if member_names else UNASSIGNED_OPTION

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()


class NewRewardAssignedToSelect(SelectEntity):
    """Same shape as `NewChoreAssignedToSelect`, for the Add Reward popup."""

    _attr_has_entity_name = True
    _attr_name = "New Reward Assigned To"
    _attr_icon = "mdi:account-arrow-right"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member_names: list[str]) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_new_reward_assigned_to"
        self._attr_options = [*member_names, UNASSIGNED_OPTION]
        self._attr_current_option = member_names[0] if member_names else UNASSIGNED_OPTION

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()


class ChoreFrequencySelect(SelectEntity):
    """Editable frequency field for one EXISTING chore - tap opens the native dropdown
    showing its real current value. Not a `RestoreEntity` - same reasoning as `ChoreNameText`
    (modules/chores/text.py): state must derive fresh from `entry.data` each time this is
    reconstructed by the reload its own edit triggers."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-refresh"
    _attr_options = _FREQUENCY_OPTIONS
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, chore: dict) -> None:
        self._entry = entry
        self._chore_id = chore["chore_id"]
        self._attr_name = f"{chore['name']} Frequency"
        self._attr_unique_id = f"{entry.entry_id}_{self._chore_id}_frequency"
        self._attr_current_option = CHORE_FREQUENCIES.get(chore["frequency"], _FREQUENCY_OPTIONS[0])

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_select_option(self, option: str) -> None:
        label_to_key = {v: k for k, v in CHORE_FREQUENCIES.items()}
        await crud.async_update_chore_field(
            self.hass, self._entry, self._chore_id, frequency=label_to_key.get(option, "daily")
        )


class ChoreAssignedToSelect(SelectEntity):
    """Editable assigned-to field for one EXISTING chore. Same live-field-entity reasoning as
    `ChoreFrequencySelect`."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-arrow-right"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, chore: dict, member_names: list[str]) -> None:
        self._entry = entry
        self._chore_id = chore["chore_id"]
        self._attr_name = f"{chore['name']} Assigned To"
        self._attr_unique_id = f"{entry.entry_id}_{self._chore_id}_assigned_to"
        self._attr_options = [*member_names, UNASSIGNED_OPTION]
        self._attr_current_option = _member_name(entry, chore.get("assigned_to"))

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_select_option(self, option: str) -> None:
        await crud.async_update_chore_field(
            self.hass, self._entry, self._chore_id,
            assigned_to=_resolve_assigned_to(self._entry, option),
        )


class RewardAssignedToSelect(SelectEntity):
    """Same shape as `ChoreAssignedToSelect`, for one existing reward."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-arrow-right"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, reward: dict, member_names: list[str]) -> None:
        self._entry = entry
        self._reward_id = reward["reward_id"]
        self._attr_name = f"{reward['name']} Assigned To"
        self._attr_unique_id = f"{entry.entry_id}_{self._reward_id}_assigned_to"
        self._attr_options = [*member_names, UNASSIGNED_OPTION]
        self._attr_current_option = _member_name(entry, reward.get("assigned_to"))

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_select_option(self, option: str) -> None:
        await crud.async_update_reward_field(
            self.hass, self._entry, self._reward_id,
            assigned_to=_resolve_assigned_to(self._entry, option),
        )
