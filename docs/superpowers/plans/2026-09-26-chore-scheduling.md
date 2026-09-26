# Chore Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chores recur on picked weekdays, month days, or once; each due day is its own
claimable instance; parents can reset a mistaken claim; approved rewards are redeemable again.

**Architecture:** A pure `modules/chores/schedule.py` owns all date logic and the picker's
token format. The task sensor gains `due_today`/`claimed_on` and runs an "instance check" at
midnight, at startup, and after review. The picker is scratch entities + a
`toggle_schedule_day` service, rendered as button-card pills; the Edit popup pre-fills via
Bubble Card's pop-up `open_action` calling `load_chore_schedule`.

**Tech Stack:** Home Assistant custom integration (Python 3.14 in tests, HA 2026.7.2 live),
pytest-homeassistant-custom-component, Lovelace `custom:button-card` + `custom:bubble-card`.

**Spec:** `docs/superpowers/specs/2026-09-26-chore-scheduling-design.md`

## Global Constraints

- Repeat keys: `days_of_week`, `monthly`, `one_time`; labels "Days of week", "Monthly", "One-time".
- `schedule_days`: lowercase full weekday names, Monday→Sunday order; empty/absent = every day.
- `month_days`: sorted unique ints 1–31, at least one for `monthly`; day past month end → last day.
- Old `weekly` with no days → `days_of_week`, `["sunday"]`.
- Statuses stay `idle`/`claimed`/`approved`/`denied`; reset only from `claimed`.
- Day boundary at 00:00:05 local, `dt_util.now().date()` for "today".
- Picker scratch text format: comma-separated tokens, weekday keys `mon`..`sun` or day
  numbers `1`..`31`, canonical order, no duplicates.
- Every new entity goes through the platform shims (`entity_ids.pin_entity_ids`).
- `strings.json` and `translations/en.json` stay byte-identical.
- Tests: `MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD:/app" -w /app python:3.14-slim bash -c "pip install -q -r requirements_test.txt && python -m pytest tests/ -q"`.

## Review Focus

1. A monthly chore on the 31st in a 30-day month and in February (leap and non-leap) must be
   due on the month's last day, exactly once. → Task 1 tests.
2. HA off across one or more due days: a chore approved before the gap is claimable when HA
   comes back. → Task 3 test `test_startup_catch_up_after_gap`.
3. A chore claimed on its last due day of the week, reviewed days later, must not stay stuck:
   it resets on review if a newer due day started, otherwise waits. → Task 3 tests.
4. Switching Repeat after tapping pills must not save weekday tokens as month days (or the
   reverse). → Task 4 test `test_repeat_change_clears_days`.
5. Existing installs: chores with only `frequency`, and task sensors stuck `approved` with no
   `claimed_on`, must upgrade without losing points. → Tasks 2 and 3 tests.

---

## File map

- Create `custom_components/family_dashboard/modules/chores/schedule.py` — dates + tokens.
- Create `custom_components/family_dashboard/modules/chores/upgrade.py` — one-time data upgrade
  and retired-entity cleanup, called from `__init__.async_setup_entry` before forwarding.
- Modify `const.py` — `CHORE_REPEATS` replaces `CHORE_FREQUENCIES`.
- Modify `modules/chores/crud.py` — add/update/save use repeat fields; drop frequency.
- Modify `modules/chores/select.py` — remove `ChoreFrequencySelect`; `NewChoreRepeatSelect`
  and `ChoreScheduleRepeatSelect` (both clear their paired text on change).
- Modify `modules/chores/text.py` — `toggle_schedule_day` on the two scratch texts.
- Modify `modules/chores/sensor.py` — lifecycle, midnight listener, `reset_claim`,
  `load_chore_schedule`, save via tokens.
- Modify `modules/chores/dashboard.py` — kid tile conditional, pills, popups, Reset.
- Modify `config_flow.py` — wizard/options chore form: repeat + weekday/month-day multi-selects.
- Modify `services.yaml`, `strings.json`, `translations/en.json`.
- Modify `util.py` — remove `parse_schedule_days_text`/`format_schedule_days` (replaced).
- Tests: create `tests/test_chore_schedule.py`, `tests/test_chore_lifecycle.py`; update
  `tests/test_chores_crud.py`, `test_chores_module.py`, `test_chores_scheduling.py`,
  `test_config_flow.py`, `test_dashboard.py`, `test_entity_ids.py`, `test_util.py`.

---

### Task 1: Pure schedule module

**Files:** Create `modules/chores/schedule.py`, `tests/test_chore_schedule.py`; modify `const.py`.

