# Chore Reminders and Missed-Chores List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-chore 4/6/7 PM phone reminders for unclaimed due-today chores, plus a 30-day
missed-chores list in the Kiosk parent view.

**Architecture:** A `reminders` flag on each chore record, edited through a new per-chore
switch. A time-triggered engine (`modules/chores/reminders.py`) reuses the Calendar module's
phone resolver. Misses are recorded by each chore's own task sensor at midnight and startup,
into a per-entry HA `Store` (`modules/chores/missed.py`). A `sensor.family_dashboard_missed_chores`
exposes the list, with dismiss/clear entity services and a button-card list under Parent Review.

**Tech Stack:** Home Assistant custom integration (Python 3.12+), pytest-homeassistant-custom-component,
Lovelace `custom:button-card`.

**Spec:** `docs/superpowers/specs/2026-09-26-chore-reminders-and-missed-list-design.md`

## Global Constraints

- Supports HA back to 2024.6.0 (`hacs.json`). Dashboard conditions can't match attributes (HA 2026.5+ only).
- Entity IDs are `<domain>.family_dashboard_<slugified _attr_name>`, pinned by `entity_ids.pin_entity_ids`. Entity classes don't set `entity_id`.
- Scheduler callbacks that create tasks must be `@callback`. No blocking I/O in entity properties.
- Reminder times: 16:00, 18:00, 19:00 local. Missed-list retention: 30 days. Card rows: 20.
- Reminded statuses: `idle`, `denied`. Missed reasons: `not_claimed`, `denied`.
- Tests run in `python:3.14-slim` Docker (see CLAUDE.md). Never a host venv.
- Live bench validation (CLAUDE.md "Live validation") is required before calling it done.

## Refinements to the spec (found while planning)

1. **Pending claims block later due days.** While a claim awaits review, the kid can't claim
   (`async_claim` raises "already claimed"). So a due day after `claimed_on`, while the state
   is still `claimed`, is **not** missed.
2. **Denials are recorded at the midnight scan, not at the reset.** For a Mon/Thu chore, the
   reset after a Monday denial only happens Thursday. Instead:
   - The scan records `denied` for `d == claimed_on` when the state is `denied`.
   - `async_deny` records it immediately when the instance's day has already ended
     (`claimed_on < today`).
   - Dedupe on `(chore_id, date)` makes a double record harmless.
3. The dismiss service field is `missed_id`, not `entry_id` (avoids confusion with config entries).
4. **One-time chores are never recorded as missed.** `is_due` is true every day for a one-time
   chore until it's done, so it has no day to miss and would otherwise add an entry every night.
   They are still reminded.
