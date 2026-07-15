"""Family Dashboard's own `todo` platform - one `FamilyDashboardTodoListEntity` per
(roster member, selected preset) pair, e.g. `todo.family_dashboard_ada_shopping` and
`todo.family_dashboard_grace_shopping` are separate entities, fully isolated per person -
the whole reason Lists moved from a household-wide toggle to per-member (see const.py's
FEATURES docstring). Deliberately NOT chained into HA's core `local_todo` config flow -
owning the entity directly means no dependency on another integration's config-flow
internals staying stable across HA versions, and no separate config entries to manage.

Re-exported by the top-level `todo.py` shim (HA requires platform files at the
integration's top level - see modules/__init__.py's docstring).
"""
from __future__ import annotations

import dataclasses
import uuid

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from ...const import CONF_FEATURES, CONF_LIST_PRESETS, CONF_ROSTER, DOMAIN, LIST_PRESETS


def member_feature_entity_ids(entry: ConfigEntry, member: dict) -> list[tuple[str, str]]:
    """(domain, unique_id) pairs for this member's Lists-feature entities - used by
    `roster.async_set_member_features` to hide/un-hide them in the entity registry when the
    feature is toggled off/on. Takes the whole `member` dict (not just `member_id`) since the
    unique_ids depend on their selected presets too."""
    member_id = member["member_id"]
    return [
        ("todo", f"{entry.entry_id}_{member_id}_{preset_key}_list")
        for preset_key in member.get(CONF_LIST_PRESETS, [])
    ]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entities = [
        FamilyDashboardTodoListEntity(entry, member, preset_key)
        for member in entry.data[CONF_ROSTER]
        if "lists" in member.get(CONF_FEATURES, [])
        for preset_key in member.get(CONF_LIST_PRESETS, [])
    ]
    async_add_entities(entities)


@dataclasses.dataclass
class TodoListExtraStoredData(ExtraStoredData):
    """Persisted item collection for one FamilyDashboardTodoListEntity - a plain State's
    single string can't hold a list of items, so this uses RestoreEntity's extra-data
    mechanism instead (same "own entity platform + RestoreEntity, no YAML" principle
    modules/settings/ uses for scalar values, just the structured-data variant).
    """

    items: list[dict]

    def as_dict(self) -> dict:
        return {"items": self.items}

    @classmethod
    def from_dict(cls, restored: dict) -> "TodoListExtraStoredData":
        return cls(items=restored.get("items", []))


class FamilyDashboardTodoListEntity(TodoListEntity, RestoreEntity):
    """One preset to-do list belonging to one roster member."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
    )

    def __init__(self, entry: ConfigEntry, member: dict, preset_key: str) -> None:
        preset = LIST_PRESETS[preset_key]
        self._entry = entry
        self._member_id = member["member_id"]
        self._attr_name = f"{member['name']} {preset['name']}"
        self._attr_icon = preset["icon"]
        self._attr_unique_id = f"{entry.entry_id}_{self._member_id}_{preset_key}_list"
        self._attr_todo_items = []

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Family Dashboard",
            manufacturer="Family Dashboard",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        extra_data = await self.async_get_last_extra_data()
        if extra_data is not None:
            restored = TodoListExtraStoredData.from_dict(extra_data.as_dict())
            self._attr_todo_items = [
                TodoItem(
                    summary=item["summary"],
                    uid=item["uid"],
                    status=TodoItemStatus(item["status"]),
                )
                for item in restored.items
            ]

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        return TodoListExtraStoredData(
            items=[dataclasses.asdict(item) for item in self.todo_items or []]
        )

    async def async_create_todo_item(self, item: TodoItem) -> None:
        item.uid = item.uid or uuid.uuid4().hex
        item.status = item.status or TodoItemStatus.NEEDS_ACTION
        self._attr_todo_items = [*(self.todo_items or []), item]
        self.async_write_ha_state()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        self._attr_todo_items = [
            item if existing.uid == item.uid else existing for existing in self.todo_items or []
        ]
        self.async_write_ha_state()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        self._attr_todo_items = [
            item for item in self.todo_items or [] if item.uid not in uids
        ]
        self.async_write_ha_state()
