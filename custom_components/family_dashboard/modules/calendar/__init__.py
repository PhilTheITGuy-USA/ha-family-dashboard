"""Calendar module - Family Dashboard's own `calendar` platform.

Entity classes live in `modules/calendar/calendar.py` (`FamilyDashboardCalendarEntity`, one
per roster member who mapped a real `calendar.*` entity via the wizard's `calendar` step - a
full read+write proxy, not a display-only wrapper, forwarding to the mapped source entity via
`EntityComponent.get_entity()`). The top-level `calendar.py` is a thin shim re-exporting that
module's `async_setup_entry` (see modules/__init__.py's docstring for why HA requires
platform files at the integration's top level).

The guided mapping step is `config_flow.py`'s `async_step_calendar` (falling back to
`async_step_calendar_none_found` if no calendars exist anywhere yet), chained in after
`async_step_link_users` and only shown if at least one roster member selected "calendar" in
`async_step_features`.

The opt-in per-event reminder engine (ported from `ha-family-hub`'s
`packages/family_hub_calendar.yaml`) lives in `modules/calendar/reminders.py` - a background
5-minute poll, not a new entity type, registered from `calendar.py`'s own `async_setup_entry`
and cancelled in the top-level `__init__.py`'s `async_unload_entry`.

`modules/calendar/dashboard.py`'s `async_calendar_view_card` is this module's dashboard-
template contribution (see `dashboard/registry.py`'s docstring for the multi-view assembly
it plugs into) - a multi-calendar `week-planner-card`, called once per VIEW rather than once
per member (a documented exception to the general per-member pattern, since the card type
itself natively overlays multiple calendars in one grid).
"""
