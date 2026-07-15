"""Add/Modify/Delete for Chores & Rewards - mirrors `roster.py`'s mutate+reload shape, but
scoped to `entry.data["chores"]`/`["rewards"]` and living inside `modules/chores/` (unlike
roster fields, which span multiple modules, chores/rewards are entirely owned by this one
module).

Deletion is a REAL removal (`entity_registry.async_remove`), not `hidden_by` - unlike
disabling a feature (which has a prior state to restore to on re-enable), a deleted chore/
reward has nothing to restore; re-adding "the same" chore later creates a genuinely new
`chore_id` via `slugify_unique`, not the old one back.
"""
from __future__ import annotations

import homeassistant.components.number as number_component
import homeassistant.components.select as select_component
import homeassistant.components.text as text_component
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ...const import CHORE_FREQUENCIES, CONF_CHORES, CONF_REWARDS, CONF_ROSTER, DOMAIN
from ...util import slugify_unique
from .sensor import _deny_reason_unique_id, _task_unique_id

_COMPONENT_MAP = {
    "text": text_component.DATA_COMPONENT,
    "number": number_component.DATA_COMPONENT,
    "select": select_component.DATA_COMPONENT,
}

# A chore/reward can genuinely have no owner (explicit user request) - this sentinel is the
# assigned-to selects' extra dropdown option (modules/chores/select.py), living here (not
# there) so both `select.py` (which already imports this module) and this module's own
# scratch-field creation functions below share one definition without a circular import.
UNASSIGNED_OPTION = "Unassigned"


def member_display_name(entry: ConfigEntry, member_id: str | None) -> str:
    """`UNASSIGNED_OPTION` for `None` (or a stale/removed member_id), else that member's live
    display name - what an assigned-to select's `current_option` should show."""
    if member_id is None:
        return UNASSIGNED_OPTION
    member = next((m for m in entry.data[CONF_ROSTER] if m["member_id"] == member_id), None)
    return member["name"] if member else UNASSIGNED_OPTION


def resolve_assigned_to(entry: ConfigEntry, option: str) -> str | None:
    """The reverse of `member_display_name` - `None` for `UNASSIGNED_OPTION` (or a name that
    doesn't match any current roster member, a permissive fallback rather than an error, since
    "assigned to nobody" is now a valid, expected state, not a mistake to guard against)."""
    if option == UNASSIGNED_OPTION:
        return None
    member = next((m for m in entry.data[CONF_ROSTER] if m["name"] == option), None)
    return member["member_id"] if member else None


def _entity(hass: HomeAssistant, domain: str, unique_id: str):
    """Resolve a scratch/field entity by its own unique_id, same registry-lookup pattern as
    `modules/calendar/events.py`'s own `_entity` helper."""
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    if entity_id is None:
        return None
    component = hass.data.get(_COMPONENT_MAP[domain])
    return component.get_entity(entity_id) if component else None


async def _async_persist(hass: HomeAssistant, entry: ConfigEntry, **data_updates) -> None:
    hass.config_entries.async_update_entry(entry, data={**entry.data, **data_updates})
    await hass.config_entries.async_reload(entry.entry_id)


async def async_add_chore(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    name: str,
    points: int,
    frequency: str,
    assigned_to: str | None,
) -> str:
    existing_ids = {c["chore_id"] for c in entry.data.get(CONF_CHORES, [])}
    chore_id = slugify_unique(name, existing_ids)
    chores = [
        *entry.data.get(CONF_CHORES, []),
        {
            "chore_id": chore_id,
            "name": name,
            "points": points,
            "frequency": frequency,
            "assigned_to": assigned_to,
        },
    ]
    await _async_persist(hass, entry, **{CONF_CHORES: chores})
    return chore_id


async def async_add_reward(
    hass: HomeAssistant, entry: ConfigEntry, *, name: str, cost: int, assigned_to: str | None
) -> str:
    existing_ids = {r["reward_id"] for r in entry.data.get(CONF_REWARDS, [])}
    reward_id = slugify_unique(name, existing_ids)
    rewards = [
        *entry.data.get(CONF_REWARDS, []),
        {"reward_id": reward_id, "name": name, "cost": cost, "assigned_to": assigned_to},
    ]
    await _async_persist(hass, entry, **{CONF_REWARDS: rewards})
    return reward_id


async def async_update_chore_field(hass: HomeAssistant, entry: ConfigEntry, chore_id: str, **field_updates) -> None:
    chores = [
        {**c, **field_updates} if c["chore_id"] == chore_id else c
        for c in entry.data.get(CONF_CHORES, [])
    ]
    await _async_persist(hass, entry, **{CONF_CHORES: chores})


async def async_update_reward_field(hass: HomeAssistant, entry: ConfigEntry, reward_id: str, **field_updates) -> None:
    rewards = [
        {**r, **field_updates} if r["reward_id"] == reward_id else r
        for r in entry.data.get(CONF_REWARDS, [])
    ]
    await _async_persist(hass, entry, **{CONF_REWARDS: rewards})