5. The Add popup's scratch switch isn't restored across restarts. That matches the other
   scratch fields (`NewChorePointsNumber` isn't a `RestoreEntity` either).

## Review Focus

1. **A claim pending across a due day** (claimed Mon, reviewed Fri): Thursday must not be
   recorded as missed. Test in Task 4.
2. **Monday denial on a Mon/Thu chore** must appear Tuesday morning, not Thursday. Test in Task 4.
3. **The notify call raises** (for example, the phone's notify entity was removed): other kids
   must still get theirs, and no exception reaches the scheduler. Test in Task 2.
4. **Deleting a chore** must remove its reminders switch, but keep its missed entries (names
   are copied). Test in Task 1 (switch) and Task 4 (entries survive delete).
5. **One-time chores** (due every day until done) must not add a missed entry every night.
   Test in Task 4.
6. **The HA restart path:** `checked_through` restored from state catches up exactly the due
   days in between, and the Store survives the reload triggered by editing a chore. Test in Task 4.

## File map

- Create `custom_components/family_dashboard/modules/chores/switch.py`: `ChoreRemindersSwitch`, `NewChoreRemindersSwitch`.
- Create `custom_components/family_dashboard/modules/chores/reminders.py`: the engine.
- Create `custom_components/family_dashboard/modules/chores/missed.py`: `MissedChoresLog`.
- Modify `const.py` (chores platforms get `"switch"`), top-level `switch.py` (Chores branch),
  `modules/chores/crud.py` (`reminders` param, scratch read/reset, entity ids),
  `modules/chores/sensor.py` (log loading, miss recording, `MissedChoresSensor`, services,
  engine start), `__init__.py` (unsub on unload), `modules/chores/dashboard.py` (toggle, pill,
  missed card), `services.yaml`, `SETUP.md`.
- Tests: `tests/test_chore_reminders.py`, `tests/test_missed_chores.py`, plus additions to
  `tests/test_chores_crud.py` and `tests/test_dashboard.py`.

Test command (from the repo root, Git Bash):

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD:/app" -w /app python:3.14-slim \
  bash -c "pip install -q -r requirements_test.txt && python -m pytest <target> -q -p no:cacheprovider"
```

---

### Task 1: Reminders flag and switches

**Files:**
- Create: `custom_components/family_dashboard/modules/chores/switch.py`
- Modify: `const.py` (FEATURES chores platforms), `switch.py` (top level), `modules/chores/crud.py`
- Test: `tests/test_chores_crud.py`

**Interfaces:**
- Produces: `crud.async_add_chore(..., reminders: bool = False)`; chore record key
  `"reminders"`; `switch.family_dashboard_<chore>_reminders` (unique_id
  `<entry_id>_<chore_id>_reminders`); `switch.family_dashboard_new_chore_reminders` (unique_id
  `<entry_id>_new_chore_reminders`); helper `new_chore_reminders_unique_id(entry)` in `switch.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_chores_crud.py`)

```python
async def test_reminders_switch_persists_on_chore(hass: HomeAssistant):
    entry = await _setup_entry(
        hass, [_member("ada", "Ada")],
        chores=[{"chore_id": "trash", "name": "Trash", "points": 5, "assigned_to": "ada"}],
    )
    assert hass.states.get("switch.family_dashboard_trash_reminders").state == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.family_dashboard_trash_reminders"}, blocking=True
    )
    await hass.async_block_till_done()

    assert entry.data["chores"][0]["reminders"] is True
    assert hass.states.get("switch.family_dashboard_trash_reminders").state == "on"


async def test_create_chore_from_scratch_reads_and_resets_reminders(hass: HomeAssistant):
    entry = await _setup_entry(hass, [_member("ada", "Ada")])
    await hass.services.async_call(
        "text", "set_value",
        {"entity_id": "text.family_dashboard_new_chore_name", "value": "Dishes"}, blocking=True,
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.family_dashboard_new_chore_reminders"}, blocking=True
    )
    await hass.services.async_call(
        "family_dashboard", "add_chore",
        {"entity_id": "text.family_dashboard_new_chore_name"}, blocking=True,
    )
    await hass.async_block_till_done()

    assert next(c for c in entry.data["chores"] if c["name"] == "Dishes")["reminders"] is True
    assert hass.states.get("switch.family_dashboard_new_chore_reminders").state == "off"


async def test_delete_chore_removes_reminders_switch(hass: HomeAssistant):
    entry = await _setup_entry(
        hass, [_member("ada", "Ada")],
        chores=[{"chore_id": "trash", "name": "Trash", "points": 5, "assigned_to": "ada"}],
    )
    await crud.async_delete_chore(hass, entry, "trash")
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_trash_reminders") is None
```

- [ ] **Step 2: Run them to verify they fail.** Target: `tests/test_chores_crud.py -k reminders`.
  Expected: FAIL, because the `switch.family_dashboard_trash_reminders` state is None.

- [ ] **Step 3: Implement**

`const.py`, chores platforms:
`"platforms": ["sensor", "button", "text", "binary_sensor", "select", "number", "switch"],`
(extend the comment above it: "switch" is the per-chore Reminders toggle).

`modules/chores/switch.py`:

```python
"""Chores & Rewards' `switch` entities - each chore's Reminders toggle (`ChoreRemindersSwitch`,
persisted on the chore record like its other field entities) and the Add Chore popup's scratch
toggle (`NewChoreRemindersSwitch`, reset after each submit). See `reminders.py` for what the
flag does.

Aggregated (alongside Settings and Calendar) by the top-level `switch.py`.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import CONF_CHORES, DOMAIN
from . import crud


def new_chore_reminders_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.entry_id}_new_chore_reminders"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entities: list = [NewChoreRemindersSwitch(entry)]
    entities.extend(ChoreRemindersSwitch(entry, chore) for chore in entry.data.get(CONF_CHORES, []))
    async_add_entities(entities)


class _ChoreSwitchBase(SwitchEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-ring-outline"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )


class NewChoreRemindersSwitch(_ChoreSwitchBase):
    """Add Chore popup's scratch toggle - not a RestoreEntity, reset to off after each submit
    (see `crud.async_create_chore_from_scratch_fields`)."""

    _attr_name = "New Chore Reminders"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = new_chore_reminders_unique_id(entry)
        self._attr_is_on = False

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()


class ChoreRemindersSwitch(_ChoreSwitchBase):
    """One EXISTING chore's Reminders flag. Not a RestoreEntity - derives from `entry.data`
    each time the reload its own edit triggers rebuilds it (same as `ChorePointsNumber`)."""

    def __init__(self, entry: ConfigEntry, chore: dict) -> None:
        super().__init__(entry)
        self._chore_id = chore["chore_id"]
        self._attr_name = f"{chore['name']} Reminders"
        self._attr_unique_id = f"{entry.entry_id}_{self._chore_id}_reminders"
        self._attr_is_on = bool(chore.get("reminders"))

    async def async_turn_on(self, **kwargs) -> None:
        await crud.async_update_chore_field(self.hass, self._entry, self._chore_id, reminders=True)

    async def async_turn_off(self, **kwargs) -> None:
        await crud.async_update_chore_field(self.hass, self._entry, self._chore_id, reminders=False)
```

Top-level `switch.py`: import `from .modules.chores.switch import async_setup_entry as _chores_setup_entry`,
compute `features` like `text.py`, and add `if "chores" in features: await _chores_setup_entry(...)`.
Update its docstring to name Chores.

`crud.py`:
- `async_add_chore(..., month_days=None, reminders: bool = False)`, and in the record:
  `if reminders: new_chore["reminders"] = True` (omitted rather than stored false, the same
  convention as `schedule_days`).
- `chore_field_entity_ids`: add `("switch", f"{entry.entry_id}_{chore_id}_reminders")`.
- `async_create_chore_from_scratch_fields`:
  - read `reminders_entity = _entity(hass, "switch", f"{entry.entry_id}_new_chore_reminders")`;
  - pass `reminders=bool(reminders_entity and reminders_entity.is_on)`;
  - after the add, `if reminders_entity: await reminders_entity.async_turn_off()`.
  - The unique_id is a literal string here to avoid importing `switch.py` (which imports `crud`).

- [ ] **Step 4: Run** `tests/test_chores_crud.py`. Expected: all PASS.
- [ ] **Step 5: Commit** — `git commit -m "Add a per-chore Reminders switch and Add Chore toggle"`

### Task 2: Reminder engine

**Files:**
- Create: `custom_components/family_dashboard/modules/chores/reminders.py`
- Modify: `modules/chores/sensor.py` (`async_setup_entry` starts it), `__init__.py` (unload)
- Test: `tests/test_chore_reminders.py`

**Interfaces:**
- Consumes: chore `"reminders"` (Task 1); `async_resolve_member_notify_targets(hass, member)`
  from `modules/calendar/reminders.py`; `is_due` from `schedule.py`; `_task_unique_id(entry, item_id, kind)` from `sensor.py`.
- Produces: `async_send_chore_reminders(hass, entry) -> None`,
  `async_start_chore_reminders(hass, entry) -> CALLBACK_TYPE`, `REMINDER_HOURS = (16, 18, 19)`,
  `hass.data[DOMAIN][entry_id]["chore_reminder_unsub"]`.

- [ ] **Step 1: Write the failing tests** — `tests/test_chore_reminders.py`

```python
"""Chore reminders: at 4/6/7 PM, each kid with a phone gets one notification listing their
due-today chores that have reminders on and aren't claimed or approved yet.

Dates: Mon 2026-09-21. Chores are due every day unless a test says otherwise.
"""
from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.family_dashboard.const import DOMAIN


def _member(member_id="ada", name="Ada", notify="notify.ada_phone", **extra):
    return {
        "member_id": member_id, "name": name, "color": "Blue", "features": ["chores"],
        "ha_user_id": None, "calendar_entity_id": None, "notify_entity_id": notify,
        "list_presets": [], **extra,
    }


def _chore(chore_id, name, assigned_to="ada", reminders=True, **schedule):
    chore = {"chore_id": chore_id, "name": name, "points": 5, "assigned_to": assigned_to,
             "repeat": "days_of_week", **schedule}
    if reminders:
        chore["reminders"] = True
    return chore


async def _at(hass, freezer, hour, minute=0, day=21):
    local = datetime(2026, 9, day, hour, minute, 0, tzinfo=dt_util.get_default_time_zone())
    freezer.move_to(local)
    async_fire_time_changed(hass, local)
    await hass.async_block_till_done()


async def _setup(hass, roster, chores):
    entry = MockConfigEntry(
        version=1, domain=DOMAIN, title="Family Dashboard",
        data={"roster": roster, "chores": chores, "rewards": []},
        source="user", unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    async_mock_service(hass, "logbook", "log")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _claim(hass, chore_id):
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.family_dashboard_{chore_id}_claim"}, blocking=True
    )


async def test_sends_one_notification_listing_outstanding_chores(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)
    calls = async_mock_service(hass, "notify", "send_message")
    await _setup(hass, [_member()], [_chore("dishes", "Dishes"), _chore("trash", "Trash")])

    await _at(hass, freezer, 16)

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["notify.ada_phone"]
    assert calls[0].data["title"] == "Chores left today"
    assert calls[0].data["message"] == "Dishes, Trash"


async def test_fires_at_4_6_and_7_only(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)
    calls = async_mock_service(hass, "notify", "send_message")
    await _setup(hass, [_member()], [_chore("dishes", "Dishes")])

    for hour in (15, 16, 17, 18, 19, 20):
        await _at(hass, freezer, hour)

    assert len(calls) == 3


async def test_skips_claimed_and_approved_but_reminds_denied(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)
    calls = async_mock_service(hass, "notify", "send_message")
    await _setup(
        hass, [_member()],
        [_chore("dishes", "Dishes"), _chore("trash", "Trash"), _chore("bed", "Bed")],
    )
    await _claim(hass, "dishes")  # pending
    await _claim(hass, "trash")
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.family_dashboard_trash_approve"}, blocking=True
    )
    await _claim(hass, "bed")
    await hass.services.async_call(
        DOMAIN, "deny_task",
        {"entity_id": "sensor.family_dashboard_bed", "reason": "Not made"}, blocking=True,
    )

    await _at(hass, freezer, 16)

    assert [c.data["message"] for c in calls] == ["Bed"]


async def test_skips_reminders_off_not_due_and_unassigned(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)  # Monday
    calls = async_mock_service(hass, "notify", "send_message")
    await _setup(
        hass, [_member()],
        [
            _chore("dishes", "Dishes", reminders=False),
            _chore("trash", "Trash", schedule_days=["tuesday"]),
            _chore("lawn", "Lawn", assigned_to=None),
        ],
    )

    await _at(hass, freezer, 16)

    assert calls == []


async def test_skips_member_without_phone_or_disabled(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)
    calls = async_mock_service(hass, "notify", "send_message")
    await _setup(
        hass,
        [_member("ada", "Ada", notify=None), _member("bo", "Bo", notify="notify.bo", disabled=True)],
        [_chore("dishes", "Dishes"), _chore("trash", "Trash", assigned_to="bo")],
    )

    await _at(hass, freezer, 16)

    assert calls == []


async def test_one_failing_phone_does_not_stop_the_others(hass: HomeAssistant, freezer):
    await _at(hass, freezer, 12)
    sent = []

    async def _send(call):
        if call.data["entity_id"] == ["notify.ada_phone"]:
            raise HomeAssistantError("gone")
        sent.append(call.data["entity_id"])

    hass.services.async_register("notify", "send_message", _send)
    await _setup(
        hass, [_member(), _member("bo", "Bo", notify="notify.bo")],
        [_chore("dishes", "Dishes"), _chore("trash", "Trash", assigned_to="bo")],
    )

    await _at(hass, freezer, 16)

    assert sent == [["notify.bo"]]
```

- [ ] **Step 2: Run** `tests/test_chore_reminders.py`. Expected: FAIL (no calls).

- [ ] **Step 3: Implement** `modules/chores/reminders.py`

```python
"""Chore reminders - at 4, 6 and 7 PM local, each kid gets one phone notification listing
their chores that are due today, have Reminders on (`chore["reminders"]`, see `switch.py`),
and are still `idle` or `denied` (a denied chore can be claimed again the same day). Claimed
or approved chores, unassigned chores, disabled members, and members with no phone are
skipped. "Has a phone" is the Calendar reminders' resolver: a manual notify mapping, else the
linked HA user's Companion App devices.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from ...const import CONF_CHORES, CONF_DISABLED, CONF_FEATURES, CONF_ROSTER, DOMAIN
from ..calendar.reminders import async_resolve_member_notify_targets
from .schedule import is_due

_LOGGER = logging.getLogger(__name__)

REMINDER_HOURS = (16, 18, 19)
_REMIND_STATUSES = ("idle", "denied")


def _outstanding_chore_names(hass: HomeAssistant, entry: ConfigEntry, member_id: str) -> list[str]:
    from .sensor import _task_unique_id

    today = dt_util.now().date()
    registry = er.async_get(hass)
    names = []
    for chore in entry.data.get(CONF_CHORES, []):
        if chore.get("assigned_to") != member_id or not chore.get("reminders"):
            continue
        if not is_due(chore, today):
            continue
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, _task_unique_id(entry, chore["chore_id"], "chore")
        )
        state = hass.states.get(entity_id) if entity_id else None
        if state is not None and state.state in _REMIND_STATUSES:
            names.append(chore["name"])
    return names


