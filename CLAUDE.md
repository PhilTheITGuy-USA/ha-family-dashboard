# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The `family_dashboard` Home Assistant custom integration (repo: `ha-family-dashboard`,
installed via HACS). **Status: beta** — feature-complete against the v1 plan, not yet declared
stable. Deliberately deferred (not gaps): a Meals module, and importing from a legacy
`ha-family-hub` install (`migration/` is a stub).

Layout:

- `custom_components/family_dashboard/` — the integration (the only thing HACS ships).
- `tests/`, `pytest.ini`, `requirements_test.txt` — the pytest suite.
- `README.md` (HACS-rendered), `SETUP.md` (end-user setup guide), `hacs.json`.
- `testbench/` — the local HA test instance. Only `testbench/docker-compose.yml` is tracked;
  everything else there is gitignored local state: `config/` (HA's live `/config`),
  `config.base-snapshot.tar.gz`, `dev.env` (`HA_URL` + `HA_TOKEN` long-lived token),
  `screenshots/`, and `claude-code-kickoff.md` (the original project brief, which links to the
  living planning docs in `C:\Users\philt\CLAUDE_FOLDER\Family Dashboard Mockups\` — those are
  user-edited, reread them fresh before dashboard/config-flow work).

## Test bench (live HA in Docker)

You have a real Home Assistant instance to test against: container `ha-test-bench`
(`ghcr.io/home-assistant/home-assistant:stable`, with `testbench/config/` bind-mounted as
`/config`), http://localhost:8123, timezone `America/New_York`. Use it; don't
stop at green pytest.

```bash
docker compose -f testbench/docker-compose.yml up -d
docker compose -f testbench/docker-compose.yml restart   # pick up custom_components changes
docker compose -f testbench/docker-compose.yml logs -f
source testbench/dev.env                                  # $HA_URL, $HA_TOKEN for REST/WS calls
```

The base state is roster Phil/Lhen/Tristan/Harlee; HA users dunsel (owner), Marcus, and
Kiosk (password `kiosk`); `calendar.family`/`calendar.ava` fixtures; US/Philippines Holiday
entries; family_dashboard installed and configured. To restore it: `down`, rename
`testbench/config/`, `tar -xzf config.base-snapshot.tar.gz` inside `testbench/`, `up -d`.
To make the current state the new base, `stop` the container first (the SQLite recorder and
`.storage` JSON can be mid-write), then `tar -czf` and `start`. The snapshot contains the
real auth DB and token, so it's never committed.

### Live validation (required before calling any change done)

A predecessor project shipped 13/13 passing tests and still failed its first real install.
After tests pass:

1. Copy the integration onto the bench and restart:
   `rm -rf testbench/config/custom_components/family_dashboard && cp -r custom_components/family_dashboard testbench/config/custom_components/`
   (replace rather than overlay, so deleted files don't linger), then `restart`.
2. Check the container logs for errors. Pytest doesn't catch blocking I/O in entity properties
   or listeners missing `@callback`, but live HA logs do.
3. For config-flow changes, walk every step over REST (`POST /api/config/config_entries/flow`)
   and confirm the results via `GET /api/states` and `GET /api/config/config_entries/entry`,
   not just that the flow calls succeeded.
4. For dashboard changes, check the cards render in a real browser (next section). A
   generated config that looks right can still throw a JS template error or have a `card_mod`
   selector that misses the shadow DOM.

### Browser verification

No browser automation is installed on the host. Run a disposable
`mcr.microsoft.com/playwright/python` container on the `ha-test-bench_default` network, point
it at `http://ha-test-bench:8123`, and log in as a real account: `kiosk`/`kiosk` for the Kiosk
bucket (everyone at once), or a linked roster member's account for a personal bucket. Capture
console errors, and measure layout with `getComputedStyle`/`getBoundingClientRect` rather than
judging from one fixed-wait screenshot. Screenshots have produced false positives here before,
so corroborate against backend state before reporting a live bug. Put screenshots under
`testbench/screenshots/`.

## Running the test suite

`pytest-homeassistant-custom-component` can't run on native Windows (a hardcoded
`pytest_socket.disable_socket` breaks the Proactor loop's self-pipe, and `homeassistant/runner.py`
imports Unix-only `fcntl`). Don't make a host venv. Run it in a disposable Linux container,
using `python:3.14-slim` (3.12-slim's pip fails to resolve the pinned version):

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD:/app" -w /app python:3.14-slim \
  bash -c "pip install -q -r requirements_test.txt && python -m pytest tests/ -v"
# single file / test: narrow the target, e.g. tests/test_config_flow.py::test_name
```

`requirements_test.txt` pins `holidays`/`babel` because `holidays_setup.py` drives HA's
built-in Holiday integration's real config flow under test, and the test container doesn't
auto-install other integrations' manifest requirements. Anything that exercises another
integration's flow needs its requirements added there. The pytest harness caps at an older HA
upstream than the live bench runs, so verify HA-core behavior against the live instance.

## Releasing

Bump `version` in `custom_components/family_dashboard/manifest.json` (currently in the
`1.0.x-betaN` series), keep README's "Status:" line in sync, then tag `vX.Y.Z` and publish a
GitHub Release (mark it pre-release while in beta). `hacs.json` sets the minimum HA version
(2024.6.0).

## Architecture

- **Roster members** are the unit almost everything hangs off. Each has a stable `member_id`
  (generated once and never re-derived from name edits; see `util.slugify_unique`), plus
  `color`, `avatar`, `features` (which of Calendar/Lists/Chores & Rewards they opted into), and
  an optional `ha_user_id` for a personal dashboard view. Settings/Roster is always on.
  Disabling a feature must *hide* that member's entities (`hidden_by` in the entity registry),
  never delete them. `roster.py` holds the mutate+reload helpers for existing members.
- **`const.py`**: domain, the `FEATURES` registry, and colors/avatars. Its docstring records
  which decisions are locked.
- **`config_flow.py`**: the wizard (roster → colors → avatars → birthdates → per-member features
  → link HA users → per-feature sub-flows → confirm) and `FamilyDashboardOptionsFlow`. The
  per-member form builders/parsers (`build_*_schema`/`parse_*_input`) are module-level
  functions so the Options Flow can reuse them pre-filled; keep new steps in that shape. HA has
  no generic user selector, so build a `select` from `hass.auth.async_get_users()` (active,
  non-system). `dashboard/registry.py`'s Kiosk bucket reuses the same filter. Wizard steps stay
  plain dropdowns: no config-flow selector can render a color-swatch or avatar grid.
  `strings.json` and `translations/en.json` are byte-identical and both hand-maintained, so
  edit both.
- **`__init__.py` `async_setup_entry`**: forwards Settings' platforms plus the union of every
  member's feature platforms, seeds static assets (`assets.py` → `/config/www/family_dashboard/`,
  `/config/themes/`), provisions Holidays (`holidays_setup.py`, idempotent and best-effort),
  then builds and registers the dashboard.
- **`modules/<name>/`** (calendar, lists, chores, settings) hold the real entity logic, and
  each may add a `dashboard.py` and its own flow step. Top-level `<platform>.py` files are thin
  shims that call the modules' `async_setup_entry` with `async_add_entities` wrapped in
  `entity_ids.pin_entity_ids` (see Entity IDs below). See `modules/__init__.py`'s docstring
  for the new-module checklist. `modules/settings/` is the reference pattern.
- **`dashboard/`**: `registry.py` generates four uniformly labeled tabs
  (Calendar/Lists/Chores/Settings) for every viewer, and a custom strategy
  (`www/family-dashboard-strategy.js`) swaps per-viewer-bucket *content* client-side. An
  earlier per-person-named-views design was deliberately reverted, so read the docstring first.
  Views need `type: sections` + `subview: true`. `register.py` does storage-mode dashboard and
  resource registration against HA internals that differ by version. Reread its docstring
  before touching registration.
- **`user_watch.py` / `unmapped_users.py`**: `user_watch.py` reloads the entry (debounced)
  when HA user add/update/remove events change Kiosk-bucket membership. `unmapped_users.py`
  raises a Repair Issue per unlinked user, and dismissing one is a permanent per-user opt-out.
- **`services.yaml`**: declares only the schemas for the custom services the dashboard calls
  (task/points/member management, PIN unlock, the `add_event`/`add_chore`/`add_reward`
  popups). Each module registers its own handlers.
- **Entity IDs** are always `<domain>.family_dashboard_<slugified entity name>` (e.g.
  `select.family_dashboard_ada_color`), and the dashboard hardcodes many of them. Left to
  itself, HA derives a new entity's ID from the device's area and current name, so once the
  shared device is assigned to an area or renamed, new entities would come out as
  `select.living_room_family_dashboard_...` and their cards would break. `entity_ids.py`
  prevents that: every top-level platform wraps `async_add_entities` in `pin_entity_ids`,
  which sets each entity's canonical ID from its `_attr_name`, so entity classes don't pin
  IDs themselves (a class that does set `self.entity_id` keeps it). Setup also runs
  `async_repair_prefixed_entity_ids` after the platforms load, renaming any
  `<x>_family_dashboard_<name>` ID back in place so its state carries over. It leaves
  user-customised IDs alone and won't take an ID that's already in use.

### Calendar module specifics

- **Family calendar** is auto-detected: any `calendar.*` entity whose name is exactly "Family"
  (case-insensitive). See `_family_calendar_entity` in `modules/calendar/dashboard.py`. A
  shared calendar with any other name silently won't appear, which SETUP.md warns about.
  Check the entity name before assuming a code bug.
- **Add Event times** use a decomposed Date + Hour(1-12) + Minute + AM/PM group, not HA's
  `datetime` picker, because that picker's 12/24h display follows each viewer's profile and a
  shared kiosk can't rely on it. `event_time.py` owns the field IDs and the start→end
  recompute, which goes through real `datetime` so midnight rollover is correct.
- **Recurring events** call the calendar entity's `async_create_event` directly (`events.py`)
  because the `calendar.create_event` service schema has no `rrule`. That means replicating
  the service's `CREATE_EVENT` support check (`_resolve_calendar_entity`) and returning
  timezone-*aware* datetimes (`dt_util.as_local`).
- **Kiosk fit**: the whole Kiosk view must fit a 1920x1080 display without scrolling. The
  numbers in `_CARD_MOD_STYLE` / `_WEEK_PLANNER_STATIC_OPTIONS` (card height
  `calc(100vh - 240px)`, capped per-day event lists, overridden `--event-padding`) were
  live-measured and documented inline. Re-measure in a browser before changing them.

### Chores module specifics

- Chores & Rewards management sits behind the Parent PIN on the Chores tab, not on Settings.
- A chore's schedule is `repeat` (`days_of_week` / `monthly` / `one_time`) plus
  `schedule_days` (none = every day) or `month_days` (a day past the month's end falls on its
  last day). All date logic lives in the HA-free `modules/chores/schedule.py`. Old
  `frequency` data is upgraded once at setup (`modules/chores/upgrade.py`; weekly with no day
  becomes Sunday).
- Each due day is its own instance. The task sensor only allows a claim on a due day, records
  `claimed_on`, and sends an approved/denied chore back to `idle` once a newer due day
  starts: at 00:00:05 local, at startup, and right after a late review. A claim awaiting
  review is never reset by the clock. Approved rewards go straight back to `idle`.
  `reset_claim` undoes a pending claim.
- Kid tiles are one conditional per chore: its Due Today binary sensor is on, or it's
  claimed (one-time chores also hide once approved). Don't switch this to the task sensor's `due_today` attribute: dashboard conditions
  only match attributes from HA 2026.5 on, and the integration supports back to 2024.6. The
  schedule pickers are scratch entities (a Repeat select plus a days text holding tokens like
  `mon,thu` or `1,15`) toggled by `toggle_schedule_day`. The Edit popup pre-fills via Bubble
  Card's pop-up `open_action` calling `load_chore_schedule`.
- Splitting a chore across kids means one chore record per kid, because `assigned_to` is
  fixed per record.

### Third-party Lovelace cards

The dashboard needs `button-card`, `bubble-card`, `card-mod`, `config-template-card`, and
`week-planner-card` (pinned v1.14.1, since the calendar relies on its filter internals). Users
install them as a manual HACS prerequisite; SETUP.md lists the tested versions. Don't re-vendor
them: none guard `customElements.define`, so a duplicate copy races and breaks (history in
`assets.py`/`dashboard/register.py` docstrings). Keep SETUP.md in sync when card versions or
the Family-calendar naming rule change.
