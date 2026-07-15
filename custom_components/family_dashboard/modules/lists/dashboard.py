"""Dashboard-template contribution for the Lists module - one native `todo-list` card per
(roster member, selected preset) pair.

Unlike Calendar's `async_calendar_view_card` (called once per VIEW, since a single
week-planner-card natively overlays multiple calendars), Lists follows the general
module-contributes-cards pattern: called once per member, since each preset is its own
fully-isolated `todo.family_dashboard_<member_id>_<preset_key>` entity (see
`modules/lists/todo.py`) with no equivalent multi-list overlay card to exploit. `todo-list`
is a stock Lovelace card type - no HACS dependency, no backend API surface to drift between
HA versions.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ...const import CONF_FEATURES, CONF_LIST_PRESETS, LIST_PRESETS


async def async_lists_cards_for_member(
    hass: HomeAssistant, entry: ConfigEntry, member: dict
) -> list[dict]:
    """One todo-list card per preset this member selected, titled "<Name> <Preset>" (the
    card's own default title would otherwise be the device-qualified friendly name, e.g.
    "Family Dashboard Ada Shopping" - redundant on a per-person dashboard). Empty list if the
    member has no selected presets (not opted into Lists, or opted in with none selected), or
    if Lists is currently toggled off for them - `list_presets` is deliberately left intact by
    a toggle-off (see `roster.async_set_member_features`) so re-enabling restores the same
    selection, which means this must check the feature flag too, not just the preset list.
    """
    if "lists" not in member.get(CONF_FEATURES, []):
        return []
    return [
        {
            "type": "todo-list",
            "entity": f"todo.family_dashboard_{member['member_id']}_{preset_key}",
            "title": f"{member['name']} {LIST_PRESETS[preset_key]['name']}",
        }
        for preset_key in member.get(CONF_LIST_PRESETS, [])
    ]
