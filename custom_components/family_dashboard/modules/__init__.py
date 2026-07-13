"""Family Dashboard's toggleable-module system.

The registry of available modules lives in `const.py`'s `MODULES` dict (key -> display
name, platforms, default_selected, implemented). Each module is a subpackage here
(`modules/<key>/`) that should contain:

  - Entity platform logic (e.g. `modules/calendar/calendar.py` defining the actual
    `CalendarEntity` subclasses and `async_setup_entry`). HA's
    `async_forward_entry_setups` requires platform files at the INTEGRATION'S TOP LEVEL
    (`custom_components/family_dashboard/<platform>.py`), not nested under modules/ - so
    each module's top-level platform file (e.g. top-level `calendar.py`) is a thin shim:
    `from .modules.calendar.calendar import async_setup_entry as async_setup_entry`. See
    `modules/settings/` for the working example of this pattern.
  - (optional) a config-flow step class, for modules that need extra input beyond the
    always-on roster + module-selection steps in `config_flow.py` (e.g. Calendar's guided
    calendar-mapping step, Lists' preset picker). Chain it in from `config_flow.py`'s
    `async_step_modules`, gated on that module's key being selected.
  - (optional, once `dashboard/registry.py` is built out) a dashboard-template
    contribution function that returns cards/sections given the resolved entity IDs for
    that module's provisioned entities.

Settings/Roster is NOT part of this registry - it's always-on core, not a toggle (see
`const.py`'s module docstring and `family-hub-v2-rebuild-plan.md`'s "Decided" section). Its
platforms are forwarded unconditionally by the top-level `__init__.py`, independent of
whatever's in `MODULES`.

New module checklist (e.g. adding Meals later): create `modules/meals/`, add its entity
platform file(s) + top-level shim(s), add an entry to `const.py`'s `MODULES`, add any
config-flow step needed, done - none of the other modules should need to change.
"""
