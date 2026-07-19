"""Shared roster-mutation helpers - the single place (besides
`FamilyDashboardOptionsFlow.async_step_add_confirm`, which adds a brand-new member) that
mutates `entry.data["roster"]` and reloads the config entry. This module is for editing an
EXISTING member's features/calendar/notify mapping from live entities on the Settings
dashboard (`modules/settings/switch.py`'s `RosterFeatureSwitch`,
`modules/settings/select.py`'s `RosterCalendarMapSelect`/`RosterNotifyMapSelect`) - unlike
Name/Color/Avatar (plain `RestoreEntity` local state, never touching `entry.data` again after
initial setup), features/calendar/notify are structural: `__init__.py`'s
`_platforms_for_entry` and each feature module's own roster filtering read `entry.data`
directly at setup time, so a change here is only real once persisted + reloaded.

Feature toggles need one extra step beyond a plain mutate+reload: `hidden_by` in the entity
registry. Disabling a feature must HIDE that member's entities for it, never delete them (see
CLAUDE.md/claude-code-kickoff.md's explicit requirement) - a plain reload alone already stops
RE-CREATING those entities (each module's own `async_setup_entry` filters by `CONF_FEATURES`),
but their registry entries would otherwise just go quiet/orphaned rather than being marked
hidden. Each feature module owns its own entity-id shape and exposes a
`member_feature_entity_ids(...)` hook (see `modules/calendar/calendar.py`,
`modules/lists/todo.py`, `modules/chores/sensor.py`) so this module stays ignorant of it,
matching `modules/__init__.py`'s "each module owns everything about itself" principle.

Whole-member Remove (`async_set_member_disabled`/`async_delete_member`) is a separate concept
from per-feature toggles above, not built on top of them: Disable hides EVERY entity a member
owns regardless of their feature selection while keeping all data intact and reversible;
Delete genuinely removes the member and their entities with no undo. Note `hidden_by` is
cosmetic only (HA's own native entity-list/history UI) - it does NOT stop a custom Lovelace
card with an explicit entity_id from rendering, so the actual "don't show this member
anywhere" mechanism for Disable is `dashboard/registry.py`'s own `entry.data`-level roster
filtering, not the registry hide call.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CALENDAR_ENTITY_ID,
    CONF_CHORES,
    CONF_DISABLED,
    CONF_FEATURES,
    CONF_NOTIFY_ENTITY_ID,
    CONF_REWARDS,
    CONF_ROSTER,
    DOMAIN,
    FEATURES,
)


async def async_update_member_fields(
    hass: HomeAssistant, entry: ConfigEntry, member_id: str, **field_updates: Any
) -> None:
    """Immutable roster patch (never mutate a member dict in place - same convention as
    `FamilyDashboardOptionsFlow.async_step_add_confirm`) + `async_update_entry` +
    `async_reload`. The low-level primitive every helper below calls."""
    roster = [
        {**member, **field_updates} if member["member_id"] == member_id else member
        for member in entry.data[CONF_ROSTER]
    ]
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_ROSTER: roster})
    await hass.config_entries.async_reload(entry.entry_id)


def _member_feature_entity_ids(
    entry: ConfigEntry, member: dict, feature_key: str
) -> list[tuple[str, str]]:
    """Dispatches to the owning module's own hook - see this module's docstring. Imported
    locally (not at module level) to avoid import-time circular dependencies, same reasoning
    as `modules/chores/text.py`'s own local import."""
    from .modules.calendar.calendar import member_feature_entity_ids as calendar_ids
    from .modules.chores.sensor import member_feature_entity_ids as chores_ids
    from .modules.lists.todo import member_feature_entity_ids as lists_ids

    if feature_key == "calendar":
        return calendar_ids(entry, member["member_id"])
    if feature_key == "lists":
        return lists_ids(entry, member)
    if feature_key == "chores":
        return chores_ids(entry, member["member_id"])
    return []