**Produces:**
- `REPEAT_DAYS_OF_WEEK = "days_of_week"`, `REPEAT_MONTHLY = "monthly"`, `REPEAT_ONE_TIME = "one_time"`
- `WEEKDAY_KEYS = ("mon", ..., "sun")`; `WEEKDAYS` full names (from util).
- `is_due(chore: dict, day: date) -> bool`
- `due_day_started_since(chore: dict, since: date, today: date) -> bool`
- `describe(chore: dict) -> str`
- `toggle_token(repeat: str, text: str, token: str) -> str` (raises `ValueError` for a token
  that doesn't belong to `repeat`)
- `tokens_to_schedule(repeat: str, text: str) -> dict` → `{"repeat", "schedule_days"?, "month_days"?}`
  (raises `ValueError("Pick at least one day of the month")` for monthly with no days)
- `chore_to_tokens(chore: dict) -> str`
- `upgrade_chore(chore: dict) -> dict` (spec §1 table; returns the same dict object if already upgraded)
- `const.CHORE_REPEATS = {"days_of_week": "Days of week", "monthly": "Monthly", "one_time": "One-time"}`

- [ ] Step 1: tests (all pure):

```python
from datetime import date
from custom_components.family_dashboard.modules.chores import schedule as s

W = lambda *d: {"repeat": "days_of_week", "schedule_days": list(d)}
M = lambda *d: {"repeat": "monthly", "month_days": list(d)}
ONE = {"repeat": "one_time"}

def test_days_of_week_empty_means_every_day():
    assert all(s.is_due(W(), date(2026, 9, d)) for d in range(21, 28))

def test_days_of_week_only_picked_days():
    c = W("monday", "thursday")
    assert s.is_due(c, date(2026, 9, 21)) and s.is_due(c, date(2026, 9, 24))
    assert not s.is_due(c, date(2026, 9, 22))

def test_monthly_31st_falls_on_last_day():
    c = M(31)
    assert s.is_due(c, date(2026, 4, 30)) and not s.is_due(c, date(2026, 4, 29))
    assert s.is_due(c, date(2026, 2, 28)) and s.is_due(c, date(2028, 2, 29))
    assert not s.is_due(c, date(2028, 2, 28))

def test_monthly_30_and_31_one_instance_in_short_month():
    c = M(30, 31)
    assert [d for d in range(1, 31) if s.is_due(c, date(2026, 4, d))] == [30]

def test_one_time_always_due_never_restarts():
    assert s.is_due(ONE, date(2026, 1, 1))
    assert not s.due_day_started_since(ONE, date(2026, 1, 1), date(2027, 1, 1))

def test_due_day_started_since():
    c = W("monday", "thursday")
    mon, tue, thu = date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 24)
    assert not s.due_day_started_since(c, mon, mon)
    assert not s.due_day_started_since(c, mon, tue)
    assert s.due_day_started_since(c, mon, thu)
    assert s.due_day_started_since(M(15), date(2026, 1, 1), date(2026, 3, 1))  # 31+ day gap

def test_describe():
    assert s.describe(W()) == "Every day"
    assert s.describe(W("monday", "thursday")) == "Mon, Thu"
    assert s.describe(M(1, 15)) == "Monthly: 1, 15"
    assert s.describe(ONE) == "One-time"

def test_toggle_token_sorts_and_dedupes():
    assert s.toggle_token("days_of_week", "thu", "mon") == "mon,thu"
    assert s.toggle_token("days_of_week", "mon,thu", "mon") == "thu"
    assert s.toggle_token("monthly", "15", "1") == "1,15"

def test_toggle_token_rejects_wrong_kind():
    import pytest
    with pytest.raises(ValueError):
        s.toggle_token("monthly", "", "mon")
    with pytest.raises(ValueError):
        s.toggle_token("days_of_week", "", "32")

def test_tokens_to_schedule_round_trip():
    assert s.tokens_to_schedule("days_of_week", "mon,thu") == {
        "repeat": "days_of_week", "schedule_days": ["monday", "thursday"]}
    assert s.tokens_to_schedule("days_of_week", "") == {"repeat": "days_of_week"}
    assert s.tokens_to_schedule("monthly", "15,1") == {"repeat": "monthly", "month_days": [1, 15]}
    assert s.tokens_to_schedule("one_time", "mon") == {"repeat": "one_time"}
    assert s.chore_to_tokens(M(1, 15)) == "1,15"
    assert s.chore_to_tokens(W("monday", "thursday")) == "mon,thu"

def test_tokens_to_schedule_monthly_needs_a_day():
    import pytest
    with pytest.raises(ValueError, match="at least one day"):
        s.tokens_to_schedule("monthly", "")

def test_upgrade_chore_table():
    base = {"chore_id": "t", "name": "T", "points": 1, "assigned_to": None}
    up = lambda **kw: s.upgrade_chore({**base, **kw})
    assert up(frequency="daily") == {**base, "repeat": "days_of_week"}
    assert up(frequency="daily", schedule_days=["monday"]) == {
        **base, "repeat": "days_of_week", "schedule_days": ["monday"]}
    assert up(frequency="one_time") == {**base, "repeat": "one_time"}
    assert up(frequency="weekly", schedule_days=["friday"]) == {
        **base, "repeat": "days_of_week", "schedule_days": ["friday"]}
    assert up(frequency="weekly") == {**base, "repeat": "days_of_week", "schedule_days": ["sunday"]}
    assert up() == {**base, "repeat": "days_of_week"}
    already = {**base, "repeat": "monthly", "month_days": [3]}
    assert s.upgrade_chore(already) is already
```

- [ ] Step 2: run, expect ImportError/fail.
- [ ] Step 3: implement `schedule.py` (calendar.monthrange for month length; due dates per
  month = `{min(d, last) for d in month_days}`; `due_day_started_since` returns True when
  `(today - since).days >= 31` for recurring chores, else scans `since+1 .. today`).
  Add `CHORE_REPEATS` to `const.py` (keep `CHORE_FREQUENCIES` until Task 2 removes its users).
- [ ] Step 4: run, all pass. Step 5: commit "Add pure chore schedule module".

### Task 2: Stored data — upgrade, CRUD, retired entities, wizard

**Files:** Create `modules/chores/upgrade.py`; modify `__init__.py`, `crud.py`, `select.py`,
`config_flow.py`, `strings.json`, `translations/en.json`, `const.py`, `util.py`,
`modules/chores/__init__.py` docstring; tests as listed.

**Consumes:** `schedule.upgrade_chore`, `CHORE_REPEATS`, `tokens_to_schedule`.
**Produces:**
- `upgrade.async_upgrade_chores(hass, entry) -> None` — rewrites `entry.data["chores"]` via
  `upgrade_chore` when anything changed (`async_update_entry`, no reload), and removes
  registry entries for unique_ids `f"{entry_id}_{chore_id}_frequency"` and
  `f"{entry_id}_new_chore_frequency"`.
- `crud.async_add_chore(hass, entry, *, name, points, assigned_to, repeat="days_of_week", schedule_days=None, month_days=None) -> str`
- `crud.chore_field_entity_ids` no longer lists the frequency select.
- `select.NewChoreRepeatSelect` (unique `f"{entry_id}_new_chore_repeat"`, name "New Chore Repeat",
  default "Days of week") and `select.ChoreScheduleRepeatSelect` (unique
  `f"{entry_id}_chore_schedule_repeat"`, name "Chore Schedule Repeat"); both clear their paired
  scratch text (`new_chore_schedule` / `chore_schedule_scratch`) on change.
- Wizard/options chore form fields: `repeat` (vol.In CHORE_REPEATS), `weekdays`
  (cv.multi_select of Mon..Sun labels, optional), `month_days` (cv.multi_select "1".."31",
  optional); monthly with none → form error `month_days_required`.

- [ ] Step 1: tests —
  - `test_upgrade_rewrites_legacy_chores_and_is_idempotent` (setup with legacy `frequency`
    chores; assert stored chores match `upgrade_chore`; second setup leaves data object equal).
  - `test_upgrade_removes_retired_frequency_selects` (pre-register
    `select` unique `..._trash_frequency`; after setup it's gone from the registry).
  - `test_add_chore_stores_repeat_fields` (monthly `[1, 15]`, no `frequency` key).
  - config flow: `test_wizard_chore_monthly_requires_days` and
    `test_wizard_chore_days_of_week_stored` (weekdays ["Mon","Thu"] →
    `schedule_days ["monday","thursday"]`).
  - Update existing tests asserting `frequency` in stored data / the `*_frequency` selects to
    the new shape.
- [ ] Step 2: run, expect failures.
- [ ] Step 3: implement. Call `async_upgrade_chores` in `async_setup_entry` right after
  `hass.data` init, before forwarding. Remove `ChoreFrequencySelect`, `CHORE_FREQUENCIES`,
  `util.parse_schedule_days_text`/`format_schedule_days` (+ their tests).
- [ ] Step 4: full suite green. Step 5: commit.

### Task 3: Task sensor lifecycle + reset

**Files:** modify `modules/chores/sensor.py`, `services.yaml`; create `tests/test_chore_lifecycle.py`.

**Consumes:** `schedule.is_due`, `schedule.due_day_started_since`.
**Produces:** sensor attributes `repeat`, `due_today`, `claimed_on` (ISO str, chores only);
entity service `reset_claim` (no fields) → `async_reset_claim`.

Behaviour (spec §3): claim only from idle/denied and (chores) when due today, sets
`claimed_on`; approve/deny then instance check; reward approve → idle; reset only from
claimed; midnight `async_track_time_change(hour=0, minute=0, second=5)` with a `@callback`
handler that recomputes `due_today`, runs the instance check, writes state; restore status +
`claimed_on`; stale approved/denied with no `claimed_on` → idle when due today.

- [ ] Step 1: tests (use `freezer` to set dates; weekday chore Mon/Thu):
  `test_claim_refused_when_not_due`, `test_claim_sets_claimed_on_and_refuses_double_claim`,
  `test_approve_same_day_stays_approved_until_next_due_day` (freeze Mon, approve, tick to
  Tue 00:00:06 → still approved, tick to Thu 00:00:06 → idle),
  `test_claimed_survives_midnight`, `test_late_review_resets_immediately` (claim Mon, freeze
  Thu, approve → points awarded and state idle),
  `test_late_review_waits_if_no_new_due_day` (claim Mon, approve Tue → approved),
  `test_denied_is_reclaimable_same_day`, `test_reset_claim_only_from_claimed`,
  `test_reward_approve_returns_to_idle_and_deducts`,
  `test_startup_catch_up_after_gap` (mock_restore_cache approved with claimed_on a week ago → idle),
  `test_stale_approved_without_claimed_on_upgrades_to_idle`,
  `test_one_time_approved_stays_approved`.
- [ ] Step 2: fail. Step 3: implement + `services.yaml` `reset_claim`. Step 4: green. Step 5: commit.

### Task 4: Picker backend

**Files:** modify `modules/chores/text.py`, `select.py`, `sensor.py`, `crud.py`,
`services.yaml`; tests in `tests/test_chores_scheduling.py` (rewrite).

**Produces:** entity services `toggle_schedule_day` (text; field `value: str`) and
`load_chore_schedule` (sensor; no fields). `set_chore_schedule_days` and `add_chore` read
Repeat select + scratch text via `tokens_to_schedule`; monthly with no days raises
`HomeAssistantError("Pick at least one day of the month")`; both clear scratch afterwards.

- [ ] Step 1: tests — `test_toggle_schedule_day_adds_and_removes`,
  `test_toggle_rejects_token_of_other_kind`, `test_repeat_change_clears_days`,
  `test_load_chore_schedule_fills_scratch` (monthly [1,15] → select "Monthly", text "1,15"),
  `test_set_schedule_saves_monthly`, `test_set_schedule_monthly_without_days_raises`,
  `test_add_chore_from_scratch_uses_repeat_and_days`.
- [ ] Step 2–5: fail, implement, green, commit.

### Task 5: Dashboard

**Files:** modify `modules/chores/dashboard.py`; tests in `tests/test_dashboard.py`.

Card shapes:
- Kid tile: `{"type": "conditional", "conditions": [{"condition": "or", "conditions": [
  {"condition": "state", "entity": S, "attribute": "due_today", "state": "true"},
  {"condition": "state", "entity": S, "state": "claimed"}]}], "card": tile}` — one per chore.
- Weekday pill (button-card): name "Mon", tap `perform-action`
  `family_dashboard.toggle_schedule_day`, target the scratch text, data `{"value": "mon"}`;
  background via `[[[ return (states[T]?.state || '').split(',').includes('mon') ? 'var(--primary-color)' : 'rgba(255,255,255,0.7)' ]]]`.
- Picker block: conditional on Repeat select state "Days of week" → horizontal-stack of 7
  pills + markdown hint "None picked = every day"; conditional on "Monthly" → `grid`
  (columns 7, square false) of 31 pills.
- Edit popup: bubble-card pop-up `#schedule-<id>` with `open_action` perform-action
  `family_dashboard.load_chore_schedule` targeting the chore sensor; Repeat select entity row;
  picker block; Save button (existing `set_chore_schedule_days`).
- Add Chore popup: entities (Name, Points, Repeat, Assigned To) + picker block + Add button.
- Management row: drop Frequency pill; Schedule pill name `f"Schedule: {describe(chore)}"`.
- Parent Review: Reset button-card beside Approve calling `family_dashboard.reset_claim`.

- [ ] Step 1: tests — config-shape tests for each bullet. Step 2: fail. Step 3: implement.
- [ ] Step 4: green. Step 5: browser-verify on the bench (kiosk): `or` conditional shows/hides
  tiles; pills toggle and light; Edit popup pre-fills via `open_action`; Reset works; no
  console errors (beyond the known bubble-modules.yaml 404). Step 6: commit.

### Task 6: Docs + live validation

- [ ] Update CLAUDE.md "Chores module specifics", SETUP.md if it mentions schedules/frequency,
  `modules/chores/__init__.py` and `dashboard.py` docstrings.
- [ ] Live bench: deploy; confirm "bla blahj" (weekly, no days) upgraded to Sunday; walk a
  days-of-week and monthly chore through claim → approve → instance check; Reset; reward
  approve → idle; HA logs clean. Commit.
