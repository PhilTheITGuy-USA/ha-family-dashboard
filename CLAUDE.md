# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Two things sharing one directory:

1. **The `family-dashboard` HA custom integration** (`custom_components/family_dashboard/`,
   domain `family_dashboard`) — a Home Assistant integration under active development. See
   `claude-code-kickoff.md` for the full project brief, architecture, and build order before
   making changes here; it links out to the authoritative planning docs.
2. **A local Home Assistant test bench** — a `homeassistant/home-assistant:stable` container
   run via Docker Compose, with its entire state (config, database, logs, onboarding) bind-mounted
   from `./config`. This doubles as the disposable live instance the project's brief requires for
   validating the integration end-to-end (not just passing pytest) — see "Live-instance validation"
   below.

## Running the HA test instance

```bash
docker compose up -d        # start (or restart after config changes that need a full reload)
docker compose logs -f      # tail Home Assistant logs
docker compose restart      # restart to pick up configuration.yaml or custom_components changes
docker compose down         # stop
```

The UI is at http://localhost:8123. `dev.env` (gitignored) holds `HA_URL` and a Long-Lived
Access Token for driving the REST/WebSocket API directly.

## Running the test suite

```bash
python -m venv .venv && ./.venv/Scripts/python.exe -m pip install -r requirements_test.txt
./.venv/Scripts/python.exe -m pytest tests/ -v      # run everything
./.venv/Scripts/python.exe -m pytest tests/test_config_flow.py -v   # single file
```

**On native Windows, `pytest-homeassistant-custom-component` does not work.** Two independent
blockers, either one fatal on its own: it unconditionally calls
`pytest_socket.disable_socket(allow_unix_socket=True)` before every test, but asyncio's
Windows `ProactorEventLoop` needs a real (non-unix) socket for its self-pipe, so every test
fails with `SocketBlockedError` (`--force-enable-socket` does not help — the block is a
hardcoded call, not the CLI-flag-driven one); separately, `homeassistant/runner.py` itself
unconditionally imports the Unix-only `fcntl` stdlib module, so even collection fails with
`ModuleNotFoundError: No module named 'fcntl'` before pytest-socket is reached. Run the suite
inside Linux instead — a disposable container is the simplest way, no venv/host install
needed. Use `python:3.14-slim`, not `python:3.12-slim` — the latter's pip has been seen
failing to resolve the pinned `pytest-homeassistant-custom-component` version even though it
genuinely exists on PyPI (an image-specific pip quirk, not a real availability gap):

```bash
docker run --rm -v "/c/ha-test-bench:/app" -w /app python:3.14-slim \
  bash -c "pip install -q -r requirements_test.txt && python -m pytest tests/ -v"
```

(On Windows/Git Bash, prefix with `MSYS_NO_PATHCONV=1` so `-w /app` isn't mangled into a
Windows path.)

`requirements_test.txt` pins `holidays`/`babel` explicitly alongside
`pytest-homeassistant-custom-component` — not incidental version pins, but requirements of
HA's own built-in "Holiday" integration, which `holidays_setup.py` drives the real config flow
of under test. The disposable pytest container doesn't auto-install a component's own
manifest-declared requirements the way a real running HA instance does, so anything exercising
another integration's flow under test needs its requirements listed here too.

## Live-instance validation (do not skip)

Per the project brief: an automated pytest pass is necessary but explicitly **not
sufficient** before calling any module done — a prior related project shipped 13/13 passing
tests and still failed its first real install. After tests are green, copy
`custom_components/family_dashboard` into `config/custom_components/family_dashboard`,
`docker compose restart`, then drive the actual config flow over the REST API using
`dev.env`'s token (`POST /api/config/config_entries/flow`, walk every step for real) and
confirm the resulting entities/config entry via `GET /api/states` /
`GET /api/config/config_entries/entry` — not just that the flow call succeeded.

## Structure

- `docker-compose.yml` — the HA test-instance service definition (container name
  `ha-test-bench`, port 8123, timezone `America/New_York`).