async def async_send_chore_reminders(hass: HomeAssistant, entry: ConfigEntry) -> None:
    for member in entry.data[CONF_ROSTER]:
        if member.get(CONF_DISABLED) or "chores" not in member.get(CONF_FEATURES, []):
            continue
        names = _outstanding_chore_names(hass, entry, member["member_id"])
        if not names:
            continue
        targets = await async_resolve_member_notify_targets(hass, member)
        if not targets:
            continue
        try:
            await hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": targets, "title": "Chores left today", "message": ", ".join(names)},
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Family Dashboard: chore reminder for %s to %s failed: %s", member["name"], targets, err
            )


def async_start_chore_reminders(hass: HomeAssistant, entry: ConfigEntry) -> CALLBACK_TYPE:
    """Schedule the reminders; returns the unsub, called on unload (see __init__.py)."""

    @callback
    def _fire(_now) -> None:
        # @callback, like the Calendar engine's tick - see modules/calendar/reminders.py.
        hass.async_create_task(async_send_chore_reminders(hass, entry))

    return async_track_time_change(hass, _fire, hour=list(REMINDER_HOURS), minute=0, second=0)
```

In `modules/chores/sensor.py` `async_setup_entry`, after the entity services are registered:

```python
    from .reminders import async_start_chore_reminders

    hass.data[DOMAIN][entry.entry_id]["chore_reminder_unsub"] = async_start_chore_reminders(hass, entry)
