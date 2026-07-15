"""Avatar file-list `sensor` - one per config entry, always provisioned. Exposes the live
contents of `/config/www/family_dashboard/avatars/` as a `file_list` attribute (frontend-
servable `/local/family_dashboard/avatars/*.png` URLs), driving the dashboard's avatar picker
grid.

Deliberately NOT HA core's built-in `folder` platform sensor (`homeassistant.components.
folder.sensor`) - confirmed by reading its source directly that it's a YAML-only platform
(`setup_platform`, no `async_setup_entry`), so instantiating it would mean a
`configuration.yaml`/packages edit, violating this integration's own "no YAML packages"
principle. This is the same directory-scan behavior as our own owned `sensor` entity instead -
polled on HA's normal sensor interval, no YAML required.

Re-exported by the top-level `sensor.py` shim, which is an AGGREGATOR (not a 1:1 shim) since
Settings (always-on, this file) and Chores (conditional) both need the `sensor` platform for
the same config entry - see that file's docstring.
"""
from __future__ import annotations

from pathlib import Path

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN

AVATARS_SUBPATH = "www/family_dashboard/avatars"

# has_entity_name + the shared "Family Dashboard" device slugify to this exact entity_id -
# other modules (modules/settings/select.py's RosterAvatarSelect) read this sensor's
# `file_list` attribute instead of re-scanning the avatars folder themselves.
AVATARS_SENSOR_ENTITY_ID = "sensor.family_dashboard_avatars"


def avatars_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(AVATARS_SUBPATH))


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([FamilyDashboardAvatarsSensor(entry, hass)])


class FamilyDashboardAvatarsSensor(SensorEntity):
    """Native value is the avatar count (a sensor needs some scalar state); the actual picker
    data is the `file_list` attribute - same "attribute carries the real payload" shape HA's
    own `folder` sensor uses, so the dashboard-side picker card reads it the same way.
    """

    _attr_has_entity_name = True
    _attr_name = "Avatars"
    _attr_icon = "mdi:account-box-multiple"
    _attr_should_poll = True

    def __init__(self, entry: ConfigEntry, hass: HomeAssistant) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_avatars"
        self._dir = avatars_dir(hass)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    def update(self) -> None:
        files = sorted(self._dir.glob("*.png")) if self._dir.is_dir() else []
        self._attr_native_value = len(files)
        self._attr_extra_state_attributes = {
            "file_list": [f"/local/family_dashboard/avatars/{f.name}" for f in files]
        }
