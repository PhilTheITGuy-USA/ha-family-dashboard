"""Dashboard template + registry system - STUB, not yet implemented.

To build (modeled on `ccpk1/choreops-dashboards`'s proven pattern - see
`project_choreops_kidschores_successor` memory):
- Versioned template YAML fragments per module under `dashboard/templates/` (e.g.
  `settings-v1.yaml`, and later `calendar-v1.yaml`, `lists-v1.yaml`, `chores-v1.yaml`),
  with placeholder tokens resolved dynamically against THIS integration's own entity IDs
  (via each module's dashboard-template contribution function - see modules/__init__.py's
  docstring) - never hardcoded names/IDs the way v1's vendored `family-hub.yaml` was.
- A function here, `async_build_dashboard_config(hass, entry) -> dict`, that: looks up
  which modules are enabled for this entry, calls each enabled module's (plus Settings'
  always-on) template-contribution function with the resolved entity IDs, and assembles
  the results into one Lovelace dashboard config dict (views/cards).
- A "regenerate dashboard" button/service that re-runs this whenever roster or enabled
  modules change, so the dashboard never needs hand-editing per deployment - this is the
  core promise of the rebuild, don't skip it once modules exist.
- This function is intentionally NOT called yet from `__init__.py` - see the TODO there.
  Wire it in once at least one toggleable module (Calendar/Lists/Chores) has real entities
  to build a dashboard around.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_build_dashboard_config(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Not yet implemented - see module docstring."""
    raise NotImplementedError(
        "Dashboard generation isn't built yet - see dashboard/registry.py's docstring for "
        "the template + registry system this needs to become."
    )
