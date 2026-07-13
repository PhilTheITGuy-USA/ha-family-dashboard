"""Storage-mode Lovelace dashboard registration - STUB, not yet implemented.

The API shape here is already KNOWN CORRECT from the v1 (`ha-family-hub-setup`) attempt -
see the `project_ha-family-hub-setup-scaffolded` memory for the full diagnosis:
- `dashboards_collection.async_create_item()` requires a `url_path` and only accepts
  `mode: "storage"` - v1's `mode: "yaml"` + `filename` combination is rejected outright,
  there's no runtime API to register a file-backed dashboard.
- Push the actual dashboard config into the created entry via
  `LovelaceStorage.async_save(config)`, not a filename reference.
- CRITICAL fix v1 missed: this integration's `manifest.json` MUST declare
  `"dependencies": ["lovelace"]` (already done - see manifest.json) so `hass.data["lovelace"]`
  is guaranteed to exist by the time this runs, instead of racing against Lovelace's own
  setup on a freshly onboarded instance (the likely real cause of v1's dashboard never
  appearing, even though the storage-mode API fix alone was validated separately).

To build: `async_register_dashboard(hass, entry, config: dict) -> bool`, called from
`dashboard/registry.py`'s output once that's wired into `__init__.py`. Should be idempotent
(safe to call again if the dashboard already exists for this entry - update in place rather
than erroring).
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_register_dashboard(
    hass: HomeAssistant, entry: ConfigEntry, config: dict
) -> bool:
    """Not yet implemented - see module docstring."""
    raise NotImplementedError(
        "Dashboard registration isn't built yet - see register.py's docstring for the "
        "known-correct API shape to implement against."
    )
