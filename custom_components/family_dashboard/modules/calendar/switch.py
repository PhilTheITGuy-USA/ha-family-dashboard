"""Household-scoped `switch` entities for Calendar: the Birthdays/Holidays overlay
show/hide toggles (same `RestoreEntity`-backed pattern as `modules/settings/switch.py`'s
per-member toggles, since these persist across restarts same as a member's own), plus the Add
Event popup's all-day flag and Week/Day/Hour reminder checkboxes (NOT `RestoreEntity` - these
are cleared after every submit alongside the scratch text fields, see `events.py`).

Forwarded once if any roster member has "calendar" enabled. Re-exported (aggregated alongside
modules/settings/switch.py) by the top-level `switch.py` shim - see that file's docstring.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from ...const import DOMAIN, REMINDER_LEAD_TIMES

BIRTHDAYS_SHOWN_UNIQUE_ID = "birthdays_shown"
HOLIDAYS_SHOWN_UNIQUE_ID = "holidays_shown"
EVENT_ALL_DAY_UNIQUE_ID = "event_all_day"


def reminder_switch_unique_id(lead_key: str) -> str:
    return f"event_remind_{lead_key}"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entities: list[SwitchEntity] = [
        _OverlayShownSwitch(entry, BIRTHDAYS_SHOWN_UNIQUE_ID, "Birthdays Shown"),
        _OverlayShownSwitch(entry, HOLIDAYS_SHOWN_UNIQUE_ID, "Holidays Shown"),
        _EventScratchSwitch(entry, EVENT_ALL_DAY_UNIQUE_ID, "Event All Day"),
    ]
    entities.extend(
        _EventScratchSwitch(
            entry, reminder_switch_unique_id(key), f"Event Remind 1 {key.capitalize()} Before"
        )
        for key in REMINDER_LEAD_TIMES
    )
    async_add_entities(entities)


class _CalendarSwitchBase(SwitchEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, unique_id_suffix: str, name: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_is_on = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()


class _OverlayShownSwitch(_CalendarSwitchBase, RestoreEntity):
    """Birthdays/Holidays overlay visibility - persists across restarts, default on (matches
    every other "shown" toggle's default in this integration)."""

    _attr_icon = "mdi:eye"

    def __init__(self, entry: ConfigEntry, unique_id_suffix: str, name: str) -> None:
        super().__init__(entry, unique_id_suffix, name)
        self._attr_is_on = True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == "on"


class _EventScratchSwitch(_CalendarSwitchBase):
    """Add Event popup field - not RestoreEntity, cleared after every submit."""

    _attr_icon = "mdi:bell-ring-outline"
