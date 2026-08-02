# Family Dashboard
📖 **[Full Setup Guide → SETUP.md](./SETUP.md)**

A single Home Assistant custom integration: install via HACS, run one wizard, get a
turnkey family command center - Calendar, Lists, Chores & Rewards, and Settings/Roster - with
no YAML to hand-edit and a dashboard that's generated, not hand-coded.

Replaces `ha-family-hub` (the old YAML-package/dashboard reference repo) and
`ha-family-hub-setup` (a failed installer-wizard attempt) entirely. See
`family-hub-v2-rebuild-plan.md` in the project folder for the full architecture and the
reasoning behind the rebuild.

## Why a rebuild

`ha-family-hub-setup` promised "one wizard, done" but wrote static YAML package files and
required the user to manually update `configuration.yaml` with contnet from Family Hub and then HA got restarted -
neither was true on a real install.  Family Dashboard fixes this
architecturally: every entity is created live, owned directly by this integration - no YAML,
no restart dependency.

## Status: 1.0 (2026-08-02)

Feature-complete against the v1 plan and live-validated end-to-end - not an early scaffold.
Setup is a single wizard (Roster → Colors → Avatars → Birthdates → Features → Link HA users →
Calendar → Lists → Chores & Rewards → Confirm) that provisions everything live, no YAML, no
restart required for anything it creates.

- **Settings/Roster**: always-on core. Name, color (16 choices), avatar (own live-updating
  picker, folder-backed so new images drop in without a code change), and birthdate per
  member, all `RestoreEntity`-backed and editable any time from the Settings tab - not just at
  setup.
- **Calendar**: per-member calendar mapping onto whatever real calendar service is already
  connected, plus a shared Family calendar, an own-computed Birthdays calendar (no external
  "Birthdays" integration - HA doesn't ship one), and Holidays auto-provisioned for the US and
  the Philippines via HA's own Holiday integration on first setup. Reminders resolve their
  notify target live from whichever phone is currently linked to that person's HA account.
- **Lists**: per-member preset to-do lists (To-Do/Shopping/Packing/Gift Ideas/Custom), fully
  isolated between family members.
- **Chores & Rewards**: points economy with a claim → approve/deny (reason required) flow,
  PIN-gated Parent Review, and an Unassigned option for shared household chores with no single
  owner.
- **Dashboard**: generated and registered automatically - four uniformly-labeled tabs
  (Calendar/Lists/Chores/Settings) for every viewer; the wall-mounted Kiosk sees everyone at
  once with toggle-filter pills, anyone logged in via their own linked HA account sees only
  their own.
- **Reconfigure**: a real Options Flow - add a member, change anyone's features/calendar/
  notify mapping any time, disable a feature reversibly, or permanently delete a member
  (their chores/rewards fall back to Unassigned rather than vanishing).
- **Deliberately deferred, not gaps**: a Meals module (the feature registry is already shaped
  for it) and best-effort import from the legacy `ha-family-hub` install (stubbed, not a
  launch requirement).

See `family-dashboard-claude-code-brief.md` for the full build history and the mandatory
live-instance validation gate this project holds itself to (the predecessor shipped 13/13
passing tests and still failed its first real install - a live end-to-end run against a real
HA instance is required before anything here is called done, not just the automated suite).

## Module architecture

Each toggleable feature (Calendar, Lists, Chores & Rewards) is a self-contained module under
`custom_components/family_dashboard/modules/<name>/`. Settings/Roster is always-on core, not
a toggle - see `const.py`'s `FEATURES` registry and `modules/__init__.py`'s docstring for the
module contract new features (Meals, etc.) need to follow.

## Development

```
pip install -r requirements_test.txt
pytest tests/
```

Uses `pytest-homeassistant-custom-component`. A real running dev HA instance is also needed
for the live-validation gate - see `family-hub-v2-rebuild-plan.md`'s "Dev environment for
live validation" section.