- `config/` — the test instance's live state (bind-mounted into the container at `/config`).
  Gitignored entirely — it's runtime state (db, logs, `.storage`, `secrets.yaml`), not
  source. `config/configuration.yaml` is HA's own entry point (unrelated to the integration's
  `custom_components/` code until that gets copied into `config/custom_components/` for a
  live-validation run, per above). It's a plain bind mount, not a Docker volume, so
  `docker compose down`/`up` alone never touches it - only losing the `config/` directory
  itself (disk failure, accidental delete, moving to a new machine) actually needs recovery.
  `config.base-snapshot.tar.gz` (repo root, gitignored - same sensitivity as `dev.env`: it
  contains the real auth database, including the `dunsel` owner account's Long-Lived Access
  Token) is a point-in-time snapshot of `config/` taken 2026-07-26, meant to be the
  restorable "base" state for this test bench (roster: Phil/Lhen/Tristan/Harlee; HA users
  dunsel/Marcus/Kiosk; a `calendar.family`/`calendar.ava` test fixture and US/Philippines
  Holiday entries; family_dashboard already installed and configured). To restore:
  `docker compose down`, delete/rename the existing `config/`, `tar -xzf
  config.base-snapshot.tar.gz`, `docker compose up -d`. This snapshot doesn't auto-update -
  if the test bench's roster/fixtures meaningfully change going forward and the new state
  should become the new restore point, re-run the same `docker compose stop` + `tar -czf` +
  `docker compose start` sequence to replace it (stop first: HA's SQLite recorder db and
  `.storage` JSON files can be mid-write while running, and a snapshot taken then risks
  restoring a corrupted/inconsistent state).
