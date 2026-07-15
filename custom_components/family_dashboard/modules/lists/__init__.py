"""Lists module - Family Dashboard's own `todo` platform.

Entity classes live in `modules/lists/todo.py` (`FamilyDashboardTodoListEntity`, one per
(roster member who has "lists" in their own `features` list, selected preset) pair -
isolated per person, e.g. `todo.family_dashboard_ada_shopping` and
`todo.family_dashboard_grace_shopping` are separate entities). The top-level `todo.py` is a
thin shim re-exporting that module's `async_setup_entry` (see modules/__init__.py's
docstring for why HA requires platform files at the integration's top level).

The per-member preset picker is `config_flow.py`'s `async_step_lists`, chained in after
`async_step_link_users` and only shown if at least one roster member selected "lists" in
`async_step_features`. Presets (To-Do, Shopping, Packing, Gift Ideas, Custom) live in
`const.py`'s `LIST_PRESETS`, sourced from the legacy `ha-family-hub-setup-plan.md` table.

Item persistence uses `RestoreEntity`'s `extra_restore_state_data`/`async_get_last_extra_data`
mechanism (not a plain `State` string, which can't hold a list of items) - same "own entity
platform + RestoreEntity, no YAML" principle `modules/settings/` established for scalar
values, just the structured-data variant.
"""
