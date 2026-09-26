# Chore scheduling, per-instance claims, and claim reset — design

Date: 2026-09-26. Status: approved in conversation, pending spec review.

## Problem

- Chores have a `frequency` (Daily / Weekly / One-time) that nothing reads, and an optional
  `schedule_days` that is typed as free text ("Mon, Wed, Fri") and only hides the tile on
  other days. There's no monthly option and no way to pick days.
- A task sensor goes `idle → claimed → approved/denied` and never returns to `idle`, so one
  approval completes a chore for all time. Rewards have the same problem: one redemption ever.
- The only way to undo a claim is Deny, which needs a reason and writes to the Logbook.

## Goals

1. A chore recurs on chosen **days of the week** or **days of the month**, or is **one-time**,
   picked with tap-to-toggle pills, never typed.
2. Each scheduled day is its own instance: a claim covers that instance only.
3. A parent can **reset** a mistaken pending claim back to unclaimed, with no reason.
4. An approved reward is immediately redeemable again.

Non-goals: claim history or streaks; tracking missed instances; "weekday of the month"
schedules (e.g. first Saturday); schedules on rewards; kids undoing their own claims; reset
reversing an approval (Adjust Points covers that).

## Decisions (from the design conversation)

| Question | Decision |
|---|---|
| Weekly with days picked | Each scheduled day is its own instance ("Weekly Mon, Thu" = claimable Mon and Thu) |
| Monthly | Day numbers 1–31; a day past the month's end falls on its last day |
| Claim unreviewed at the day boundary | Stays pending until reviewed; when reviewed, resets to idle immediately if a newer due day has started |
| Reset scope | Pending claims only |
| Rewards after approval | Immediately available again |
| Picker | Repeat dropdown + tap-to-toggle pills (7 weekdays / 1–31 grid) |
| Architecture | Integration owns the schedule (approach 1) |
| Existing "weekly" chore with no days | Becomes days-of-week, Sunday only |

## 1. Stored data

Each chore in `entry.data["chores"]` keeps `chore_id`, `name`, `points`, `assigned_to`, and
replaces `frequency` with:

- `repeat`: `"days_of_week"` | `"monthly"` | `"one_time"`
- `schedule_days`: list of lowercase weekday names (existing field and format). Absent or
  empty means every day. Used only when `repeat == "days_of_week"`.
- `month_days`: sorted list of unique ints 1–31, at least one. Used only when
  `repeat == "monthly"`.

Month-end rule: for each picked day `d`, the due date in a month is `min(d, last day of that
month)`. Picking both 30 and 31 still yields one instance in a 30-day month (dates are a set).

`const.CHORE_FREQUENCIES` is replaced by a `CHORE_REPEATS` mapping (key → display name) used
by the Repeat dropdowns.

### Upgrading existing chores

Runs once in `async_setup_entry` before platforms are forwarded; if any chore changed, the
result is written back with `async_update_entry` (no reload, since setup is already running).
A chore that already has `repeat` is left alone, so it's idempotent.

| Old | New |
|---|---|
| `frequency: daily` (any `schedule_days`) | `repeat: days_of_week`, same `schedule_days` |
| `frequency: one_time` | `repeat: one_time` |
| `frequency: weekly` with `schedule_days` | `repeat: days_of_week`, same `schedule_days` |
| `frequency: weekly`, no `schedule_days` | `repeat: days_of_week`, `schedule_days: ["sunday"]` |
| missing/unknown `frequency` | `repeat: days_of_week`, same `schedule_days` |

`frequency` is dropped from the stored chore after upgrading.

## 2. Schedule logic — `modules/chores/schedule.py` (new, no HA imports)

Pure functions on a chore dict and `datetime.date`:

- `is_due(chore, day) -> bool` — `one_time` always true; `days_of_week` true if
  `schedule_days` is empty or contains the weekday; `monthly` true if `day` is one of that
  month's due dates under the month-end rule.
- `due_day_started_since(chore, since, today) -> bool` — true if any date in
  `(since, today]` is due. `one_time` always false. Every recurring chore has a due date in
  any 31-day span, so a gap of 31+ days returns true without scanning; shorter gaps are
  checked date by date.
- `describe(chore) -> str` — the Schedule pill text: "Every day", "Mon, Thu",
  "Monthly: 1, 15", "One-time". Replaces `util.format_schedule_days` for chores.
- Token helpers for the picker: `parse_tokens(repeat, text) -> list` and
  `toggle_token(text, token) -> str`, where the scratch text is a comma-separated list of
  weekday keys (`mon,thu`) or day numbers (`1,15`), kept sorted and de-duplicated.

## 3. Task sensor lifecycle — `modules/chores/sensor.py`

Statuses are unchanged: `idle`, `claimed`, `approved`, `denied`. New attributes on chore
sensors:

- `due_today`: bool, from `schedule.is_due(chore, today)`.
- `claimed_on`: ISO date of the instance being claimed, or absent.

Actions:

- **claim**: allowed from `idle` or `denied` when `due_today` (rewards: always). Sets
  `claimed_on = today`. Otherwise raises `HomeAssistantError`: "'X' isn't due today" or
  "'X' is already approved for today" / "…already claimed".
