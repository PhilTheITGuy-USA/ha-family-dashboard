"""Parent PIN `text` entity - one per config entry (not per-member; there's only one Family
Dashboard install per HA instance, and parent-mode gating is a whole-household concept) -
plus the PIN-entry numpad's buffer entity and its `append_pin_digit` service.

Also owns Chores & Rewards' text fields: `NewChoreNameText`/`NewRewardNameText` (the Add
Chore/Add Reward popups' scratch name fields, cleared after each submit - see `crud.py`'s
`async_create_chore_from_scratch_fields`/`async_create_reward_from_scratch_fields`) and
`ChoreNameText`/`RewardNameText` (one per EXISTING chore/reward, tap → native edit dialog,
persists via `crud.async_update_chore_field`/`async_update_reward_field`).

Re-exported (aggregated alongside modules/settings/text.py) by the top-level `text.py` shim -
NOT a 1:1 shim like most modules, since Settings (always-on) and Chores (conditional) both
need the `text` platform for the same config entry, and HA only calls one `async_setup_entry`
per (entry, platform) pair. See the top-level `text.py`'s own docstring for why.
"""
from __future__ import annotations

import voluptuous as vol
import homeassistant.components.binary_sensor as binary_sensor_component
import homeassistant.components.text as text_component
from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from ...const import CONF_CHORES, CONF_REWARDS, DOMAIN
from . import crud
from .sensor import _deny_reason_unique_id

DEFAULT_PIN = "1234"
PIN_LENGTH = 4

NEW_CHORE_NAME_UNIQUE_ID_SUFFIX = "new_chore_name"
NEW_REWARD_NAME_UNIQUE_ID_SUFFIX = "new_reward_name"


def parent_pin_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.entry_id}_parent_pin"


def pin_entry_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.entry_id}_pin_entry"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # Add Chore/Add Reward's scratch name fields are always provisioned alongside the existing
    # per-item fields below (like the Add Event popup's own scratch fields) - "Chores &
    # Rewards" is a single combined feature, so there's no narrower condition to gate these on
    # beyond this platform already only being forwarded when at least one member has "chores"
    # (see const.py's FEATURES).
    entities: list = [
        FamilyDashboardParentPinText(entry),
        FamilyDashboardPinEntryText(entry),
        NewChoreNameText(entry),
        NewRewardNameText(entry),
    ]
    entities.extend(ChoreNameText(entry, chore) for chore in entry.data.get(CONF_CHORES, []))
    entities.extend(RewardNameText(entry, reward) for reward in entry.data.get(CONF_REWARDS, []))
    entities.extend(
        TaskDenyReasonText(entry, chore["chore_id"], "chore", chore["name"])
        for chore in entry.data.get(CONF_CHORES, [])
    )
    entities.extend(
        TaskDenyReasonText(entry, reward["reward_id"], "reward", reward["name"])
        for reward in entry.data.get(CONF_REWARDS, [])
    )
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "append_pin_digit", {vol.Required("digit"): cv.string}, "async_append_digit"
    )
    platform.async_register_entity_service(
        "append_pin_digit_raw", {vol.Required("digit"): cv.string}, "async_append_digit_raw"
    )
    platform.async_register_entity_service("verify_old_pin", {}, "async_verify_old_pin")
    platform.async_register_entity_service("save_new_pin", {}, "async_save_new_pin")
    platform.async_register_entity_service("add_chore", {}, "async_add_chore")
    platform.async_register_entity_service("add_reward", {}, "async_add_reward")


class FamilyDashboardParentPinText(TextEntity, RestoreEntity):
    """Current parent-unlock PIN. Persists across restarts via RestoreEntity - the default
    "1234" is seeded only when no restored state exists (mirrors the legacy
    `family_hub_parent.yaml` automation's "seed default PIN on first run only" behavior, so
    a changed PIN is never silently reset back to the default on restart).
    """

    _attr_has_entity_name = True
    _attr_name = "Parent PIN"
    _attr_icon = "mdi:lock"
    _attr_mode = TextMode.PASSWORD
    _attr_native_max = 8
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = parent_pin_unique_id(entry)
        self._attr_native_value = DEFAULT_PIN

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