def _always_on_member_entity_ids(entry: ConfigEntry, member_id: str) -> list[tuple[str, str]]:
    """(domain, unique_id) pairs for the Settings-owned entities every member always has,
    regardless of any `CONF_FEATURES` selection - `_member_feature_entity_ids` above only
    covers the three feature-gated modules, not these. Exact unique_id patterns confirmed
    against `modules/settings/{text,select,date,switch}.py`. Deliberately EXCLUDES the
    "Enabled" switch's own entity (`modules/settings/switch.py`'s `RosterEnabledSwitch`) -
    that one control must never hide itself, or a disabled member could never be re-enabled
    from the dashboard."""
    prefix = f"{entry.entry_id}_{member_id}"
    ids: list[tuple[str, str]] = [
        ("text", f"{prefix}_name"),
        ("select", f"{prefix}_color"),
        ("select", f"{prefix}_avatar"),
        ("select", f"{prefix}_calendar_map"),
        ("select", f"{prefix}_notify_map"),
        ("date", f"{prefix}_birthdate"),
        ("switch", f"{prefix}_shown"),
    ]
    ids += [("switch", f"{prefix}_feature_{key}") for key in FEATURES]
    return ids


def _set_hidden(hass: HomeAssistant, entity_ids: list[tuple[str, str]], *, hidden: bool) -> None:
    registry = er.async_get(hass)
    for domain, unique_id in entity_ids:
        entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        if entity_id is not None:
            registry.async_update_entity(
                entity_id,
                hidden_by=er.RegistryEntryHider.INTEGRATION if hidden else None,
            )


async def async_set_member_features(
    hass: HomeAssistant, entry: ConfigEntry, member_id: str, features: list[str]
) -> None:
    """Diffs the member's CURRENT features (from `entry.data`, before this call's own update)
    against the requested `features`: hides each removed feature's entities, un-hides each
    added feature's (a never-before-enabled feature has nothing to un-hide - its fresh
    entities from the coming reload default to unhidden anyway). Then persists + reloads.
    """
    member = next(m for m in entry.data[CONF_ROSTER] if m["member_id"] == member_id)
    old_features = set(member.get(CONF_FEATURES, []))
    new_features = set(features)

    for removed in old_features - new_features:
        _set_hidden(hass, _member_feature_entity_ids(entry, member, removed), hidden=True)
    for added in new_features - old_features:
        _set_hidden(hass, _member_feature_entity_ids(entry, member, added), hidden=False)

    await async_update_member_fields(hass, entry, member_id, **{CONF_FEATURES: features})


async def async_set_member_disabled(
    hass: HomeAssistant, entry: ConfigEntry, member_id: str, disabled: bool
) -> None:
    """Whole-member Disable/re-enable - hides EVERY entity belonging to this member (the
    always-on Settings ones above, plus every feature module's entities regardless of the
    member's current per-feature selection - a feature they never enabled simply has nothing
    to hide, `_set_hidden` already no-ops on unresolved entity_ids), keeping all their data
    intact. Re-enabling doesn't just blanket-unhide everything: it re-derives per-feature
    hidden state from the member's CURRENT `CONF_FEATURES` (same logic
    `async_set_member_features` uses) so a feature that was already off before the member was
    disabled stays off after re-enabling, rather than coming back visible.

    This ONLY affects the entity registry's cosmetic `hidden_by` flag (HA's own native
    entity-list/history UI) - the REAL "don't show this member on the generated dashboard"
    mechanism is `dashboard/registry.py`'s own `entry.data`-level filtering, since a custom
    Lovelace card with an explicit entity_id renders regardless of `hidden_by`.
    """
    member = next(m for m in entry.data[CONF_ROSTER] if m["member_id"] == member_id)

    if disabled:
        always_on = _always_on_member_entity_ids(entry, member_id)
        all_feature_ids = [
            eid
            for feature_key in FEATURES
            for eid in _member_feature_entity_ids(entry, member, feature_key)
        ]
        _set_hidden(hass, [*always_on, *all_feature_ids], hidden=True)
    else:
        _set_hidden(hass, _always_on_member_entity_ids(entry, member_id), hidden=False)
        selected = set(member.get(CONF_FEATURES, []))
        for feature_key in FEATURES:
            ids = _member_feature_entity_ids(entry, member, feature_key)
            _set_hidden(hass, ids, hidden=feature_key not in selected)

    await async_update_member_fields(hass, entry, member_id, **{CONF_DISABLED: disabled})


