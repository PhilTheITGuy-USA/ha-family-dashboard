"""Family Dashboard's own `sensor` platform for Chores & Rewards - one
`FamilyDashboardPointsSensor` per roster member with "chores" enabled (their running points
total), and one `FamilyDashboardTaskSensor` per chore/reward (its claim/approve/deny status).

Claim/Approve are separate `button` entities (see modules/chores/button.py) that resolve
their sibling sensor via the entity registry (`unique_id` -> entity_id, both computed with
`_task_unique_id`/`_points_unique_id` below) and call its methods directly - the same
direct-entity-forwarding pattern `modules/calendar/calendar.py`'s proxy already established,
just resolved through the registry first since (unlike Calendar's user-supplied source
entity_id) these entity_ids aren't known until HA's own id-generation runs at add-time.

Deny (needs a reason) and point adjustment (needs a delta) are entity-registered custom
services (`family_dashboard.deny_task`/`family_dashboard.adjust_points`) - the same
first-class mechanism HA's own `todo`/`calendar` components use for their own parameterized
actions, since a plain zero-param button can't carry either value. `family_dashboard.
delete_task` (zero-param) genuinely removes the chore/reward (see `crud.py`'s module
docstring for why this is a real `entity_registry.async_remove`, not `hidden_by`).

`frequency` is a display label only in v1 - no once-per-day/week claim-locking. Claiming
always starts a fresh cycle regardless of prior status (idle/approved/denied all become
"claimed" again) - see const.py's CHORE_FREQUENCIES docstring.

Re-exported by the top-level `sensor.py` shim (HA requires platform files at the
integration's top level - see modules/__init__.py's docstring).
"""
from __future__ import annotations

import homeassistant.components.sensor as sensor
import homeassistant.components.text as text_component
import voluptuous as vol
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from ...const import CONF_CHORES, CONF_FEATURES, CONF_REWARDS, CONF_ROSTER, DOMAIN
from ...util import parse_schedule_days_text


def _points_unique_id(entry: ConfigEntry, member_id: str) -> str:
    return f"{entry.entry_id}_{member_id}_points"


def _day_of_week_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.entry_id}_day_of_week"


def _schedule_scratch_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.entry_id}_chore_schedule_scratch"


def _task_unique_id(entry: ConfigEntry, item_id: str, kind: str) -> str:
    return f"{entry.entry_id}_{item_id}_{kind}"


def _deny_reason_unique_id(entry: ConfigEntry, item_id: str, kind: str) -> str:
    """Separate from `_task_unique_id` (not just `f"{task_uid}_deny_reason"` reused as a
    string) so it's its own first-class id builder other modules import, same convention as
    `_points_unique_id`/`_task_unique_id` themselves."""
    return f"{entry.entry_id}_{item_id}_{kind}_deny_reason"


def _assigned_member_has_chores(item: dict, roster_by_id: dict) -> bool:
    """Whether this chore/reward's entities should exist: either it's UNASSIGNED (explicit
    user request - always eligible, not gated on any member's own toggle, since it isn't
    tied to one; it stays Settings-only via modules/chores/dashboard.py's per-member
    filtering never matching `None`, not via being excluded here), or its assigned member
    currently has "chores" selected. Unlike the points sensor (filtered the same way just
    below), task sensors weren't checking the latter at all until an earlier fix, which
    meant toggling Chores off for a member did nothing to their own chore/reward entities. A
    member no longer in the roster at all (shouldn't normally happen, but defensive) is
    treated as not having chores."""
    assigned_to = item.get("assigned_to")
    if assigned_to is None:
        return True
    member = roster_by_id.get(assigned_to)
    return member is not None and "chores" in member.get(CONF_FEATURES, [])


