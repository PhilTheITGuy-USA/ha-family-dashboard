"""Best-effort import from an existing `ha-family-hub` install - STUB, not yet implemented,
and intentionally not a v1 gate.

To build (only if cheap - see module docstring):
- Detect old roster helpers: `input_select.*_color` / `input_text.*_display_name` entities
  matching `ha-family-hub`'s `packages/family_hub_settings.yaml` naming pattern. If found,
  offer to pre-fill the wizard's roster step with their current values instead of typing
  from scratch.
- Detect an existing KidsChores config entry. If found, offer to import point totals/history
  - skip gracefully (not an error) if the shape doesn't match what's expected; this is a
  nice-to-have, not something worth hardening extensively.
- Should be entirely optional and skippable - never block wizard completion on migration
  detection failing or finding nothing.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant


async def async_detect_legacy_install(hass: HomeAssistant) -> dict | None:
    """Not yet implemented - see module docstring. Returns None (nothing detected) until
    built out, which is a safe/correct default - callers should treat None as "skip
    migration, proceed with a fresh wizard" rather than an error.
    """
    return None
