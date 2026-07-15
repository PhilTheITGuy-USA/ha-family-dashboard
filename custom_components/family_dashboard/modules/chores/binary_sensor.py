"""Parent-mode `binary_sensor` - one per config entry, gates Approve/Deny/point-adjustment
actions behind a PIN the same way the legacy `family_hub_parent.yaml` UI lock did. Stated
plainly, matching that legacy package's own comment: this is a UI lock, not cryptographic
security - anyone with Developer Tools access could flip it directly.

Unlock needs a PIN, so it's an entity-registered service (`family_dashboard.unlock_parent_mode`,
field `pin`) rather than a button - same reasoning as `deny_task`/`adjust_points` in
modules/chores/sensor.py. Lock is zero-param, so it's a plain button
(`FamilyDashboardLockParentModeButton` in modules/chores/button.py).

Re-exported by the top-level `binary_sensor.py` shim - a NEW top-level file (no other module
uses this platform yet), unlike `text.py`'s aggregator (see that file's docstring for why
platform sharing needs special handling and this one doesn't).
"""
from __future__ import annotations

import voluptuous as vol
import homeassistant.components.text as text_component
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.restore_state import RestoreEntity

from ...const import DOMAIN
from .text import parent_pin_unique_id

AUTO_LOCK_SECONDS = 300


PIN_CHANGE_AUTO_CANCEL_SECONDS = 60


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            FamilyDashboardParentModeBinarySensor(entry),
            FamilyDashboardPinChangeAuthorizedBinarySensor(entry),
        ]
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "unlock_parent_mode", {vol.Required("pin"): cv.string}, "async_unlock"
    )


class FamilyDashboardParentModeBinarySensor(BinarySensorEntity, RestoreEntity):
    """Whether parent mode is currently unlocked. Auto-locks after 5 minutes, matching the
    legacy `family_hub_auto_lock_parent` automation exactly.
    """

    _attr_has_entity_name = True
    _attr_name = "Parent Mode"
    _attr_icon = "mdi:shield-account"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_parent_mode"
        self._attr_is_on = False
        self._autolock_unsub = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._autolock_unsub is not None:
            self._autolock_unsub()
            self._autolock_unsub = None
        await super().async_will_remove_from_hass()

    def _pin_entity(self):
        component = self.hass.data.get(text_component.DATA_COMPONENT)
        if component is None:
            return None
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "text", DOMAIN, parent_pin_unique_id(self._entry)
        )
        return component.get_entity(entity_id) if entity_id else None

    async def async_unlock(self, pin: str) -> None:
        pin_entity = self._pin_entity()
        if pin_entity is None or pin != pin_entity.native_value:
            raise HomeAssistantError("Incorrect parent PIN")

        self._attr_is_on = True
        self.async_write_ha_state()

        if self._autolock_unsub is not None:
            self._autolock_unsub()
        self._autolock_unsub = async_call_later(
            self.hass, AUTO_LOCK_SECONDS, self._async_auto_lock
        )

    async def async_lock(self) -> None:
        if self._autolock_unsub is not None:
            self._autolock_unsub()
            self._autolock_unsub = None
        self._attr_is_on = False
        self.async_write_ha_state()

    async def _async_auto_lock(self, _now) -> None:
        self._autolock_unsub = None
        self._attr_is_on = False
        self.async_write_ha_state()


def pin_change_authorized_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.entry_id}_pin_change_authorized"


class FamilyDashboardPinChangeAuthorizedBinarySensor(BinarySensorEntity):
    """Whether the PIN-change flow's "enter a new PIN" step is currently open - ported from
    the legacy `input_boolean.pin_change_authorized` + `family_hub_pin_change_timeout`
    automation. NOT `RestoreEntity` - always starts closed on restart, same reasoning as
    Parent Mode never resuming "unlocked" across a restart.
    """

    _attr_has_entity_name = True
    _attr_name = "PIN Change Authorized"
    _attr_icon = "mdi:lock-open-check"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = pin_change_authorized_unique_id(entry)
        self._attr_is_on = False
        self._autocancel_unsub = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._autocancel_unsub is not None:
            self._autocancel_unsub()
            self._autocancel_unsub = None
        await super().async_will_remove_from_hass()

    async def async_authorize(self) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

        if self._autocancel_unsub is not None:
            self._autocancel_unsub()
        self._autocancel_unsub = async_call_later(
            self.hass, PIN_CHANGE_AUTO_CANCEL_SECONDS, self._async_auto_cancel
        )

    async def async_deauthorize(self) -> None:
        if self._autocancel_unsub is not None:
            self._autocancel_unsub()
            self._autocancel_unsub = None
        self._attr_is_on = False
        self.async_write_ha_state()

    async def _async_auto_cancel(self, _now) -> None:
        self._autocancel_unsub = None
        self._attr_is_on = False
        self.async_write_ha_state()