```

(A local import, because `reminders.py` imports `_task_unique_id` from this module.)

`__init__.py` `async_unload_entry`, beside `reminder_unsub`:

```python
        if chore_reminder_unsub := domain_data.get("chore_reminder_unsub"):
            chore_reminder_unsub()
```

- [ ] **Step 4: Run** `tests/test_chore_reminders.py`. Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Send 4/6/7 PM phone reminders for unclaimed chores"`

### Task 3: Missed-chores log, sensor, and services

**Files:**
- Create: `custom_components/family_dashboard/modules/chores/missed.py`
- Modify: `modules/chores/sensor.py` (load the log, add `MissedChoresSensor`, register services), `services.yaml`
- Test: `tests/test_missed_chores.py`

**Interfaces:**
- Produces: `MissedChoresLog(hass, entry_id)` with `async_load()`,
  `add(*, day: date, chore: dict, member_name: str, reason: str)`, `dismiss(missed_id: str)`,
  `clear()`, `entries -> list[dict]` (newest first), and `async_add_listener(cb) -> CALLBACK_TYPE`;
  `RETENTION_DAYS = 30`; `hass.data[DOMAIN][entry_id]["missed_log"]`;
  `sensor.family_dashboard_missed_chores` (unique_id `<entry_id>_missed_chores`, state = count,
  attribute `entries`); services `family_dashboard.dismiss_missed_chore` (`missed_id`) and
  `family_dashboard.clear_missed_chores`.

- [ ] **Step 1: Write the failing tests** — `tests/test_missed_chores.py` (first part; Task 4 appends to it)

```python
"""The missed-chores list: a due day that ended with the chore never claimed, or denied and
not redone. Kept 30 days; a parent can dismiss one entry or clear all.

Dates: Mon 2026-09-21 .. Sun 2026-09-27. The test chore is due Mondays and Thursdays.
"""
from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache,
)

from custom_components.family_dashboard.const import DOMAIN

ENTRY_ID = "fdtest"
STORE_KEY = f"family_dashboard.{ENTRY_ID}.missed_chores"
MISSED = "sensor.family_dashboard_missed_chores"
TASK = "sensor.family_dashboard_trash"
MON, TUE, WED, THU, FRI = 21, 22, 23, 24, 25


def _member():
    return {
        "member_id": "ada", "name": "Ada", "color": "Blue", "features": ["chores"],
        "ha_user_id": None, "calendar_entity_id": None, "notify_entity_id": None,
        "list_presets": [],
    }


def _chore(**overrides):
    return {
        "chore_id": "trash", "name": "Trash", "points": 10, "assigned_to": "ada",
        "repeat": "days_of_week", "schedule_days": ["monday", "thursday"], **overrides,
    }


def _stored(entry):
    return {"version": 1, "minor_version": 1, "key": STORE_KEY, "data": {"entries": entry}}


async def _at(hass, freezer, day, hour=12, minute=0, second=0):
    local = datetime(2026, 9, day, hour, minute, second, tzinfo=dt_util.get_default_time_zone())
    freezer.move_to(local)
    async_fire_time_changed(hass, local)
    await hass.async_block_till_done()


async def _midnight(hass, freezer, day):
    await _at(hass, freezer, day, 0, 0, 5)


async def _setup(hass, chores=None):
    entry = MockConfigEntry(
        version=1, domain=DOMAIN, title="Family Dashboard", entry_id=ENTRY_ID,
        data={"roster": [_member()], "chores": [_chore()] if chores is None else chores, "rewards": []},
        source="user", unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    async_mock_service(hass, "logbook", "log")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entries(hass):
    return hass.states.get(MISSED).attributes["entries"]


def _summary(hass):
    return [(e["date"], e["chore_name"], e["reason"]) for e in _entries(hass)]


def _entry(missed_id, day, name="Trash"):
    return {"id": missed_id, "date": day, "chore_id": name.lower(), "chore_name": name,
            "member_id": "ada", "member_name": "Ada", "reason": "not_claimed"}


async def test_loads_stored_entries_and_prunes_older_than_30_days(hass: HomeAssistant, freezer, hass_storage):
    await _at(hass, freezer, MON)
    hass_storage[STORE_KEY] = _stored([_entry("a", "2026-09-17"), _entry("b", "2026-08-01")])

    await _setup(hass)

    assert hass.states.get(MISSED).state == "1"
    assert [e["id"] for e in _entries(hass)] == ["a"]


async def test_dismiss_and_clear(hass: HomeAssistant, freezer, hass_storage):
    await _at(hass, freezer, MON)
    hass_storage[STORE_KEY] = _stored(
        [_entry("a", "2026-09-17"), _entry("b", "2026-09-18", "Dishes"), _entry("c", "2026-09-19", "Bed")]
    )
    await _setup(hass)

    await hass.services.async_call(
        DOMAIN, "dismiss_missed_chore", {"entity_id": MISSED, "missed_id": "b"}, blocking=True
    )
    await hass.async_block_till_done()
    assert [e["id"] for e in _entries(hass)] == ["c", "a"]  # newest first

    await hass.services.async_call(DOMAIN, "clear_missed_chores", {"entity_id": MISSED}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(MISSED).state == "0"
```

