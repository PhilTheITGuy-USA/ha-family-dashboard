"""Tests for `roster.py`'s mutate+reload+hide helpers - the shared machinery
`RosterFeatureSwitch`/`RosterCalendarMapSelect`/`RosterNotifyMapSelect` (see
test_settings_module.py) build on top of. Covers: features/calendar/notify mutations persist
into `entry.data` and reload the entry; disabling a feature HIDES (never deletes) that
member's entities via the entity registry's `hidden_by`, and re-enabling un-hides the SAME
entity_ids rather than creating new ones; chore/reward data itself survives a toggle-off/on
cycle untouched. Also covers whole-member Disable (`async_set_member_disabled`) and permanent
Delete (`async_delete_member`) - a distinct, broader concept from per-feature toggles.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_dashboard import roster
from custom_components.family_dashboard.const import DOMAIN


def _is_gone(hass: HomeAssistant, entity_id: str) -> bool:
    """A hidden-but-still-registered entity isn't necessarily `None` in `hass.states` - HA's
    own restore-state machinery leaves a synthetic `unavailable, restored=True` placeholder
    for any entity that was previously added and still has a registry entry, which is exactly
    the "hidden, not deleted" behavior wanted here. Absent entirely (never created in the
    first place) is `None`; hidden-after-having-existed is this placeholder - both count as
    "not currently live" for these tests."""
    state = hass.states.get(entity_id)
    return state is None or state.state == "unavailable"


def _member(member_id, name, features, **extra):
    return {
        "member_id": member_id,
        "name": name,
        "color": "Blue",
        "features": list(features),
        "ha_user_id": None,
        "calendar_entity_id": None,
        "notify_entity_id": None,
        "list_presets": [],
        **extra,
    }


async def _setup_entry(hass: HomeAssistant, roster_data, **extra_data) -> MockConfigEntry:
    entry = MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Family Dashboard",
        data={"roster": roster_data, **extra_data},
        source="user",
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_set_member_features_persists_and_reloads(hass: HomeAssistant):
    roster_data = [_member("ada", "Ada", ["lists"], list_presets=["shopping"])]
    entry = await _setup_entry(hass, roster_data)

    assert hass.states.get("todo.family_dashboard_ada_shopping") is not None
    assert hass.states.get("sensor.family_dashboard_ada_points") is None  # chores not enabled yet

    await roster.async_set_member_features(hass, entry, "ada", ["lists", "chores"])
    await hass.async_block_till_done()

    updated_member = entry.data["roster"][0]
    assert set(updated_member["features"]) == {"lists", "chores"}
    assert hass.states.get("sensor.family_dashboard_ada_points") is not None
    # Not mutated in place - a fresh dict/list each time (matches async_step_add_confirm's
    # own immutable-spread convention).
    assert updated_member is not roster_data[0]


async def test_disabling_chores_hides_not_deletes_entities(hass: HomeAssistant):
    roster_data = [_member("ada", "Ada", ["chores"])]
    chores = [
        {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}
    ]
    entry = await _setup_entry(hass, roster_data, chores=chores)

    points_entity_id = "sensor.family_dashboard_ada_points"
    task_entity_id = "sensor.family_dashboard_trash"
    assert hass.states.get(points_entity_id) is not None
    assert hass.states.get(task_entity_id) is not None

    registry = er.async_get(hass)
    points_unique_id = registry.async_get(points_entity_id).unique_id
    task_unique_id = registry.async_get(task_entity_id).unique_id

    await roster.async_set_member_features(hass, entry, "ada", [])
    await hass.async_block_till_done()

    # Entities no longer live (this feature's own async_setup_entry filters them out on
    # reload), but their registry entries survive, HIDDEN rather than gone.
    assert _is_gone(hass, points_entity_id)
    assert _is_gone(hass, task_entity_id)
    assert registry.entities[points_entity_id].hidden_by == er.RegistryEntryHider.INTEGRATION
    assert registry.entities[task_entity_id].hidden_by == er.RegistryEntryHider.INTEGRATION

    # The chore DEFINITION itself is untouched - only the member's own features list changed.
    assert entry.data["chores"] == chores

    # Re-enabling brings back the SAME entity_ids (same unique_id), un-hidden.
    await roster.async_set_member_features(hass, entry, "ada", ["chores"])
    await hass.async_block_till_done()

    assert hass.states.get(points_entity_id) is not None
    assert hass.states.get(task_entity_id) is not None
    assert registry.entities[points_entity_id].unique_id == points_unique_id
    assert registry.entities[task_entity_id].unique_id == task_unique_id
    assert registry.entities[points_entity_id].hidden_by is None
    assert registry.entities[task_entity_id].hidden_by is None


async def test_disable_member_hides_everything_regardless_of_current_features(hass: HomeAssistant):
    """Disable is a whole-member concept, separate from per-feature toggles: it hides the
    always-on Settings entities (name/color/etc, not covered by `_member_feature_entity_ids`)
    PLUS every feature's entities, keeping all data intact - and never hides the Enabled
    switch itself, or a disabled member could never be re-enabled.

    Unlike a per-feature toggle (which changes `CONF_FEATURES`, so the owning module's own
    `async_setup_entry` genuinely stops recreating that entity on reload), Disable never
    touches `CONF_FEATURES` - every entity is still recreated live on each reload regardless.
    So `hidden_by` here is REAL but purely a registry/cosmetic flag (matches this module's own
    docstring: it doesn't stop a custom Lovelace card from rendering) - check the registry
    flag directly, not `hass.states`, which stays fully live/available throughout."""
    roster_data = [_member("ada", "Ada", ["chores"])]
    chores = [
        {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}
    ]
    entry = await _setup_entry(hass, roster_data, chores=chores)

    color_entity_id = "select.family_dashboard_ada_color"
    points_entity_id = "sensor.family_dashboard_ada_points"
    enabled_entity_id = "switch.family_dashboard_ada_enabled"
    assert hass.states.get(color_entity_id) is not None
    assert hass.states.get(points_entity_id) is not None

    await roster.async_set_member_disabled(hass, entry, "ada", True)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert registry.entities[color_entity_id].hidden_by == er.RegistryEntryHider.INTEGRATION
    assert registry.entities[points_entity_id].hidden_by == er.RegistryEntryHider.INTEGRATION
    # The Enabled switch itself must stay visible - it's the only way back.
    assert hass.states.get(enabled_entity_id) is not None
    assert registry.entities[enabled_entity_id].hidden_by is None

    # Data untouched.
    assert entry.data["chores"] == chores
    assert entry.data["roster"][0]["disabled"] is True

    await roster.async_set_member_disabled(hass, entry, "ada", False)
    await hass.async_block_till_done()

    assert hass.states.get(color_entity_id) is not None
    assert hass.states.get(points_entity_id) is not None
    assert registry.entities[color_entity_id].hidden_by is None
    assert registry.entities[points_entity_id].hidden_by is None
    assert entry.data["roster"][0]["disabled"] is False


async def test_reenable_restores_per_feature_hidden_state_not_blanket_unhide(hass: HomeAssistant):
    """A feature that was already OFF before the member was disabled must stay hidden after
    re-enabling - re-enable re-derives hidden state from CURRENT features, it doesn't just
    blanket-unhide everything disable touched."""
    roster_data = [_member("ada", "Ada", ["chores"])]
    entry = await _setup_entry(hass, roster_data)
    points_entity_id = "sensor.family_dashboard_ada_points"

    # Turn chores off via the normal per-feature path first.
    await roster.async_set_member_features(hass, entry, "ada", [])
    await hass.async_block_till_done()
    assert _is_gone(hass, points_entity_id)

    await roster.async_set_member_disabled(hass, entry, "ada", True)
    await hass.async_block_till_done()
    await roster.async_set_member_disabled(hass, entry, "ada", False)
    await hass.async_block_till_done()

    # Still hidden - chores was never re-selected, only the whole-member disable was lifted.
    assert _is_gone(hass, points_entity_id)
    registry = er.async_get(hass)
    assert registry.entities[points_entity_id].hidden_by == er.RegistryEntryHider.INTEGRATION


async def test_delete_member_removes_entities_and_cleans_up_references(hass: HomeAssistant):
    """Permanent delete: every entity Ada owns is genuinely gone (not hidden), her roster
    entry disappears, her chore falls back to Unassigned (not deleted, not left dangling), the
    shared Family-calendar reference clears if it pointed at her, a sibling member's own data
    is untouched, and her linked HA user account itself is left alone."""
    ada_account = await hass.auth.async_create_user(name="Ada Account")
    roster_data = [
        _member("ada", "Ada", ["chores", "calendar"], ha_user_id=ada_account.id),
        _member("grace", "Grace", ["chores"]),
    ]
    chores = [
        {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"},
        {"chore_id": "dishes", "name": "Dishes", "points": 5, "frequency": "daily", "assigned_to": "grace"},
    ]
    entry = await _setup_entry(
        hass, roster_data, chores=chores, rewards=[], family_calendar_member_id="ada"
    )

    color_entity_id = "select.family_dashboard_ada_color"
    points_entity_id = "sensor.family_dashboard_ada_points"
    registry = er.async_get(hass)
    assert registry.async_get(color_entity_id) is not None
    assert registry.async_get(points_entity_id) is not None

    await roster.async_delete_member(hass, entry, "ada")
    await hass.async_block_till_done()

    # Genuinely gone from the registry - not hidden_by, actually removed. Including the
    # Enabled switch itself - deliberately excluded from the HIDE list (so a disabled member
    # can always be re-enabled) but that exclusion must NOT carry over to deletion, where
    # there's no reason to spare it.
    assert registry.async_get(color_entity_id) is None
    assert registry.async_get(points_entity_id) is None
    assert registry.async_get("switch.family_dashboard_ada_enabled") is None
    assert hass.states.get(color_entity_id) is None

    # Roster entry gone; Grace's own untouched.
    roster_ids = {m["member_id"] for m in entry.data["roster"]}
    assert roster_ids == {"grace"}

    # Ada's chore falls back to Unassigned; Grace's own chore is untouched.
    updated_chores = {c["chore_id"]: c["assigned_to"] for c in entry.data["chores"]}
    assert updated_chores == {"trash": None, "dishes": "grace"}
    assert hass.states.get("sensor.family_dashboard_dishes") is not None

    # Dangling Family-calendar reference cleared.
    assert entry.data["family_calendar_member_id"] is None

    # Her HA account itself is untouched.
    users = await hass.auth.async_get_users()
    assert any(u.id == ada_account.id for u in users)


async def test_set_member_calendar_updates_entry_data(hass: HomeAssistant):
    roster_data = [_member("ada", "Ada", ["calendar"])]
    entry = await _setup_entry(hass, roster_data)
    assert hass.states.get("calendar.family_dashboard_ada_calendar") is None  # nothing mapped

    await roster.async_set_member_calendar(hass, entry, "ada", "calendar.some_source")
    await hass.async_block_till_done()

    assert entry.data["roster"][0]["calendar_entity_id"] == "calendar.some_source"
    assert hass.states.get("calendar.family_dashboard_ada_calendar") is not None

    await roster.async_set_member_calendar(hass, entry, "ada", None)
    await hass.async_block_till_done()

    assert entry.data["roster"][0]["calendar_entity_id"] is None
    assert _is_gone(hass, "calendar.family_dashboard_ada_calendar")


async def test_set_member_notify_updates_entry_data(hass: HomeAssistant):
    roster_data = [_member("ada", "Ada", [])]
    entry = await _setup_entry(hass, roster_data)

    await roster.async_set_member_notify(hass, entry, "ada", "notify.adas_phone")
    await hass.async_block_till_done()
    assert entry.data["roster"][0]["notify_entity_id"] == "notify.adas_phone"

    await roster.async_set_member_notify(hass, entry, "ada", None)
    await hass.async_block_till_done()
    assert entry.data["roster"][0]["notify_entity_id"] is None
