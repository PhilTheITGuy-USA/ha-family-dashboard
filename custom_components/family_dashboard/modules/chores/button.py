"""Family Dashboard's own `button` platform for Chores & Rewards - Claim/Approve per chore
and reward (zero-param actions), plus a single Lock Parent Mode button. Deny (needs a
reason) is deliberately NOT a button - see modules/chores/sensor.py's module docstring for
why that's an entity-registered service instead.

Each Claim/Approve button resolves its sibling `FamilyDashboardTaskSensor` through the
entity registry (by the exact same `unique_id` the sensor computed - see
`sensor._task_unique_id`) and calls its `async_claim`/`async_approve` method directly, the
same direct-entity-forwarding pattern already established by `modules/calendar/calendar.py`.

Re-exported by the top-level `button.py` shim (HA requires platform files at the
integration's top level - see modules/__init__.py's docstring).
"""
from __future__ import annotations

import homeassistant.components.binary_sensor as binary_sensor
import homeassistant.components.sensor as sensor
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import CONF_CHORES, CONF_REWARDS, CONF_ROSTER, DOMAIN
from .sensor import FamilyDashboardTaskSensor, _assigned_member_has_chores, _task_unique_id


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    roster_by_id = {member["member_id"]: member for member in entry.data[CONF_ROSTER]}

    buttons: list[ButtonEntity] = []
    for chore in entry.data.get(CONF_CHORES, []):
        if not _assigned_member_has_chores(chore, roster_by_id):
            continue
        buttons.append(_TaskClaimButton(entry, chore, "chore"))
        buttons.append(_TaskApproveButton(entry, chore, "chore"))
    for reward in entry.data.get(CONF_REWARDS, []):
        if not _assigned_member_has_chores(reward, roster_by_id):
            continue
        buttons.append(_TaskClaimButton(entry, reward, "reward"))
        buttons.append(_TaskApproveButton(entry, reward, "reward"))

    if "chores" in {f for m in entry.data[CONF_ROSTER] for f in m.get("features", [])}:
        buttons.append(FamilyDashboardLockParentModeButton(entry))

    async_add_entities(buttons)


class _TaskButtonBase(ButtonEntity):
    """Shared construction + sibling-sensor lookup for Claim/Approve buttons."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, item: dict, kind: str) -> None:
        self._entry = entry
        item_id = item["chore_id"] if kind == "chore" else item["reward_id"]
        self._sensor_unique_id = _task_unique_id(entry, item_id, kind)
        self._attr_unique_id = f"{self._sensor_unique_id}_{self._action}"
        # No member-name prefix (unlike an earlier version) - entity_id is keyed purely on
        # the item's own name/id, same convention as its sibling field entities
        # (modules/chores/text.py's ChoreNameText etc.) and the same "never derive a stable
        # id from mutable data" principle util.slugify_unique's own docstring already states
        # for member_id - reassigning who a chore belongs to must not look like it renamed the
        # entity. "assigned_to" is still a live attribute on the task sensor itself.
        self._attr_name = f"{item['name']} {self._action.capitalize()}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    def _sensor(self) -> FamilyDashboardTaskSensor | None:
        component = self.hass.data.get(sensor.DATA_COMPONENT)
        if component is None:
            return None
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, self._sensor_unique_id
        )
        return component.get_entity(entity_id) if entity_id else None


class _TaskClaimButton(_TaskButtonBase):
    _action = "claim"
    _attr_icon = "mdi:hand-front-right"

    async def async_press(self) -> None:
        sensor_entity = self._sensor()
        if sensor_entity is not None:
            await sensor_entity.async_claim()


class _TaskApproveButton(_TaskButtonBase):
    _action = "approve"
    _attr_icon = "mdi:check-decagram"

    async def async_press(self) -> None:
        sensor_entity = self._sensor()
        if sensor_entity is not None:
            await sensor_entity.async_approve()


class FamilyDashboardLockParentModeButton(ButtonEntity):
    """Zero-param - always locks parent mode immediately (see
    modules/chores/binary_sensor.py for the unlock side, which needs a PIN and is therefore
    an entity service, not a button)."""

    _attr_has_entity_name = True
    _attr_name = "Lock Parent Mode"
    _attr_icon = "mdi:shield-lock"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_lock_parent_mode"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_press(self) -> None:
        component = self.hass.data.get(binary_sensor.DATA_COMPONENT)
        if component is None:
            return
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "binary_sensor", DOMAIN, f"{self._entry.entry_id}_parent_mode"
        )
        parent_mode = component.get_entity(entity_id) if entity_id else None
        if parent_mode is not None:
            await parent_mode.async_lock()