async def async_delete_member(hass: HomeAssistant, entry: ConfigEntry, member_id: str) -> None:
    """Permanently removes this member: every entity they own is genuinely removed from the
    registry (not hidden - there's nothing to restore to, same reasoning
    `modules/chores/crud.py`'s own chore/reward deletion gives), the roster entry itself is
    dropped, and any chore/reward assigned to them falls back to Unassigned (`assigned_to:
    None`, the same permissive convention `modules/chores/crud.py`'s `member_display_name`/
    `resolve_assigned_to` already use for a stale/missing member_id - the item itself is kept,
    it isn't "this member's data"). The shared Family calendar (if any) is unaffected by
    member deletion - it's auto-detected by calendar name, not tied to any roster member (see
    `modules/calendar/dashboard.py`'s `_family_calendar_entity`).

    The member's linked HA user account (if any) is left completely untouched - only the
    roster record disappears, so on the next reload `dashboard/registry.py`'s bucket
    computation naturally treats that account as unlinked (falls back to Kiosk), matching
    what disabling them already does. No precedent anywhere in this codebase for the
    integration itself deleting/deactivating an HA account, and none is added here.
    """
    # Local import to avoid a circular dependency (modules/settings/switch.py itself imports
    # this module as `roster_helpers`), same convention as `_member_feature_entity_ids`'s own
    # local imports.
    from .modules.settings.switch import enabled_switch_unique_id

    member = next(m for m in entry.data[CONF_ROSTER] if m["member_id"] == member_id)

    registry = er.async_get(hass)
    all_ids = [
        ("switch", enabled_switch_unique_id(entry, member_id)),
        *_always_on_member_entity_ids(entry, member_id),
        *(
            eid
            for feature_key in FEATURES
            for eid in _member_feature_entity_ids(entry, member, feature_key)
        ),
    ]
    for domain, unique_id in all_ids:
        entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        if entity_id is not None:
            registry.async_remove(entity_id)

    roster = [m for m in entry.data[CONF_ROSTER] if m["member_id"] != member_id]
    chores = [
        {**c, "assigned_to": None} if c["assigned_to"] == member_id else c
        for c in entry.data.get(CONF_CHORES, [])
    ]
    rewards = [
        {**r, "assigned_to": None} if r["assigned_to"] == member_id else r
        for r in entry.data.get(CONF_REWARDS, [])
    ]

    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_ROSTER: roster,
            CONF_CHORES: chores,
            CONF_REWARDS: rewards,
        },
    )
    await hass.config_entries.async_reload(entry.entry_id)


async def async_set_member_calendar(
    hass: HomeAssistant, entry: ConfigEntry, member_id: str, calendar_entity_id: str | None
) -> None:
    """No `hidden_by` concerns - the Calendar feature toggle itself is untouched, only which
    source entity it forwards to. `None` is a valid value (the "unmap" case)."""
    await async_update_member_fields(
        hass, entry, member_id, **{CONF_CALENDAR_ENTITY_ID: calendar_entity_id}
    )


async def async_set_member_notify(
    hass: HomeAssistant, entry: ConfigEntry, member_id: str, notify_entity_id: str | None
) -> None:
    """Sets the MANUAL notify override - see `modules/calendar/reminders.py`'s
    `async_resolve_member_notify_targets` for how this interacts with auto-resolution from a
    linked HA user's mobile-app device. `None` clears the manual override (falls back to
    auto-resolution, or no target if unlinked)."""
    await async_update_member_fields(
        hass, entry, member_id, **{CONF_NOTIFY_ENTITY_ID: notify_entity_id}
    )