def chore_field_entity_ids(entry: ConfigEntry, chore_id: str) -> list[tuple[str, str]]:
    """(domain, unique_id) pairs for everything belonging to one chore - the task sensor, its
    claim/approve buttons, and its four per-item edit fields. Used by `async_delete_chore` to
    genuinely remove all of them from the entity registry."""
    task_uid = _task_unique_id(entry, chore_id, "chore")
    return [
        ("sensor", task_uid),
        ("button", f"{task_uid}_claim"),
        ("button", f"{task_uid}_approve"),
        ("text", f"{entry.entry_id}_{chore_id}_name"),
        ("number", f"{entry.entry_id}_{chore_id}_points"),
        ("select", f"{entry.entry_id}_{chore_id}_frequency"),
        ("select", f"{entry.entry_id}_{chore_id}_assigned_to"),
        ("text", _deny_reason_unique_id(entry, chore_id, "chore")),
    ]


def reward_field_entity_ids(entry: ConfigEntry, reward_id: str) -> list[tuple[str, str]]:
    """Same as `chore_field_entity_ids`, for one reward (no frequency field)."""
    task_uid = _task_unique_id(entry, reward_id, "reward")
    return [
        ("sensor", task_uid),
        ("button", f"{task_uid}_claim"),
        ("button", f"{task_uid}_approve"),
        ("text", f"{entry.entry_id}_{reward_id}_name"),
        ("number", f"{entry.entry_id}_{reward_id}_cost"),
        ("select", f"{entry.entry_id}_{reward_id}_assigned_to"),
        ("text", _deny_reason_unique_id(entry, reward_id, "reward")),
    ]


def _remove_entities(hass: HomeAssistant, entity_ids: list[tuple[str, str]]) -> None:
    registry = er.async_get(hass)
    for domain, unique_id in entity_ids:
        entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        if entity_id is not None:
            registry.async_remove(entity_id)


async def async_delete_chore(hass: HomeAssistant, entry: ConfigEntry, chore_id: str) -> None:
    # Removal happens BEFORE the data/reload update, while the registry can still resolve
    # these entity_ids - filtering the item out of entry.data first would leave them as
    # permanently "hidden-looking" orphans instead of genuinely gone.
    _remove_entities(hass, chore_field_entity_ids(entry, chore_id))
    chores = [c for c in entry.data.get(CONF_CHORES, []) if c["chore_id"] != chore_id]
    await _async_persist(hass, entry, **{CONF_CHORES: chores})


async def async_delete_reward(hass: HomeAssistant, entry: ConfigEntry, reward_id: str) -> None:
    _remove_entities(hass, reward_field_entity_ids(entry, reward_id))
    rewards = [r for r in entry.data.get(CONF_REWARDS, []) if r["reward_id"] != reward_id]
    await _async_persist(hass, entry, **{CONF_REWARDS: rewards})


async def async_create_chore_from_scratch_fields(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Add Chore popup's submit action - reads the scratch fields, creates the chore, clears
    the fields. Mirrors `modules/calendar/events.py`'s `async_create_event_from_scratch_fields`.
    A blank name is a silent no-op (same "blank name = nothing to add" convention the wizard's
    own `add_chore` loop uses), not an error.
    """
    name_entity = _entity(hass, "text", f"{entry.entry_id}_new_chore_name")
    points_entity = _entity(hass, "number", f"{entry.entry_id}_new_chore_points")
    frequency_entity = _entity(hass, "select", f"{entry.entry_id}_new_chore_frequency")
    assigned_entity = _entity(hass, "select", f"{entry.entry_id}_new_chore_assigned_to")

    name = ((name_entity.native_value if name_entity else "") or "").strip()
    if not name:
        return

    assigned_option = assigned_entity.current_option if assigned_entity else UNASSIGNED_OPTION
    assigned_to = resolve_assigned_to(entry, assigned_option)

    frequency_label = frequency_entity.current_option if frequency_entity else None
    label_to_key = {v: k for k, v in CHORE_FREQUENCIES.items()}
    frequency = label_to_key.get(frequency_label, "daily")

    points = int(points_entity.native_value) if points_entity and points_entity.native_value is not None else 5

    await async_add_chore(
        hass, entry, name=name, points=points, frequency=frequency, assigned_to=assigned_to
    )

    if name_entity:
        await name_entity.async_set_value("")
    if points_entity:
        await points_entity.async_set_native_value(5)


async def async_create_reward_from_scratch_fields(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Same shape as `async_create_chore_from_scratch_fields`, for the Add Reward popup (no
    frequency field)."""
    name_entity = _entity(hass, "text", f"{entry.entry_id}_new_reward_name")
    cost_entity = _entity(hass, "number", f"{entry.entry_id}_new_reward_cost")
    assigned_entity = _entity(hass, "select", f"{entry.entry_id}_new_reward_assigned_to")

    name = ((name_entity.native_value if name_entity else "") or "").strip()
    if not name:
        return

    assigned_option = assigned_entity.current_option if assigned_entity else UNASSIGNED_OPTION
    assigned_to = resolve_assigned_to(entry, assigned_option)

    cost = int(cost_entity.native_value) if cost_entity and cost_entity.native_value is not None else 50

    await async_add_reward(hass, entry, name=name, cost=cost, assigned_to=assigned_to)

    if name_entity:
        await name_entity.async_set_value("")
    if cost_entity:
        await cost_entity.async_set_native_value(50)