- `custom_components/family_dashboard/` — the integration's source.
  - `const.py` — domain, roster/feature constants, the `FEATURES` registry (Calendar/Lists/
    Chores & Rewards), color/avatar constants. Read its module docstring first; it records
    which decisions are locked vs. still scaffold-stage (`FEATURES[...]["implemented"]`).
  - `config_flow.py` — the setup wizard; see its module docstring for the full step
    sequence (roster → colors → per-member features → link HA users → per-feature
    sub-flows → confirm) and `FamilyDashboardOptionsFlow` (reconfigure after initial setup,
    reuses the same `build_*_schema`/`parse_*_input` functions as the initial flow).
    `strings.json` and `translations/en.json` are byte-identical and both hand-maintained —
    a new/changed step's title, description, or field labels need editing in both files or
    the English UI silently falls back to stale/missing text; there's no build step that
    generates one from the other.
  - `__init__.py` — `async_setup_entry`: forwards Settings' always-on platforms plus the
    union of every roster member's selected features' platforms, seeds static assets
    (`assets.py`), then builds and registers the generated Lovelace dashboard
    (`dashboard/`).
  - `modules/<name>/` — per-feature entity logic (`calendar/`, `lists/`, `chores/`,
    `settings/`). `modules/settings/` is the reference pattern for "own entity platform, no
    YAML". Each module can also contribute a `dashboard.py` (cards for its feature) and/or
    its own config-flow step. See `modules/__init__.py`'s docstring for the full new-module
    checklist.
  - Top-level `<platform>.py` files (`calendar.py`, `todo.py`, `select.py`, etc.) — thin
    shims HA requires at the integration's top level, re-exporting each module's real
    `async_setup_entry`.
  - `dashboard/` — generates and registers the multi-view Lovelace dashboard on every entry
    setup. `dashboard/registry.py`'s module docstring explains the current architecture:
    four uniformly-labeled tabs (Calendar/Lists/Chores/Settings) for every viewer, with
    per-viewer-bucket *content* swapped in client-side by a custom dashboard strategy
    (`www/family-dashboard-strategy.js`) rather than by generating differently-named views —
    read this before touching dashboard generation, the earlier per-person-named-views
    design was deliberately reverted. `dashboard/register.py` does the actual storage-mode
    dashboard/resource registration; its module docstring documents three corrections found
    by reading HA core source directly (no public API reaches the real `DashboardsCollection`;
    `hass.data` stores dashboards/resources in different shapes across HA versions and both
    must be handled; `frontend.async_register_built_in_panel`'s kwargs differ by version too)
    — reread it before touching dashboard *registration* (as opposed to dashboard *content*,
    which is `registry.py`'s concern).
  - The household-shared calendar ("Family calendar") is auto-detected, not roster-mapped:
    `modules/calendar/dashboard.py`'s `_family_calendar_entity` scans for any `calendar.*`
    entity whose name matches "Family" *exactly* (case-insensitively) and, if found, adds it
    as its own always-on-by-default toggle pill (`switch.family_dashboard_family_calendar_shown`)
    on both the Kiosk bucket's and every personal bucket's calendar card — same mechanism as
    the Birthdays/Holidays overlays. This replaced an earlier design where one flagged roster
    member's own calendar mapping had to double as the shared calendar (sacrificing that
    member's personal view); a live install later showed the exact-name match is a real
    gotcha — a properly-connected shared calendar named anything other than literally "Family"
    silently never appears, which is why SETUP.md's prerequisites/wizard/Known-Issues sections
    call this requirement out explicitly. Don't assume a missing Family calendar on a live
    install is a code bug before checking the entity's actual name.
  - The Add Event popup's Start/End time fields are a decomposed Date + Hour(1-12) + Minute +
    AM/PM group per side (`modules/calendar/event_time.py`), not HA's native `datetime`
    picker — that picker's 12-vs-24-hour display depends on each *viewer's own* HA account
    profile setting (Settings > General > Time Format), confirmed directly against HA
    frontend source, which a shared wall-mounted kiosk can't rely on. `event_time.py` is the
    single source of truth for all 8 fields' unique-id constants (even though the entity
    classes themselves live in `date.py`/`number.py`/`select.py` per the usual one-file-per-
    platform convention) and owns `async_recompute_end_from_start`, composing/decomposing
    through a real Python `datetime` so a Start near midnight correctly rolls End to the next
    calendar day — don't reimplement this as hour-of-day arithmetic by hand.
  - Recurring events (`switch.family_dashboard_event_recurring` + a Recurrence preset select,
    same "switch reveals a conditional card" shape as All Day Event) work by calling the
    target calendar entity's `async_create_event` *directly* (`events.py`), not via the
    `calendar.create_event` service — confirmed by reading HA core source that the service's
    own schema has no `rrule` field at all, even though the two calendar backends this project
    supports (local_calendar, google) both accept one when called directly. Bypassing the
    service means replicating its own `CalendarEntityFeature.CREATE_EVENT` support check by
    hand (`_resolve_calendar_entity`) and its localization step (`event_time.compose_datetime`
    must return a timezone-*aware* datetime via `dt_util.as_local` — a naive one raises
    `Expected all values to have a timezone`, since the service normally does that
    localization itself before the entity ever sees the value).
  - Live-verified gotcha (2026-07-25, applies to ANY future new entity, not just this
    session's): if the shared "Family Dashboard" device has already been assigned to an HA
    *area* (a normal thing to do for a kiosk device) by the time a brand-new entity is first
    registered, HA's entity registry prefixes its auto-generated entity_id with the area name
    too (e.g. `number.living_room_family_dashboard_...`), not just the device name — confirmed
    by reading `entity_registry.py`'s `_async_get_full_entity_name` directly. Every entity
    shipped before this was discovered dodged it only by luck of being created before any area
    was ever assigned; a live scan afterward found several pre-existing entities already
    affected (`text.living_room_family_dashboard_birthdate_entry` and others from the Chores
    scheduling feature) that were never fixed — a real latent bug across the whole integration,
    not something this session's fix (pinning `self.entity_id` explicitly in `__init__` on
    every entity added since) retroactively corrects. New entities going forward should keep
    pinning `entity_id` explicitly; a blanket fix for pre-existing entities is still open.
  - `assets.py` — seeds default avatars/background/theme from the package's own `www/`/
    `themes/` into `/config/www/family_dashboard/`/`/config/themes/` on first setup (HA
    can't serve files from inside a custom component's package directory directly).
  - `migration/` — best-effort import from a prior `ha-family-hub` install; currently a
    stub (`async_detect_legacy_install` always returns `None`), not a v1 gate.
  - `holidays_setup.py` — one-time auto-provisioning of HA's own built-in "Holiday"
    integration for the US and Philippines on first setup (computes holidays live from the
    `holidays` PyPI package, so it's not an ongoing sync). Idempotent by checking existing
    Holiday config entries before starting a flow, and best-effort: failures are logged and
    swallowed rather than blocking `async_setup_entry`, since creating another integration's
    config entry is outside this integration's own domain.
  - `roster.py` — shared helpers for mutating an *existing* member's features/calendar/
    notify mapping from live Settings-tab entities and reloading the entry (the Options
    Flow's own `async_step_add_confirm` is the only other path that writes
    `entry.data["roster"]`, and it's for adding a brand-new member). Feature-toggle changes
    go through here specifically because they need the `hidden_by` treatment on top of the
    plain mutate+reload.
  - `user_watch.py` / `unmapped_users.py` — keep the generated dashboard's Kiosk bucket
    correct as HA's user registry changes after initial setup. `user_watch.py` listens for
    HA's own `user_added`/`user_updated`/`user_removed` auth-manager bus events and reloads
    the entry (debounced) only when the computed Kiosk-bucket membership actually changes.
    `unmapped_users.py` raises an HA Repair Issue per active, non-system HA user not linked
    to any roster member — dismissing it in the Repairs UI is a real permanent per-user
    opt-out (confirmed against `IssueRegistry.async_get_or_create` behavior), not just a
    reminder.
  - `services.yaml` — custom services the dashboard's buttons/popups call instead of acting
    on entities directly (e.g. `deny_task`/`adjust_points`/`delete_task`/`delete_member`,
    the PIN-entry/parent-mode-unlock services, `add_event`/`add_chore`/`add_reward` for the
    scratch-field "Add" popups). Each module registers and handles its own services in its
    own `async_setup_entry` — this file only declares the schemas HA's service-call UI and
    validation use.
  - Chores & Rewards management (add/edit/delete) lives on the Chores tab behind the same
    Parent PIN gate as Parent Review, not on the (unprotected) Settings tab where it started —
    a live-reported gap, since it originally had no PIN gate at all.
  - Chores support an OPTIONAL per-chore `schedule_days` field (2026-07-21,
    `modules/chores/dashboard.py`/`sensor.py`) — absent/`None` (every chore before this
    feature) means visible/claimable every day, unchanged; a list of weekdays means only
    those days. Splitting one chore across multiple kids (e.g. "Dishes" Mon/Wed/Fri for one
    kid, Tue/Thu/Sat for another) means creating one independent chore record per kid via
    "Add Chore" — NOT a single record holding a day→assignee map — since claim/approve/
    points has no "who claimed it today" concept separate from a chore's fixed
    `assigned_to` (`FamilyDashboardTaskSensor.__init__` fixes it once, permanently). Gating
    is UI-only (one `type: conditional` per configured day, keyed on a new household
    `sensor.<device>_day_of_week` entity that rolls over at local midnight via
    `async_track_time_change`) — same "no backend claim-locking" philosophy `frequency`
    already established, not new enforcement.
  - The generated dashboard depends on five third-party Lovelace cards (`button-card`,
    `bubble-card`, `card-mod`, `config-template-card`, `week-planner-card`) that are now a
    **manual HACS prerequisite, not vendored** — see SETUP.md's Prerequisites section for the
    exact versions to install. They used to be bundled directly under a `www/vendor/`
    directory (removed 2026-07-26); reversed on a live-reported real risk, not a style
    preference: none of the five guard their own `customElements.define(...)` call with an
    existence check first (confirmed by reading each one directly), so a user who already had
    any of them installed separately for their own other dashboards would end up with two
    copies racing to register the same custom element — the loser throws an uncaught console
    error and silently never takes effect, and for `week-planner-card` specifically, this
    integration's own calendar behavior depends on the *exact* pinned v1.14.1's filter-
    matching internals (see `modules/calendar/dashboard.py`'s own docstring), so a
    differently-versioned copy silently winning that race could break the calendar in a way
    that has nothing to do with this integration's own code. See `assets.py`'s and
    `dashboard/register.py`'s module docstrings for the full history of this reversal.
- `tests/` — pytest-homeassistant-custom-component suite, one file per module/flow/concern:
  `test_config_flow.py`, `test_dashboard.py`, `test_assets.py`, `test_util.py`,
  `test_roster.py`, `test_unmapped_users.py`, `test_notify_resolution.py`,
  `test_holidays_setup.py`, and per-module `test_<module>_module.py` plus targeted
  `test_<module>_<concern>.py` files for behavior that doesn't fit the main module test file
  (e.g. `test_calendar_extras.py`, `test_birthdays_calendar.py`, `test_chores_crud.py`,
  `test_chores_scheduling.py`).
- `claude-code-kickoff.md` — where to start; links to the full planning docs (build brief,
  architecture/rebuild plan, wizard flowchart) at
  `C:\Users\philt\CLAUDE_FOLDER\Family Dashboard Mockups\`. Those docs are living and
  user-edited — reread them fresh before dashboard/config-flow work rather than relying on
  what a past session summarized.
- `dev.env` (gitignored) — `HA_URL` + Long-Lived Access Token for the live test instance.

## Working with the integration

- The config flow's step handlers that build/parse per-roster-member form data
  (`build_*_schema`/`parse_*_input` in `config_flow.py`) are plain module-level functions,
  not methods, so `FamilyDashboardOptionsFlow` can reuse them pre-filled from an existing
  config entry instead of duplicating the forms — keep new steps following this shape.
- Roster members are the unit almost everything else hangs off: each carries its own
  `member_id` (stable, generated once, never re-derived from a display-name edit — see
  `util.slugify_unique`'s docstring), `color`, `avatar`, `features` (which of Calendar/
  Lists/Chores & Rewards they've opted into), and optional `ha_user_id` (links them to an
  HA user account for a personal dashboard view). Settings/Roster itself is always-on, not
  a toggle. Disabling a feature via the Options Flow must hide that member's entities
  (`hidden_by` in the entity registry), never delete them — deleting data is a deliberately
  separate, not-yet-built action.
- HA core has no generic "user" selector — picking an existing HA account in a config flow
  means fetching `hass.auth.async_get_users()` yourself and building a `select` selector
  from the (active, non-system-generated) results, not `selector({"user": {}})`. The same
  filter is reused by `dashboard/registry.py`'s Kiosk-bucket computation.
- `has_entity_name = True` combined with a shared per-config-entry `device_info` (as
  `modules/settings/` uses) means generated `entity_id`s are `<device_name>_<entity_name>`
  slugified (e.g. `select.family_dashboard_ada_color`), not just the entity's own name —
  worth knowing before hand-writing an expected entity_id in a new test.
- No blocking I/O in entity properties, and state-change listeners need `@callback` — pytest
  won't catch a violation of either, but live HA logs will. Check the live container's logs
  after any entity-property or listener change, not just green tests.
- Generated Lovelace card configs are only verified once seen actually rendering in a real
  browser with the console open — a config that looks structurally right (right keys,
  valid-looking JSON) can still fail silently or throw a JS template error client-side (e.g.
  `custom:button-card` JS templates, `card_mod` selectors reaching into shadow DOM). Don't
  call dashboard-generation work done off the generated config alone.