class FamilyDashboardPinEntryText(TextEntity):
    """Scratch buffer for the dashboard's numpad (Chores tab, `#parentpin` section - ported
    from the legacy `family-hub.yaml`'s digit-accumulation pattern, but as an owned entity
    service instead of a `scripts.yaml` script, per architecture principle 1). Deliberately
    NOT a RestoreEntity - a half-entered PIN surviving a restart would just be confusing, not
    useful.

    Each digit button on the original unlock numpad calls the `append_pin_digit` entity
    service (registered in `async_setup_entry` above). Once `PIN_LENGTH` digits have
    accumulated, compares against `FamilyDashboardParentPinText`'s value by delegating to the
    existing `FamilyDashboardParentModeBinarySensor.async_unlock` (reused, not duplicated) -
    which raises `HomeAssistantError` on a wrong PIN, surfaced to the tapping user the same way
    `deny_task`/`adjust_points` errors already are. The buffer is cleared after every
    4-digit attempt, right or wrong.

    The SAME buffer is reused for the PIN-change flow (`async_verify_old_pin`/
    `async_save_new_pin`), but via the separate `append_pin_digit_raw` service - a new PIN can
    be 3-8 characters (matching `FamilyDashboardParentPinText`'s own max), so there's no fixed
    length to auto-submit on the way `append_pin_digit` does; that flow's popup uses explicit
    Verify/Save buttons instead (see modules/chores/dashboard.py's PIN-change popup).
    """

    _attr_has_entity_name = True
    _attr_name = "PIN Entry"
    _attr_icon = "mdi:dialpad"
    _attr_mode = TextMode.PASSWORD
    _attr_native_max = 8
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = pin_entry_unique_id(entry)
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

    def _binary_sensor_entity(self, unique_id: str):
        component = self.hass.data.get(binary_sensor_component.DATA_COMPONENT)
        if component is None:
            return None
        entity_id = er.async_get(self.hass).async_get_entity_id("binary_sensor", DOMAIN, unique_id)
        return component.get_entity(entity_id) if entity_id else None

    def _parent_mode_entity(self):
        return self._binary_sensor_entity(f"{self._entry.entry_id}_parent_mode")

    def _pin_change_authorized_entity(self):
        # Imported locally to avoid a circular import (binary_sensor.py imports this module
        # for parent_pin_unique_id already).
        from .binary_sensor import pin_change_authorized_unique_id

        return self._binary_sensor_entity(pin_change_authorized_unique_id(self._entry))

    def _parent_pin_entity(self):
        component = self.hass.data.get(text_component.DATA_COMPONENT)
        if component is None:
            return None
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "text", DOMAIN, parent_pin_unique_id(self._entry)
        )
        return component.get_entity(entity_id) if entity_id else None

    async def async_append_digit(self, digit: str) -> None:
        buffer = (self._attr_native_value or "") + digit
        if len(buffer) < PIN_LENGTH:
            self._attr_native_value = buffer
            self.async_write_ha_state()
            return

        self._attr_native_value = ""
        self.async_write_ha_state()

        parent_mode = self._parent_mode_entity()
        if parent_mode is not None:
            await parent_mode.async_unlock(buffer)

    async def async_append_digit_raw(self, digit: str) -> None:
        """Plain accumulate, no auto-submit at any length - used by the PIN-change flow's
        popup (see class docstring), capped at native_max like any other text entity."""
        buffer = ((self._attr_native_value or "") + digit)[: self._attr_native_max]
        self._attr_native_value = buffer
        self.async_write_ha_state()

    async def async_verify_old_pin(self) -> None:
        """PIN-change step 1: does the buffer match the current PIN? If so, opens the
        60-second authorized window. Always clears the buffer, matching the legacy
        `pin_verify_old` script."""
        buffer = self._attr_native_value or ""
        self._attr_native_value = ""
        self.async_write_ha_state()

        pin_entity = self._parent_pin_entity()
        if pin_entity is not None and buffer == pin_entity.native_value:
            authorized = self._pin_change_authorized_entity()
            if authorized is not None:
                await authorized.async_authorize()

    async def async_save_new_pin(self) -> None:
        """PIN-change step 2: while the authorized window is open, save the buffer (3-8
        chars) as the new PIN and close the window. A too-short buffer is a silent no-op
        (matches the legacy `pin_save_new` script's own choose-with-no-default shape) - the
        popup just stays open for another attempt."""
        authorized = self._pin_change_authorized_entity()
        if authorized is None or not authorized.is_on:
            return

        buffer = self._attr_native_value or ""
        if len(buffer) < 3:
            return

        pin_entity = self._parent_pin_entity()
        if pin_entity is not None:
            await pin_entity.async_set_value(buffer)

        self._attr_native_value = ""
        self.async_write_ha_state()
        await authorized.async_deauthorize()