def member_feature_entity_ids(entry: ConfigEntry, member_id: str) -> list[tuple[str, str]]:
    """(domain, unique_id) pairs for this member's Chores-feature entities - used by
    `roster.async_set_member_features` to hide/un-hide them in the entity registry. Includes
    the points sensor plus every chore/reward's task sensor AND claim/approve buttons
    (`modules/chores/button.py` computes the same button unique_ids from a task sensor's own
    unique_id, so no separate import from that module is needed here)."""
    entity_ids = [("sensor", _points_unique_id(entry, member_id))]
    for chore in entry.data.get(CONF_CHORES, []):
        if chore["assigned_to"] != member_id:
            continue
        task_id = _task_unique_id(entry, chore["chore_id"], "chore")
        entity_ids += [
            ("sensor", task_id),
            ("button", f"{task_id}_claim"),
            ("button", f"{task_id}_approve"),
            ("text", _deny_reason_unique_id(entry, chore["chore_id"], "chore")),
        ]
    for reward in entry.data.get(CONF_REWARDS, []):
        if reward["assigned_to"] != member_id:
            continue
        task_id = _task_unique_id(entry, reward["reward_id"], "reward")
        entity_ids += [
            ("sensor", task_id),
            ("button", f"{task_id}_claim"),
            ("button", f"{task_id}_approve"),
            ("text", _deny_reason_unique_id(entry, reward["reward_id"], "reward")),
        ]
    return entity_ids


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    roster_by_id = {member["member_id"]: member for member in entry.data[CONF_ROSTER]}

    points_sensors = [
        FamilyDashboardPointsSensor(entry, member)
        for member in entry.data[CONF_ROSTER]
        if "chores" in member.get(CONF_FEATURES, [])
    ]
    task_sensors = [
        FamilyDashboardTaskSensor(entry, chore, "chore", roster_by_id)
        for chore in entry.data.get(CONF_CHORES, [])
        if _assigned_member_has_chores(chore, roster_by_id)
    ] + [
        FamilyDashboardTaskSensor(entry, reward, "reward", roster_by_id)
        for reward in entry.data.get(CONF_REWARDS, [])
        if _assigned_member_has_chores(reward, roster_by_id)
    ]
    async_add_entities([*points_sensors, *task_sensors, FamilyDashboardDayOfWeekSensor(entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "deny_task", {vol.Required("reason"): cv.string}, "async_deny"
    )
    platform.async_register_entity_service(
        "adjust_points", {vol.Required("delta"): vol.Coerce(int)}, "async_adjust"
    )
    platform.async_register_entity_service("delete_task", {}, "async_delete")
    platform.async_register_entity_service(
        "set_chore_schedule_days", {}, "async_set_schedule_days"
    )


class FamilyDashboardPointsSensor(SensorEntity, RestoreEntity):
    """One roster member's running points total."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:star"
    _attr_native_unit_of_measurement = "points"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member: dict) -> None:
        self._entry = entry
        self._member_id = member["member_id"]
        self._attr_name = f"{member['name']} Points"
        self._attr_unique_id = _points_unique_id(entry, self._member_id)
        self._attr_native_value = 0

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
            self._attr_native_value = int(float(last_state.state))

    async def async_adjust(self, delta: int) -> None:
        self._attr_native_value = (self._attr_native_value or 0) + delta
        self.async_write_ha_state()


class FamilyDashboardTaskSensor(SensorEntity, RestoreEntity):
    """One chore or reward's status: idle -> claimed -> approved/denied.

    kind="chore": approve AWARDS `item["points"]` to the assigned member's points sensor.
    kind="reward": approve DEDUCTS `item["cost"]`, raising HomeAssistantError first if the
    member doesn't have enough points (no partial/negative-balance redemptions).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, item: dict, kind: str, roster_by_id: dict) -> None:
        self._entry = entry
        self._item = item
        self._kind = kind
        item_id = item["chore_id"] if kind == "chore" else item["reward_id"]
        self._item_id = item_id
        self._member_id = item.get("assigned_to")
        # No member-name prefix in the entity's own name (unlike an earlier version) - the
        # entity_id is keyed purely on the item's own name/id, matching its sibling field
        # entities (modules/chores/text.py's ChoreNameText etc.) and the same "never derive a
        # stable id from mutable data" principle util.slugify_unique's own docstring already
        # states for member_id - reassigning who a chore belongs to (including to/from
        # Unassigned) must not look like it renamed the entity. "assigned_to" below is still a
        # live attribute reflecting the CURRENT owner (or "Unassigned" - there's no member to
        # award points to on approve either; `_points_sensor()` below already returns None
        # gracefully for a member_id that resolves to no real registry entry, so approving an
        # unassigned item is a safe no-op).
        member_name = roster_by_id[self._member_id]["name"] if self._member_id else "Unassigned"
        self._attr_name = item["name"]
        self._attr_unique_id = _task_unique_id(entry, item_id, kind)
        self._attr_native_value = "idle"
        self._attr_icon = "mdi:cart-check" if kind == "reward" else "mdi:checkbox-marked-outline"
        attrs = {"assigned_to": member_name, "kind": kind}
        if kind == "chore":
            attrs["points"] = item["points"]
            attrs["frequency"] = item["frequency"]
        else:
            attrs["cost"] = item["cost"]
        self._attr_extra_state_attributes = attrs

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

    def _points_sensor(self) -> FamilyDashboardPointsSensor | None:
        component = self.hass.data.get(sensor.DATA_COMPONENT)
        if component is None:
            return None
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, _points_unique_id(self._entry, self._member_id)
        )
        return component.get_entity(entity_id) if entity_id else None

    def _deny_reason_entity(self):
        component = self.hass.data.get(text_component.DATA_COMPONENT)
        if component is None:
            return None
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "text", DOMAIN, _deny_reason_unique_id(self._entry, self._item_id, self._kind)
        )
        return component.get_entity(entity_id) if entity_id else None

    async def async_claim(self) -> None:
        self._attr_native_value = "claimed"
        self.async_write_ha_state()

        # A new review cycle starts with a blank reason, not whatever was typed (or left over)
        # for the previous cycle's denial.
        reason_entity = self._deny_reason_entity()
        if reason_entity is not None:
            await reason_entity.async_set_value("")

    async def async_approve(self) -> None:
        if self._attr_native_value != "claimed":
            raise HomeAssistantError(f"'{self._item['name']}' has nothing pending to approve")

        points_sensor = self._points_sensor()
        if self._kind == "reward":
            cost = self._item["cost"]
            if points_sensor is not None and (points_sensor.native_value or 0) < cost:
                raise HomeAssistantError(
                    f"Not enough points to redeem '{self._item['name']}' (needs {cost})"
                )
            if points_sensor is not None:
                await points_sensor.async_adjust(-cost)
        elif points_sensor is not None:
            await points_sensor.async_adjust(self._item["points"])

        self._attr_native_value = "approved"
        self.async_write_ha_state()

    async def async_deny(self, reason: str) -> None:
        if self._attr_native_value != "claimed":
            raise HomeAssistantError(f"'{self._item['name']}' has nothing pending to deny")
        if not reason.strip():
            raise HomeAssistantError(
                f"A reason is required to deny '{self._item['name']}'"
            )

        member_name = self._attr_extra_state_attributes["assigned_to"]
        await self.hass.services.async_call(
            "logbook",
            "log",
            {"name": f"{member_name} - {self._item['name']}", "message": f"Denied: {reason}"},
        )
        self._attr_native_value = "denied"
        self.async_write_ha_state()

    def _schedule_scratch_entity(self):
        component = self.hass.data.get(text_component.DATA_COMPONENT)
        if component is None:
            return None
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "text", DOMAIN, _schedule_scratch_unique_id(self._entry)
        )
        return component.get_entity(entity_id) if entity_id else None

    async def async_set_schedule_days(self) -> None:
        """Save button for a chore's `#schedule-{chore_id}` popup (see
        `modules/chores/dashboard.py`) - reads the SHARED scratch field (only one such popup
        is ever open at a time), parses it, and persists onto THIS chore (the row whose Save
        button was tapped), same per-row targeting `family_dashboard.delete_task` already
        uses. Rewards have no schedule concept - a no-op, not an error, since nothing in the
        UI should ever call this on one anyway."""
        if self._kind != "chore":
            return

        scratch_entity = self._schedule_scratch_entity()
        raw_value = scratch_entity.native_value if scratch_entity else None
        try:
            schedule_days = parse_schedule_days_text(raw_value)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

        from . import crud

        await crud.async_update_chore_field(
            self.hass, self._entry, self._item_id, schedule_days=schedule_days
        )
        if scratch_entity:
            await scratch_entity.async_set_value("")

    async def async_delete(self) -> None:
        """Genuinely removes this chore/reward (`family_dashboard.delete_chore`/
        `delete_reward` - see the dashboard's Delete tile, gated behind a native Lovelace
        `confirmation:` prompt) - unlike disabling a feature, there's no prior state to
        restore to, so this is a real `entity_registry.async_remove`, not `hidden_by`. See
        `crud.py`'s module docstring. Imported locally to avoid a circular import (`crud.py`
        itself imports `_task_unique_id` from this module), same reasoning as
        `modules/chores/text.py`'s own local import of `.binary_sensor`.
        """
        from . import crud

        if self._kind == "chore":
            await crud.async_delete_chore(self.hass, self._entry, self._item_id)
        else:
            await crud.async_delete_reward(self.hass, self._entry, self._item_id)