- [ ] **Step 2: Run** `tests/test_missed_chores.py`. Expected: FAIL (`MISSED` state is None).

- [ ] **Step 3: Implement** `modules/chores/missed.py`

```python
"""The missed-chores log - one HA `Store` per config entry, not `entry.data`, because writing
`entry.data` reloads the whole entry (see `crud._async_persist`) and this changes nightly.

An entry is one chore instance (a due day) that ended with the chore never claimed
(`not_claimed`) or denied and not redone (`denied`). The task sensors record them - see
`FamilyDashboardTaskSensor._record_missed_days` in `sensor.py`. Names are copied in so an
entry still reads right after the chore is renamed or deleted. Entries older than
`RETENTION_DAYS` are pruned on load and on every change.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from uuid import uuid4

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ...const import DOMAIN

RETENTION_DAYS = 30
_STORE_VERSION = 1
_SAVE_DELAY = 1


class MissedChoresLog:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict] = Store(hass, _STORE_VERSION, f"{DOMAIN}.{entry_id}.missed_chores")
        self._entries: list[dict] = []
        self._listeners: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._entries = list(data.get("entries", []))
        if self._prune():
            self._save()

    @property
    def entries(self) -> list[dict]:
        """Newest first; within a day, by kid then chore."""
        by_name = sorted(self._entries, key=lambda e: (e["member_name"], e["chore_name"]))
        return sorted(by_name, key=lambda e: e["date"], reverse=True)

    def add(self, *, day: date, chore: dict, member_name: str, reason: str) -> None:
        iso = day.isoformat()
        if any(e["chore_id"] == chore["chore_id"] and e["date"] == iso for e in self._entries):
            return
        self._entries.append(
            {
                "id": uuid4().hex,
                "date": iso,
                "chore_id": chore["chore_id"],
                "chore_name": chore["name"],
                "member_id": chore.get("assigned_to"),
                "member_name": member_name,
                "reason": reason,
            }
        )
        self._prune()
        self._changed()

    def dismiss(self, missed_id: str) -> None:
        self._entries = [e for e in self._entries if e["id"] != missed_id]
        self._changed()

    def clear(self) -> None:
        self._entries = []
        self._changed()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            self._listeners.remove(listener)

        return _remove

    def _prune(self) -> bool:
        cutoff = (dt_util.now().date() - timedelta(days=RETENTION_DAYS)).isoformat()
        kept = [e for e in self._entries if e["date"] >= cutoff]
        pruned = len(kept) != len(self._entries)
        self._entries = kept
        return pruned

    def _save(self) -> None:
        self._store.async_delay_save(lambda: {"entries": self._entries}, _SAVE_DELAY)

    def _changed(self) -> None:
        self._save()
        for listener in list(self._listeners):
            listener()
```

In `modules/chores/sensor.py`:
- Import `from .missed import MissedChoresLog`.
- At the top of `async_setup_entry`:

```python
    missed_log = MissedChoresLog(hass, entry.entry_id)
    await missed_log.async_load()
    hass.data[DOMAIN][entry.entry_id]["missed_log"] = missed_log
```

- Add `MissedChoresSensor(entry, missed_log)` to the `async_add_entities` list.
- Register:

```python
    platform.async_register_entity_service(
        "dismiss_missed_chore", {vol.Required("missed_id"): cv.string}, "async_dismiss"
    )
    platform.async_register_entity_service("clear_missed_chores", {}, "async_clear")
```

- New class (place it after `FamilyDashboardDayOfWeekSensor`):

```python
_MISSED_ATTRIBUTE_CAP = 50


class MissedChoresSensor(SensorEntity):
    """The missed-chores list (see `missed.py`) - state is how many entries there are,
    `entries` the newest `_MISSED_ATTRIBUTE_CAP` of them for the Parent view's list card.
    `entries` is kept out of the recorder, since the whole list changes nightly."""

    _attr_has_entity_name = True
    _attr_name = "Missed Chores"
    _attr_icon = "mdi:calendar-remove"
    _attr_should_poll = False
    _unrecorded_attributes = frozenset({"entries"})

    def __init__(self, entry: ConfigEntry, log: MissedChoresLog) -> None:
        self._entry = entry
        self._log = log
        self._attr_unique_id = f"{entry.entry_id}_missed_chores"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    @property
    def native_value(self) -> int:
        return len(self._log.entries)

    @property
    def extra_state_attributes(self) -> dict:
        return {"entries": self._log.entries[:_MISSED_ATTRIBUTE_CAP]}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._log.async_add_listener(self.async_write_ha_state))

    async def async_dismiss(self, missed_id: str) -> None:
        self._log.dismiss(missed_id)

    async def async_clear(self) -> None:
        self._log.clear()
```

`services.yaml` (after `reset_claim`):

