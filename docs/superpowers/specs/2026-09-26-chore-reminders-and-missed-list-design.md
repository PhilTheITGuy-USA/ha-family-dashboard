# Chore reminders and the missed-chores list — design

Date: 2026-09-26. Status: approved; implemented. See "Refinements during implementation" at the end.

## Problem

- Nothing nudges a kid who hasn't done today's chores. Parents have to chase them.
- Once a due day passes, an unclaimed chore just stays `idle`. Nothing records that the day
  was missed, so parents can't see a pattern ("Tristan skipped Dishes three times this week").

## Goals

1. Per chore, a parent can turn on **reminders**: a phone notification at **4:00, 6:00 and
   7:00 PM** local time for each due-today chore that isn't claimed yet, sent only if the
   assigned kid has a phone registered in HA.
2. A **missed-chores list** in the parent view: each due day that ended with the chore never
   claimed, or denied and not redone.
3. Entries drop off after **30 days**. A parent can dismiss one entry, or clear them all.

Non-goals: configurable reminder times; reminders for rewards; a reminders toggle in the setup
wizard (turned on from the dashboard instead); points penalties for missed chores; backfilling
missed days from before this feature is installed; streaks or statistics.

## Decisions (from the design conversation)

| Question | Decision |
|---|---|
| Where the reminders option lives | Per chore (`reminders` on the chore record), default off |
| What gets reminded | Due today, status `idle` or `denied` (a denied chore can be re-claimed the same day) |
| Notification shape | One notification per kid per time slot, listing every outstanding chore |
| "Has a phone" | `async_resolve_member_notify_targets`: a manual notify mapping, else the linked HA user's Companion App devices. None → nothing is sent |
| Missed = | Never claimed that day, or denied and not redone. A claim still awaiting review is **not** missed |
| Which chores are tracked as missed | Every assigned chore, whether or not reminders are on. Unassigned chores are never tracked |
| Clearing | Auto-prune after 30 days, plus per-entry dismiss and Clear all |
| Where the list shows | Chores tab, directly under Parent Review, behind the same Parent PIN gate |

## 1. Stored data

- Chore record gains `reminders: bool`. Absent is treated as `false`, so existing chores
  need no upgrade step.
- A new HA `Store` per config entry, key `family_dashboard.<entry_id>.missed_chores`,
  version 1:

  ```json
  {"entries": [
    {"id": "<uuid hex>", "date": "2026-09-25", "chore_id": "dishes", "chore_name": "Dishes",
     "member_id": "tristan", "member_name": "Tristan", "reason": "not_claimed"}
  ]}
  ```

  `reason` is `not_claimed` or `denied`. Names are copied in, so an entry still reads correctly
  after the chore is deleted or renamed. Entries older than 30 days (by `date`, against local
  today) are pruned on load and on every write. It's a `Store` rather than `entry.data` because
  writing `entry.data` reloads the whole entry (see `crud._async_persist`).
- Task sensors (chores only) gain a restored attribute, `checked_through` (ISO date): the last
  day already scanned for misses. A sensor with none (a new chore, or the first start after
  upgrading) sets it to yesterday, so nothing before this feature is backfilled.

## 2. Reminders

New `modules/chores/reminders.py`, the same shape as `modules/calendar/reminders.py`:

