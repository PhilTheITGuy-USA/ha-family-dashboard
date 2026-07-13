"""Calendar module - STUB, not yet implemented.

To build:
- One `CalendarEntity` per roster member, mapped to a real `calendar.*` entity (Google
  Calendar, Local Calendar, etc.) chosen via a guided config-flow step - NOT a hardcoded
  placeholder like v1's `calendar.PERSON_1`. That step must: scan
  `hass.states.async_all("calendar")`, let the user map one calendar per roster member (or
  explicitly mark "no calendar yet" - never silently leave it unmapped), and if none exist,
  show instructions + a retry button that re-scans without restarting the whole wizard. See
  `family-hub-v2-rebuild-plan.md`'s "Decided" section - this must be real and checked, not a
  documented manual step, per Phillip's own feedback on why v1's wizard felt pointless.
- Port the reminder logic from `ha-family-hub`'s `packages/family_hub_calendar.yaml`
  (opt-in per-event push reminders with a lead time in days/hours/minutes) as this module's
  own entity/service, not a YAML script+automation pair.
- Add a config-flow step class here (e.g. `CalendarMappingStep`) and chain it into
  `config_flow.py`'s `async_step_modules`, gated on "calendar" being selected.
- Add a top-level `calendar.py` shim once real entities exist, replacing the stub at
  `custom_components/family_dashboard/calendar.py` today (see modules/settings/ for the
  shim pattern).
"""