```yaml
dismiss_missed_chore:
  name: Dismiss missed chore
  description: >-
    Remove one entry from the missed-chores list (a parent has dealt with it).
  target:
    entity:
      domain: sensor
      integration: family_dashboard
  fields:
    missed_id:
      name: Missed entry ID
      description: The entry's `id` from the Missed Chores sensor's `entries` attribute.
      required: true
      selector:
        text:

clear_missed_chores:
  name: Clear missed chores
  description: Remove every entry from the missed-chores list.
  target:
    entity:
      domain: sensor
      integration: family_dashboard
```

- [ ] **Step 4: Run** `tests/test_missed_chores.py`. Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Add the missed-chores log, sensor and dismiss/clear services"`

### Task 4: Record missed days from the task sensor

**Files:**
- Modify: `modules/chores/sensor.py` (`FamilyDashboardTaskSensor`)
- Test: `tests/test_missed_chores.py` (append)

**Interfaces:**
- Consumes: `MissedChoresLog.add(...)` and `RETENTION_DAYS` (Task 3).
- Produces: task-sensor attribute `checked_through` (ISO date, chores only).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_missed_chores.py`)

```python
async def _press(hass, entity_id):
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def _deny(hass):
    await hass.services.async_call(
        DOMAIN, "deny_task", {"entity_id": TASK, "reason": "Not done"}, blocking=True
    )
    await hass.async_block_till_done()


async def test_never_claimed_is_recorded_next_midnight(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)

    await _midnight(hass, freezer, TUE)

    assert _summary(hass) == [("2026-09-21", "Trash", "not_claimed")]