- `async_start_chore_reminders(hass, entry) -> CALLBACK_TYPE` registers
  `async_track_time_change(hour=[16, 18, 19], minute=0, second=0)` with a `@callback` that
  schedules the check as a task (the calendar engine's live-verified thread-safety lesson). The
  unsub is stored and called on unload.
- `_async_send_chore_reminders(hass, entry)` is the check, which tests call directly under a
  frozen clock. For each roster member who isn't disabled and has `chores` enabled:
  1. Collect their chores with `reminders` on, `is_due(chore, today)`, and a task sensor state
     of `idle` or `denied` (read from `hass.states` via the registry `unique_id`
     `<entry_id>_<chore_id>_chore`).
  2. If there are none, skip. Otherwise resolve phones with
     `async_resolve_member_notify_targets`. If there are none, skip.
  3. Call `notify.send_message` once with every target: title "Chores left today", message the
     chore names joined by ", ".
- A failing `notify` call is logged and doesn't stop the other members.

## 3. Reminders toggle (entities and dashboard)

- New `modules/chores/switch.py`:
  - `ChoreRemindersSwitch` per chore, unique_id `<entry_id>_<chore_id>_reminders`, name
    "<Chore> Reminders", so the entity ID is `switch.family_dashboard_<chore>_reminders`.
    Turning it on or off calls `crud.async_update_chore_field(..., reminders=...)`, the same
    persist-and-reload path as the other chore fields.
  - `NewChoreRemindersSwitch`, the Add Chore popup's scratch toggle, unique_id
    `<entry_id>_new_chore_reminders`, default off, restored across restarts like the other
    scratch fields.
- `const.FEATURES["chores"]["platforms"]` gains `"switch"`. The top-level `switch.py`
  aggregator gains a Chores branch gated on any member having `chores`, like `text.py`.
- `crud.chore_field_entity_ids` includes the reminders switch, so deleting a chore removes it.
- `crud.async_add_chore` takes `reminders: bool = False`.
  `async_create_chore_from_scratch_fields` reads the scratch switch and resets it to off.
- Dashboard: `_add_chore_popup` adds a "Send reminders" row. `_chore_row` adds a
  "Reminders: On/Off" pill that toggles the switch on tap.

## 4. Recording missed chores

The task sensor records misses itself, because only it knows the instance being reset, and
ordering against its own reset is the hard part.

- `MissedChoresLog` (new `modules/chores/missed.py`) wraps the `Store`: `async_load`,
  `add(entry_dict)` (dedupes on `(chore_id, date)`), `dismiss(id)`, `clear()`, `entries`
  (newest first), and a listener hook so the sensor below updates. Writes go through
  `Store.async_delay_save` so a midnight burst of misses is one disk write. It is created and
  loaded once per entry in `hass.data[DOMAIN][entry_id]`, before the sensor platform adds
  entities.
- In `FamilyDashboardTaskSensor`, at startup and in `_handle_midnight`, **before**
  `_run_instance_check`, a new `_record_missed_days()`:
  - For each due day `d` from `checked_through + 1` through yesterday (capped at 30 days
    back): if `d == claimed_on`, skip it (claimed that day; a denial is handled below).
    Otherwise record `not_claimed` for `d`.
  - Then set `checked_through = yesterday`.
  - It skips unassigned chores, but still advances `checked_through`.
- In `_run_instance_check`, when a **denied** instance is sent back to `idle`, record `denied`
  for `claimed_on` first. This covers a denial at 3 PM that isn't redone (reset at midnight), a
  late denial after the day already ended (reset right away), and a denial followed by a
  re-claim the same day (state is `claimed`, so no reset and no record).
- A claim still pending at midnight isn't recorded. If it's later denied, the denial path
  records it.

## 5. Missed-chores sensor, services, and card

- `MissedChoresSensor` (`sensor.family_dashboard_missed_chores`): its state is the entry count,
  and its `entries` attribute is the list, newest first, capped at 50 for attribute size. It
  isn't recorded to history (`_unrecorded_attributes`), because the list changes daily.
- Entity services on that sensor, declared in `services.yaml`:
  `family_dashboard.dismiss_missed_chore` (`entry_id: str`) and
  `family_dashboard.clear_missed_chores`.
- A card under Parent Review, gated by the same `binary_sensor.family_dashboard_parent_mode`
  conditional:
  - Heading "Missed Chores (N)", and a "Clear all" button with a native `confirmation:`.
  - 20 fixed `custom:button-card` rows. Row `i` shows entry `i` as "Thu Sep 25 · Tristan ·
    Dishes · Not claimed/Denied" through a JS template, and hides itself with a
    `display: none` style when entry `i` doesn't exist. Dashboard conditions can't match
    attributes before HA 2026.5, so a conditional card can't do this. Tapping a row's ✕ calls
    `dismiss_missed_chore` with the entry id read by the template at tap time.
  - Past 20 entries, a line reads "+N more (oldest drop off after 30 days)".
  - "No missed chores 🎉" when the list is empty.
- The button-card templated service data (`[[[ ]]]` inside `data`) must be verified in a real
  browser before this counts as done. If it doesn't template, fall back to per-kid "Clear"
  buttons and Clear all.

## Testing

Pytest, under a frozen clock:

- **Reminders:**
  - only due-today chores with reminders on and status idle or denied are sent;
  - claimed and approved chores, reminders off, not due today, unassigned, disabled member,
    and no phone are all skipped;
  - one call per kid, listing every outstanding chore;
  - the switch persists `reminders`, and the Add popup scratch switch is read and reset.
- **Missed:**
  - never claimed yesterday records `not_claimed`;
  - claimed and approved records nothing;
  - pending at midnight records nothing, and a later deny records `denied` with the original
    date;
  - denied and not redone records `denied`;
  - denied then re-claimed records nothing;
  - HA off for 3 days catches up on each due day, and not on days that weren't due;
  - `checked_through` is initialised to yesterday (no backfill);
  - a monthly or one-time schedule is respected;
  - 30-day pruning, dismiss, clear, and dedupe work.

Live bench:

- Restart with clean logs.
- Flip a reminders switch over REST and confirm `reminders` is stored in the config entry.
- Give one member a temporary manual notify mapping, fire the check, and confirm it's delivered.
- Seed misses: with an every-day chore, stop HA, set that task sensor's restored
  `checked_through` in `.storage/core.restore_state` to three days ago, then start it. Confirm
  entries for the two missed days appear in the sensor and the card.
- Browser as a parent: the Add popup toggle, the Reminders pill, the missed list rendering,
  dismiss and Clear all, and no console errors.

## Docs

SETUP.md gets a "Chore reminders" note (it needs the Companion App on a linked HA user, or a
manual notify mapping) and a "Missed chores" note. `services.yaml` declares the two new
services. `strings.json`/`translations/en.json` don't change (they don't declare services).

## Refinements during implementation

- A due day after a claim that's still awaiting review isn't missed: the kid couldn't claim it.
- A denial is recorded by the midnight scan (or immediately, when a late review denies a day
  that's already over), not when the instance resets. For a Mon/Thu chore, the reset only
  happens on Thursday.
- One-time chores are never recorded as missed. `is_due` is true every day until they're done,
  so they have no day to miss. They are still reminded.
- The dismiss service field is `missed_id`. The Add popup's scratch switch isn't restored
  across restarts, which matches the other scratch fields.
- The log is flushed on unload, so the reload after a chore edit can't load it before a
  pending save.
- Missed rows are conditionals on the sensor's count (its state), not `display: none`. Hidden
  rows otherwise left about 150px of blank space in the stack (live-measured).
