"""Per-member "shown in shared views" `switch` entities - one per family member, always
provisioned. Backs the Kiosk bucket's toggle-filter pills on the Calendar and Chores tabs
(see `dashboard/registry.py`'s module docstring): a member's calendar/chores only appear in
the Kiosk bucket's overlaid grid while their switch is on. Personal buckets never consult
this - a linked member's own tab content is fixed, not filterable (see the rebuild plan's
per-bucket content rules).

One switch per member, not one per (member, tab) pair - the mockup's separate
`activeMembers`/`visibleKids` state per tab isn't worth two entities per member; a member
either counts as "shown" everywhere in the Kiosk bucket or not.

Also owns `RosterEnabledSwitch` - the whole-member Disable/re-enable control (Settings
dashboard's "Remove Member" section), a distinct, administrative concept from the casual
Kiosk-overlay "shown" toggle above: disabling excludes a member from the generated dashboard
entirely (not just the Kiosk overlay) and stops their calendar reminders, while keeping all
their data intact - see `roster.py`'s `async_set_member_disabled`.

Re-exported by the top-level `switch.py` shim (HA requires platform files at the
integration's top level - see modules/__init__.py's docstring).
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from ... import roster as roster_helpers
from ...const import CONF_DISABLED, CONF_FEATURES, CONF_ROSTER, DOMAIN, FEATURES


def shown_switch_unique_id(entry: ConfigEntry, member_id: str) -> str:
    return f"{entry.entry_id}_{member_id}_shown"


def enabled_switch_unique_id(entry: ConfigEntry, member_id: str) -> str:
    return f"{entry.entry_id}_{member_id}_enabled"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    roster = entry.data[CONF_ROSTER]
    async_add_entities(RosterShownSwitch(entry, member) for member in roster)
    async_add_entities(RosterEnabledSwitch(entry, member) for member in roster)
    async_add_entities(
        RosterFeatureSwitch(entry, member, feature_key)
        for member in roster
        for feature_key in FEATURES
    )


class RosterShownSwitch(SwitchEntity, RestoreEntity):
    """Whether this roster member currently appears in the Kiosk bucket's overlaid
    Calendar/Chores views. Defaults on (matches the mockup's all-members-active-by-default
    state) and persists across restarts via RestoreEntity.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:eye"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member: dict) -> None:
        self._entry = entry
        self._member_id = member["member_id"]
        self._attr_name = f"{member['name']} Shown"
        self._attr_unique_id = shown_switch_unique_id(entry, self._member_id)
        self._attr_is_on = True

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
        if last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()


class RosterFeatureSwitch(SwitchEntity):
    """Whether one roster member currently has a given FEATURES key (Calendar/Lists/Chores &
    Rewards) selected - lets a parent toggle a member's feature on/off from the Settings
    dashboard at any time, instead of only at initial setup. Kiosk/parent-only by design: the
    Settings dashboard only wires this into the Kiosk bucket's view, never a linked member's
    own personal bucket (see `modules/settings/dashboard.py`).

    Deliberately NOT a `RestoreEntity`, unlike every other entity in this integration - its
    on/off state must derive fresh from `entry.data` every time this entity is (re)constructed,
    since the `hass.config_entries.async_reload` its own toggle triggers is what makes the new
    value authoritative. Using `RestoreEntity`'s own last-persisted local state would fight
    that source of truth and could desync after a plain HA restart, which restores old local
    state without ever calling `roster.async_set_member_features`.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:toggle-switch"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member: dict, feature_key: str) -> None:
        self._entry = entry
        self._member_id = member["member_id"]
        self._feature_key = feature_key
        # "<Name> Calendar Enabled", not the bare "<Name> Calendar" - live-verified this
        # matters, not just phrasing: the bare form is IDENTICAL to the Calendar module's own
        # proxy entity name (modules/calendar/calendar.py's "<Name> Calendar"), which made HA's
        # entity registry disambiguate the actual generated entity_id with an area-name prefix
        # (`living_room_family_dashboard_...`) instead of the expected
        # `family_dashboard_<id>_calendar` - functionally harmless (dashboard.py resolves the
        # real entity_id via the registry, not a guessed string) but needlessly confusing in
        # Settings > Entities. Avoiding the name collision at the source keeps entity_ids
        # predictable.
        self._attr_name = f"{member['name']} {FEATURES[feature_key]['name']} Enabled"
        self._attr_unique_id = f"{entry.entry_id}_{self._member_id}_feature_{feature_key}"
        self._attr_is_on = feature_key in member.get(CONF_FEATURES, [])

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    def _current_member(self) -> dict:
        return next(
            m for m in self._entry.data[CONF_ROSTER] if m["member_id"] == self._member_id
        )

    async def _async_set(self, *, enabled: bool) -> None:
        features = [key for key in FEATURES if key in self._current_member().get(CONF_FEATURES, [])]
        if enabled and self._feature_key not in features:
            features.append(self._feature_key)
        elif not enabled and self._feature_key in features:
            features.remove(self._feature_key)
        # Restores canonical FEATURES-dict order rather than whatever append/remove above left
        # behind, matching the wizard's own stored ordering.
        features = [key for key in FEATURES if key in features]
        await roster_helpers.async_set_member_features(
            self.hass, self._entry, self._member_id, features
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(enabled=True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(enabled=False)


class RosterEnabledSwitch(SwitchEntity):
    """Whole-member Disable/re-enable - distinct from `RosterFeatureSwitch` above (a single
    feature) and from `RosterShownSwitch` (a casual Kiosk-calendar-overlay filter pill): this
    is the administrative "remove this member" control from the Settings dashboard, hiding
    EVERY entity they own and excluding them from the generated dashboard entirely while
    keeping their data intact (see `roster.py`'s `async_set_member_disabled`).

    Deliberately NOT a `RestoreEntity`, same reasoning as `RosterFeatureSwitch` - state must
    derive fresh from `entry.data[CONF_DISABLED]` each time the reload its own toggle triggers
    reconstructs it.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-check"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, member: dict) -> None:
        self._entry = entry
        self._member_id = member["member_id"]
        self._attr_name = f"{member['name']} Enabled"
        self._attr_unique_id = enabled_switch_unique_id(entry, self._member_id)
        self._attr_is_on = not member.get(CONF_DISABLED, False)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_turn_on(self, **kwargs) -> None:
        await roster_helpers.async_set_member_disabled(
            self.hass, self._entry, self._member_id, disabled=False
        )

    async def async_turn_off(self, **kwargs) -> None:
        await roster_helpers.async_set_member_disabled(
            self.hass, self._entry, self._member_id, disabled=True
        )
