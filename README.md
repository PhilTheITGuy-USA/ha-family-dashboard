# Family Dashboard

A single Home Assistant custom integration: install via HACS, run one wizard, get a
turnkey family command center - Calendar, Lists, Chores & Rewards, and Settings/Roster - with
no YAML to hand-edit and a dashboard that's generated, not hand-coded.

Replaces `ha-family-hub` (the old YAML-package/dashboard reference repo) and
`ha-family-hub-setup` (a failed installer-wizard attempt) entirely. See
`family-hub-v2-rebuild-plan.md` in the project folder for the full architecture and the
reasoning behind the rebuild.

## Why a rebuild

`ha-family-hub-setup` promised "one wizard, done" but wrote static YAML package files and
hoped the user's `configuration.yaml` already included them and that HA got restarted -
neither was true on a real install, so nothing appeared. Family Dashboard fixes this
architecturally: every entity is created live, owned directly by this integration - no YAML,
no restart dependency.

## Status: early scaffold (2026-07-10)

- **Settings/Roster**: fully implemented - reference implementation for "own entity
  platform, no YAML." One color (`select`) and one name (`text`) entity per roster member,
  created live, `RestoreEntity`-backed so edits persist across restarts.
- **Calendar, Lists, Chores & Rewards**: stubbed. Enabling them in the wizard today creates
  zero entities (logged, not a crash) - see each module's docstring under
  `custom_components/family_dashboard/modules/` for what needs to be built.
- **Dashboard generation/registration**: not yet wired in - deliberately left out until the
  toggleable modules are real, so it doesn't generate an empty shell. See
  `dashboard/registry.py` and `dashboard/register.py`.
- **Google Calendar guided mapping step**: not yet implemented - belongs to the Calendar
  module once built out.

See `family-dashboard-claude-code-brief.md` for the build-out plan and the mandatory
live-instance validation gate (this project's last attempt shipped 13/13 passing tests and
still failed its first real install - a live end-to-end run is a required step here, not
optional).

## Module architecture

Each toggleable feature (Calendar, Lists, Chores & Rewards) is a self-contained module under
`custom_components/family_dashboard/modules/<name>/`. Settings/Roster is always-on core, not
a toggle - see `const.py`'s `MODULES` registry and `modules/__init__.py`'s docstring for the
module contract new features (Meals, etc.) need to follow.

## Development

```
pip install -r requirements_test.txt
pytest tests/
```

Uses `pytest-homeassistant-custom-component`. A real running dev HA instance is also needed
for the live-validation gate - see `family-hub-v2-rebuild-plan.md`'s "Dev environment for
live validation" section.
