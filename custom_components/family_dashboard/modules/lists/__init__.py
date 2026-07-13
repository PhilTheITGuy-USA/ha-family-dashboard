"""Lists module - STUB, not yet implemented.

To build:
- Family Dashboard's OWN `todo` platform - a `FamilyDashboardTodoListEntity` per selected
  preset (To-Do, Shopping, Packing, Gift Ideas, Custom - reuse the preset table from
  `ha-family-hub-setup-plan.md`, it's still a good list). Deliberately NOT chained into
  HA's core `local_todo` config flow the way v1 did - owning the entity directly means no
  dependency on another integration's config-flow internals staying stable across HA
  versions, and no separate config entries to manage.
- A config-flow step class here for preset selection (multi-select, mirrors v1's
  `list_presets` step), chained into `config_flow.py`'s `async_step_modules`, gated on
  "lists" being selected.
- Add a top-level `todo.py` shim once real entities exist, replacing the stub at
  `custom_components/family_dashboard/todo.py` today (see modules/settings/ for the shim
  pattern).
"""