class NewChoreNameText(TextEntity):
    """Add Chore popup's scratch name field - deliberately NOT a `RestoreEntity`, cleared
    after every submit (see `crud.async_create_chore_from_scratch_fields`), same reasoning as
    `modules/calendar/text.py`'s own event-title scratch field. Its own entity service
    (`add_chore`, registered in `async_setup_entry` above) delegates straight to `crud.py` -
    kept here rather than as a grab-bag method so this class stays a plain entity."""

    _attr_has_entity_name = True
    _attr_name = "New Chore Name"
    _attr_native_max = 100
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{NEW_CHORE_NAME_UNIQUE_ID_SUFFIX}"
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

    async def async_add_chore(self) -> None:
        await crud.async_create_chore_from_scratch_fields(self.hass, self._entry)


class NewRewardNameText(TextEntity):
    """Same shape as `NewChoreNameText`, for the Add Reward popup."""

    _attr_has_entity_name = True
    _attr_name = "New Reward Name"
    _attr_native_max = 100
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{NEW_REWARD_NAME_UNIQUE_ID_SUFFIX}"
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

    async def async_add_reward(self) -> None:
        await crud.async_create_reward_from_scratch_fields(self.hass, self._entry)


class ChoreNameText(TextEntity):
    """Editable name field for one EXISTING chore - tap opens the native text more-info
    dialog showing its real current value. Not a `RestoreEntity` - same reasoning as
    `roster.py`'s `RosterFeatureSwitch`: state must derive fresh from `entry.data` each time
    this is reconstructed by the reload its own edit triggers."""

    _attr_has_entity_name = True
    _attr_native_max = 100
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, chore: dict) -> None:
        self._entry = entry
        self._chore_id = chore["chore_id"]
        self._attr_name = f"{chore['name']} Name"
        self._attr_unique_id = f"{entry.entry_id}_{self._chore_id}_name"
        self._attr_native_value = chore["name"]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_value(self, value: str) -> None:
        await crud.async_update_chore_field(self.hass, self._entry, self._chore_id, name=value)


class RewardNameText(TextEntity):
    """Same shape as `ChoreNameText`, for one existing reward."""

    _attr_has_entity_name = True
    _attr_native_max = 100
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, reward: dict) -> None:
        self._entry = entry
        self._reward_id = reward["reward_id"]
        self._attr_name = f"{reward['name']} Name"
        self._attr_unique_id = f"{entry.entry_id}_{self._reward_id}_name"
        self._attr_native_value = reward["name"]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_set_value(self, value: str) -> None:
        await crud.async_update_reward_field(self.hass, self._entry, self._reward_id, name=value)


class TaskDenyReasonText(TextEntity, RestoreEntity):
    """Free-text reason logged to the Logbook when a claim is denied - one per chore/reward
    (not a single shared scratch field), so drafting a reason for one item's pending claim
    never collides with another's. RestoreEntity: a reason drafted before a HA restart, before
    a parent has actually reviewed it, shouldn't be lost. Cleared automatically whenever the
    item is claimed again (`FamilyDashboardTaskSensor.async_claim`) - a fresh review cycle
    starts blank, not with the previous cycle's leftover text. Not persisted into
    `entry.data` at all (unlike Name/Points) - it's ephemeral per review cycle, not config.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:comment-text-outline"
    _attr_native_max = 250
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, item_id: str, kind: str, name: str) -> None:
        self._entry = entry
        self._attr_name = f"{name} Deny Reason"
        self._attr_unique_id = _deny_reason_unique_id(entry, item_id, kind)
        self._attr_native_value = ""

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