class FamilyDashboardDayOfWeekSensor(SensorEntity):
    """One per config entry - today's lowercase weekday name (`monday`..`sunday`), the single
    source of truth `modules/chores/dashboard.py`'s `_member_task_cards` gates a scheduled
    chore's `type: conditional` tile on. Always created whenever this platform sets up at all
    (i.e. whenever any member has "chores" enabled), not only when a scheduled chore exists,
    so adding a schedule to a chore later needs no new entity-creation side effect.

    Not a `RestoreEntity` - its value is cheap to recompute and must never reflect a stale
    pre-restart day. Rolls over at local midnight via `async_track_time_change` and
    `async_write_ha_state()`, the same live-reactivity mechanism the Parent PIN gate's
    `type: conditional` cards already rely on - no config-entry reload needed for a
    scheduled chore's visibility to update as the day changes.
    """

    _attr_has_entity_name = True
    _attr_name = "Day Of Week"
    _attr_icon = "mdi:calendar-today"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = _day_of_week_unique_id(entry)
        self._unsub_midnight = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    @staticmethod
    def _today_name() -> str:
        return dt_util.now().strftime("%A").lower()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_native_value = self._today_name()
        self._unsub_midnight = async_track_time_change(
            self.hass, self._handle_midnight, hour=0, minute=0, second=5
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_midnight is not None:
            self._unsub_midnight()
            self._unsub_midnight = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_midnight(self, _now) -> None:
        self._attr_native_value = self._today_name()
        self.async_write_ha_state()