async def test_claimed_and_approved_is_not_missed(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _press(hass, "button.family_dashboard_trash_claim")
    await _press(hass, "button.family_dashboard_trash_approve")

    await _midnight(hass, freezer, TUE)

    assert _summary(hass) == []


async def test_denied_same_day_is_recorded_next_midnight(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _press(hass, "button.family_dashboard_trash_claim")
    await _deny(hass)

    await _midnight(hass, freezer, TUE)

    assert _summary(hass) == [("2026-09-21", "Trash", "denied")]


async def test_denied_then_redone_is_not_missed(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _press(hass, "button.family_dashboard_trash_claim")
    await _deny(hass)
    await _press(hass, "button.family_dashboard_trash_claim")
    await _press(hass, "button.family_dashboard_trash_approve")

    await _midnight(hass, freezer, TUE)

    assert _summary(hass) == []


async def test_pending_at_midnight_then_denied_late(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _press(hass, "button.family_dashboard_trash_claim")

    await _midnight(hass, freezer, TUE)
    assert _summary(hass) == []

    await _at(hass, freezer, WED)
    await _deny(hass)
    assert _summary(hass) == [("2026-09-21", "Trash", "denied")]


async def test_pending_claim_blocks_later_due_day(hass: HomeAssistant, freezer):
    """Claimed Monday, not reviewed until Friday - the kid couldn't claim Thursday."""
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _press(hass, "button.family_dashboard_trash_claim")

    await _midnight(hass, freezer, FRI)

    assert _summary(hass) == []


async def test_startup_catches_up_only_due_days(hass: HomeAssistant, freezer):
    await _at(hass, freezer, FRI)
    mock_restore_cache(hass, [State(TASK, "idle", {"checked_through": "2026-09-20"})])

    await _setup(hass)

    assert _summary(hass) == [
        ("2026-09-24", "Trash", "not_claimed"),
        ("2026-09-21", "Trash", "not_claimed"),
    ]


async def test_first_start_does_not_backfill(hass: HomeAssistant, freezer):
    await _at(hass, freezer, FRI)
    await _setup(hass)

    assert _summary(hass) == []
    assert hass.states.get(TASK).attributes["checked_through"] == "2026-09-24"


async def test_monthly_chore_respects_its_day(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass, chores=[_chore(repeat="monthly", month_days=[22], schedule_days=None)])

    await _midnight(hass, freezer, WED)

    assert _summary(hass) == [("2026-09-22", "Trash", "not_claimed")]


async def test_one_time_chore_is_never_recorded(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass, chores=[_chore(repeat="one_time", schedule_days=None)])

    await _midnight(hass, freezer, WED)

    assert _summary(hass) == []


async def test_unassigned_chore_is_never_recorded(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass, chores=[_chore(assigned_to=None)])

    await _midnight(hass, freezer, TUE)

    assert _summary(hass) == []


async def test_entries_survive_deleting_the_chore(hass: HomeAssistant, freezer):
    await _at(hass, freezer, MON)
    await _setup(hass)
    await _midnight(hass, freezer, TUE)

    await hass.services.async_call(DOMAIN, "delete_task", {"entity_id": TASK}, blocking=True)
    await hass.async_block_till_done()

    assert _summary(hass) == [("2026-09-21", "Trash", "not_claimed")]
```

Note: `_chore(repeat="monthly", month_days=[22], schedule_days=None)` leaves `schedule_days`
as `None`, which `schedule.py` ignores for monthly. If it doesn't, pop the key in the test
instead.

- [ ] **Step 2: Run** `tests/test_missed_chores.py`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement** in `FamilyDashboardTaskSensor`

- Import `from datetime import date, timedelta` and `from .missed import RETENTION_DAYS`.
- `__init__(self, entry, item, kind, roster_by_id, missed_log=None)`: store
  `self._missed_log = missed_log`, `self._member_name = member_name`, and
  `self._checked_through: date | None = None`. `async_setup_entry` passes `missed_log` to the
  chore sensors.
- In `async_added_to_hass`, while restoring:

```python
            try:
                self._checked_through = date.fromisoformat(last_state.attributes["checked_through"])
            except (KeyError, TypeError, ValueError):
                self._checked_through = None
```

  and in the `if self._kind == "chore":` block, **before** `self._run_instance_check()`:
  `self._record_missed_days()`.
- In `_handle_midnight`, **before** `self._run_instance_check()`: `self._record_missed_days()`.
- In `_refresh_schedule_attributes`, after `due_today`:

```python
        if self._checked_through is not None:
            attrs["checked_through"] = self._checked_through.isoformat()
```

- New methods:

```python
    def _record_miss(self, day: date, reason: str) -> None:
        if self._missed_log is not None and self._member_id:
            self._missed_log.add(day=day, chore=self._item, member_name=self._member_name, reason=reason)

    def _record_missed_days(self) -> None:
        """Log every due day since the last check (through yesterday) that ended with this
        chore never claimed, or denied and not redone. Runs before `_run_instance_check`, so
        `claimed_on` still names the instance that was reset. A day after a claim still awaiting
        review isn't missed: the kid couldn't claim it. A chore with no check yet (new, or the
        first start with this feature) starts from yesterday - nothing is backfilled."""
        if self._kind != "chore" or self._item.get("repeat") == REPEAT_ONE_TIME:
            return
        today = self._today()
        yesterday = today - timedelta(days=1)
        if self._checked_through is None:
            self._checked_through = yesterday
            return
        day = max(self._checked_through + timedelta(days=1), today - timedelta(days=RETENTION_DAYS))
        status = self._attr_native_value
        while day <= yesterday:
            if is_due(self._item, day):
                if day == self._claimed_on:
                    if status == "denied":
                        self._record_miss(day, "denied")
                elif not (status == "claimed" and self._claimed_on and day > self._claimed_on):
                    self._record_miss(day, "not_claimed")
            day += timedelta(days=1)
        self._checked_through = yesterday
```

- In `async_deny`, after `self._attr_native_value = "denied"` and before `_run_instance_check()`:

```python
        if self._kind == "chore" and self._claimed_on and self._claimed_on < self._today():
            # That day has already been checked, while the claim was pending.
            self._record_miss(self._claimed_on, "denied")
```

- [ ] **Step 4: Run** `tests/test_missed_chores.py tests/test_chore_lifecycle.py`. Expected: all PASS.
- [ ] **Step 5: Commit** — `git commit -m "Record missed chore days from the task sensor"`

### Task 5: Dashboard — reminders toggle, pill, and missed list

**Files:**
- Modify: `modules/chores/dashboard.py`
- Test: `tests/test_dashboard.py` (append)

**Interfaces:**
- Consumes: the switch entities (Task 1), `sensor.family_dashboard_missed_chores` and its
  services (Task 3).
- Produces: `async_missed_chores_card(hass, entry) -> dict`, `MISSED_ROWS = 20`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_dashboard.py`, reusing its
  existing setup helpers the same way `test_kiosk_chores_has_toggle_pills_parent_lock_and_pin_popup`
  does: build the config, then take `_view_cards(_views_by_path(config)["chores-kiosk"])`).

```python
async def test_kiosk_chores_has_missed_list_under_parent_review(hass):
    # (setup identical to test_kiosk_chores_has_toggle_pills_parent_lock_and_pin_popup)
    ...
    kiosk_chores = _view_cards(_views_by_path(config)["chores-kiosk"])
    blob = json.dumps(kiosk_chores)
    assert "family_dashboard.dismiss_missed_chore" in blob
    assert "family_dashboard.clear_missed_chores" in blob
    missed = next(
        c for c in kiosk_chores
        if c.get("type") == "conditional" and "Missed Chores" in json.dumps(c)
    )
    assert missed["conditions"] == [{"entity": "binary_sensor.family_dashboard_parent_mode", "state": "on"}]
    rows = [
        c for c in missed["card"]["cards"]
        if c.get("tap_action", {}).get("perform_action") == "family_dashboard.dismiss_missed_chore"
    ]
    assert len(rows) == 20
    review_index = next(i for i, c in enumerate(kiosk_chores) if "Parent Review" in json.dumps(c))
    assert kiosk_chores.index(missed) == review_index + 1
    assert "switch.family_dashboard_new_chore_reminders" in blob
```

When implementing, copy the real setup lines from the neighbouring test in place of `...`,
and make sure the chore used there makes `switch.family_dashboard_<chore>_reminders` appear
(assert that too).

- [ ] **Step 2: Run** `tests/test_dashboard.py -k missed`. Expected: FAIL (StopIteration).

- [ ] **Step 3: Implement** in `modules/chores/dashboard.py`

- `_add_chore_popup`: resolve
  `reminders_id = ent_reg.async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_new_chore_reminders") or ""`
  and add `{"entity": reminders_id, "name": "Send reminders"}` after Assigned To.
- `_chore_row`: resolve `reminders_id` for `f"{entry.entry_id}_{chore_id}_reminders"` and
  insert `_reminders_pill(reminders_id)` after `_schedule_pill`:

```python
def _reminders_pill(entity_id: str | None) -> dict:
    """Like `_field_pill`, but tapping flips the chore's Reminders switch in place - an
    on/off has nothing to pick in a more-info dialog."""
    entity_id = entity_id or ""
    return {
        "type": "custom:button-card",
        "entity": entity_id,
        "show_name": True,
        "show_icon": False,
        "name": (
            "[[[ var s = states['" + entity_id + "']; "
            "return 'Reminders: ' + (s && s.state === 'on' ? 'On' : 'Off'); ]]]"
        ),
        "tap_action": {"action": "toggle"},
        "styles": _MANAGE_FIELD_PILL_STYLE,
    }
```

- The missed list:

```python
MISSED_ROWS = 20
_PARENT_MODE = "binary_sensor.family_dashboard_parent_mode"


def _missed_entry_js(index: int) -> str:
    return f"((entity && entity.attributes.entries) || [])[{index}]"


def _missed_row(sensor_id: str, index: int) -> dict:
    """Row `index` of the missed list - hidden (display: none) when there's no such entry,
    since a dashboard condition can't test an attribute before HA 2026.5. Tapping it
    dismisses that entry; the id is read at tap time, so it's always the row shown."""
    e = _missed_entry_js(index)
    return {
        "type": "custom:button-card",
        "entity": sensor_id,
        "icon": "mdi:close-circle-outline",
        "show_icon": True,
        "show_name": True,
        "show_state": False,
        "name": (
            f"[[[ var e = {e}; if (!e) return ''; "
            "var d = new Date(e.date + 'T00:00:00'); "
            "return d.toLocaleDateString('en-US', {weekday: 'short', month: 'short', day: 'numeric'})"
            " + ' · ' + e.member_name + ' · ' + e.chore_name + ' · '"
            " + (e.reason === 'denied' ? 'Denied' : 'Not claimed'); ]]]"
        ),
        "tap_action": {
            "action": "perform-action",
            "perform_action": "family_dashboard.dismiss_missed_chore",
            "target": {"entity_id": sensor_id},
            "data": {"missed_id": f"[[[ var e = {e}; return e ? e.id : ''; ]]]"},
            "confirmation": {"text": "Dismiss this missed chore?"},
        },
        "styles": {
            "card": [
                {"display": f"[[[ return {e} ? 'block' : 'none'; ]]]"},
                {"border-radius": "12px"},
                {"padding": "8px 12px"},
                {"box-shadow": "none"},
            ],
            "grid": [
                {"grid-template-areas": "'n i'"},
                {"grid-template-columns": "1fr 30px"},
                {"align-items": "center"},
            ],
            "name": [{"justify-self": "start"}, {"font-size": "16px"}, {"white-space": "normal"}],
            "icon": [{"width": "22px"}],
        },
    }


async def async_missed_chores_card(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """The Kiosk bucket's missed-chores list, right under Parent Review and behind the same
    Parent PIN gate - see `missed.py` for what counts as missed."""
    sensor_id = (
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_missed_chores")
        or "sensor.family_dashboard_missed_chores"
    )
    header = {
        "type": "markdown",
        "content": (
            f"{{% set n = states('{sensor_id}') | int(0) %}}"
            "## Missed Chores ({{ n }})\n"
            "{% if n == 0 %}_No missed chores 🎉_"
            f"{{% elif n > {MISSED_ROWS} %}}_Showing the latest {MISSED_ROWS} of {{{{ n }}}}. "
            "Entries drop off after 30 days._{% endif %}"
        ),
    }
    clear_all = {
        "type": "custom:button-card",
        "entity": sensor_id,
        "name": "Clear all",
        "icon": "mdi:broom",
        "show_state": False,
        "tap_action": {
            "action": "perform-action",
            "perform_action": "family_dashboard.clear_missed_chores",
            "target": {"entity_id": sensor_id},
            "confirmation": {"text": "Clear every missed chore?"},
        },
        "styles": {
            "card": [
                {"display": "[[[ return Number(entity && entity.state) > 0 ? 'block' : 'none'; ]]]"},
                {"border-radius": "16px"},
                {"height": "44px"},
                {"box-shadow": "none"},
            ],
            "grid": [
                {"grid-template-areas": "'i n'"},
                {"grid-template-columns": "30px auto"},
                {"align-items": "center"},
                {"justify-items": "start"},
            ],
        },
    }
    return {
        "type": "conditional",
        "conditions": [{"entity": _PARENT_MODE, "state": "on"}],
        "card": {
            "type": "vertical-stack",
            "cards": [header, *(_missed_row(sensor_id, i) for i in range(MISSED_ROWS)), clear_all],
        },
    }
```

- In `async_kiosk_chores_cards`, right after the Parent Review append:
  `cards.append(await async_missed_chores_card(hass, entry))`.

- [ ] **Step 4: Run** `tests/test_dashboard.py`. Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Show the reminders toggle and the missed-chores list on the Chores tab"`

### Task 6: Docs, full suite, live validation

**Files:** `SETUP.md`, `CLAUDE.md` (Chores module specifics), the spec (refinements).

- [ ] **Step 1: Docs.**
  - `SETUP.md`, in the Chores section, add a "Chore reminders" note: turn it on per chore
    (Add Chore "Send reminders", or the Reminders pill); it fires at 4, 6 and 7 PM for chores
    due today that haven't been claimed; it needs the kid linked to an HA user who has the
    Companion App, or a manual notify mapping.
  - Add a "Missed chores" note: parent view under Parent Review; not claimed, or denied and
    not redone; 30 days; dismiss or Clear all.
  - `CLAUDE.md` Chores specifics: one bullet each for the reminders engine and for how misses
    are recorded (the task sensor, `checked_through`, the Store).
  - Spec: add the four refinements above.
- [ ] **Step 2: Full suite**: `tests/`. Expected: all pass.
- [ ] **Step 3: Live bench.** Copy the integration and restart; check the logs.
  - Over REST, flip `switch.family_dashboard_<chore>_reminders` on and confirm it's in the
    config entry.
  - Real scheduling path: give a member a manual notify mapping to a bench `notify.*` entity
    (from `GET /api/states`), and turn a due chore's reminders on. In the **bench copy only**,
    set `REMINDER_HOURS` to the next local hour and minute to a couple of minutes ahead
    (temporarily make `minute` a parameter too), restart, and wait. Confirm the notify entity's
    state timestamp changes, or a persistent notification appears. Then restore the bench copy
    from the repo and revert the mapping.
  - Seed misses: stop HA, set a daily chore's `checked_through` in
    `.storage/core.restore_state` to three days ago, start, and confirm the sensor lists the
    two days.
  - Browser (Playwright container, `kiosk`/`kiosk`): unlock the Parent PIN; confirm the
    missed rows render with no console errors; that tapping ✕ plus confirming removes that
    exact entry (the backend sensor count drops, and the right id is gone); that Clear all
    works; and that the Add Chore toggle and the Reminders pill render. If templated `data`
    doesn't resolve, switch to the spec's fallback (per-kid Clear) and retest.
- [ ] **Step 4: Commit** — `git commit -m "Document chore reminders and the missed-chores list"`