- **approve**: unchanged points behaviour. Chores: then run the instance check (below).
  Rewards: go straight to `idle`.
- **deny**: unchanged reason + Logbook. Then run the instance check.
- **reset** (new, `family_dashboard.reset_claim`, entity service on the task sensor):
  allowed only from `claimed` → `idle`, clears `claimed_on`, no Logbook entry. Otherwise
  raises "'X' has no pending claim to reset". Works for chores and rewards.

Instance check (after approve/deny, at the day boundary, and at startup): a recurring chore
in `approved` or `denied` goes to `idle` (clearing `claimed_on`) when
`schedule.due_day_started_since(chore, claimed_on, today)`. `claimed` is never changed by
it. `one_time` chores never change by it.

Day boundary: each chore task sensor listens with `async_track_time_change` at 00:00:05
local (same moment as the existing Day Of Week sensor), recomputes `due_today`, runs the
instance check, and writes state. The listener is registered in `async_added_to_hass` and
removed in `async_will_remove_from_hass`; the callback is `@callback`-safe (no blocking I/O).

Restore: status and `claimed_on` are restored from the last state. Upgrade case: a restored
`approved`/`denied` recurring chore with no `claimed_on` is treated as stale and goes to
`idle` on a day it's due. `one_time` chores keep their restored status.

## 4. Picker — entities and service

- Repeat dropdowns (select entities): the existing Add Chore frequency select becomes the
  Add Chore **Repeat** select (options from `CHORE_REPEATS`); a new shared **Schedule Repeat**
  select backs the Edit popup. Both are scratch fields, like the existing ones.
- Day selections live in the existing scratch text entities: Add Chore's
  `new_chore_schedule`, and the shared `chore_schedule_scratch` for Edit.
- Changing a Repeat select clears its paired text (weekday tokens and day numbers don't mix).
- New service `family_dashboard.toggle_schedule_day` targeting one of those two text
  entities, with field `value` (a weekday key or day number). It calls
  `schedule.toggle_token` and writes the result.
- Save: `add_chore` and `set_chore_schedule_days` read Repeat + text via
  `schedule.parse_tokens`. Monthly with no days raises "Pick at least one day of the month".
  Both clear their scratch fields after saving.
- The per-chore Frequency select entities (`ChoreFrequencySelect`) are removed: no longer
  created, and their registry entries are removed at setup.

## 5. Dashboard — `modules/chores/dashboard.py`

- **Kid chore tiles**: one conditional card per chore, shown when the task sensor's
  `due_today` attribute is `true` **or** its state is `claimed`. Replaces the
  one-conditional-per-weekday construction. (Verified: the live frontend's state condition
  supports `attribute`, `state_not`, and list values; the `or` wrapper is to be confirmed in
  the browser during implementation.)
- **Management row**: Frequency pill removed; the Schedule pill shows `schedule.describe()`
  and opens the Edit popup.
- **Edit popup** and **Add Chore popup**: Repeat dropdown, then conditionally either 7
  weekday pills (hint: "None picked = every day") or a 1–31 grid, or nothing for One-time.
  Pills are `custom:button-card`s whose tap calls `toggle_schedule_day` with a fixed value
  and whose lit style comes from the scratch text's state.
- **Edit popup pre-fill**: it must open showing the chore's current schedule. Mechanism to be
  proven in the browser before it's written into the plan (one tap can't reliably both call a
  service and open a popup).
- **Parent Review**: a **Reset** button beside Approve/Deny for each claimed chore and reward,
  visible only while that item is `claimed`, calling `family_dashboard.reset_claim`.
- `services.yaml`, `strings.json`, and `translations/en.json` gain `reset_claim` and
  `toggle_schedule_day` (the latter two files kept byte-identical).

The Day Of Week sensor is kept (harmless, useful for automations) but no longer used by the
dashboard.

## 6. Testing

- `schedule.py`: pure unit tests — every repeat type; month-end (31st in April, 29–31 in
  February, leap year); 30+31 in a 30-day month; `due_day_started_since` across week and
  month gaps and HA-was-off gaps; token parse/toggle.
- Task sensor: claim refused on non-due days and when already approved; approve/deny
  followed by the instance check; reset only from claimed; rewards back to idle on approve;
  midnight rollover (freezer) including a claimed chore surviving it; startup catch-up from
  restored state, including the stale no-`claimed_on` upgrade case.
- Upgrade: each row of the upgrade table; idempotent on a second setup.
- Service: `toggle_schedule_day` adds/removes/sorts; Repeat change clears the text; Save
  validation for monthly-with-no-days.
- Dashboard config: one conditional per chore with the right conditions; no Frequency pill;
  Reset present in Parent Review.
- Live bench: walk a days-of-week and a monthly chore through claim → approve → next due
  day (driving the clock via the instance check, not by waiting); Reset from Parent Review;
  reward approve returns to idle. Browser (kiosk): pills toggle and light correctly, popups
  pre-fill, no console errors; check HA logs for errors.
