"""Constants and the module registry for Family Dashboard.

Decisions locked in `family-hub-v2-rebuild-plan.md` (2026-07-08/10):
- Settings/Roster is ALWAYS-ON CORE, not a toggleable module - it's the one thing every
  other module depends on. Its platforms (`SETTINGS_PLATFORMS`) are forwarded
  unconditionally by `__init__.py`, and it deliberately has no entry in `MODULES` below.
- `MODULES` lists only the genuinely optional pieces the wizard's module-selection step
  offers: Calendar, Lists, Chores & Rewards (Meals is a planned-later addition - it should
  slot into this same dict without touching the others).
"""
from __future__ import annotations

DOMAIN = "family_dashboard"

CONF_ROSTER = "roster"
CONF_MODULES = "modules"

ROSTER_MAX_MEMBERS = 8

COLOR_OPTIONS = [
    "Salmon",
    "Blue",
    "Green",
    "Orange",
    "Purple",
    "Teal",
    "Pink",
    "Amber",
    "Red",
    "Slate",
]

# Always-on: forwarded for every config entry regardless of the `modules` wizard answer.
SETTINGS_PLATFORMS = ["select", "text"]

# Toggleable modules offered in the wizard's `modules` step. Each module's "platforms" list
# is only forwarded via async_forward_entry_setups when that module's key is selected.
#
# "implemented" is a SCAFFOLD-STAGE marker, not a permanent field: False means the
# top-level platform file(s) for that module are currently stubs that add zero entities
# (see modules/<key>/ for what still needs building). Remove the key entirely once a
# module is genuinely built out - don't leave stale "implemented: True" markers lying
# around as scope creeps.
MODULES: dict[str, dict] = {
    "calendar": {
        "name": "Calendar",
        "platforms": ["calendar"],
        "default_selected": True,
        "implemented": False,
    },
    "lists": {
        "name": "Lists",
        "platforms": ["todo"],
        "default_selected": True,
        "implemented": False,
    },
    "chores": {
        "name": "Chores & Rewards",
        "platforms": ["sensor", "button"],
        "default_selected": True,
        "implemented": False,
    },
}

DEFAULT_SELECTED_MODULES = [key for key, mod in MODULES.items() if mod["default_selected"]]
