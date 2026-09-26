"""Keep every entity's ID at `<domain>.family_dashboard_<name>`.

The dashboard (and several modules) hardcode IDs in that shape, e.g.
`select.family_dashboard_<member>_avatar`. HA only derives a new entity's ID once, at first
registration, from the device's area and current name plus the entity name - so once the
shared "Family Dashboard" device is assigned to an area or renamed, every entity registered
after that (a new member, chore, reward, or a feature turned on later) came out as e.g.
`select.living_room_family_dashboard_...` and its dashboard card pointed at nothing.

`pin_entity_ids` wraps each top-level platform's `async_add_entities`, so every entity
states its own canonical ID up front (HA then skips the area/device derivation entirely).
`async_repair_prefixed_entity_ids` renames IDs an earlier version already let through.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, split_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

_OBJECT_ID_PREFIX = "family_dashboard"


def canonical_object_id(name: str) -> str:
    """What HA would derive for an entity `name` on the "Family Dashboard" device, with no
    area and no user rename."""
    return slugify(f"{_OBJECT_ID_PREFIX} {name}")


def pin_entity_ids(domain: str, async_add_entities: AddEntitiesCallback) -> AddEntitiesCallback:
    """Wrap `async_add_entities` so each new entity pins its canonical ID first. Entities
    that already set `self.entity_id` themselves are left as they are, and HA still uses the
    registry's ID for anything already registered (see `async_repair_prefixed_entity_ids`)."""

    def _add(new_entities: Iterable[Entity], update_before_add: bool = False, **kwargs: Any):
        new_entities = list(new_entities)
        for entity in new_entities:
            name = getattr(entity, "_attr_name", None)
            if entity.entity_id is None and isinstance(name, str) and name:
                entity.entity_id = f"{domain}.{canonical_object_id(name)}"
        async_add_entities(new_entities, update_before_add, **kwargs)

    return _add


@callback
def async_repair_prefixed_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rename `<domain>.<anything>_family_dashboard_<name>` back to
    `<domain>.family_dashboard_<name>`. Runs after the platforms are loaded, so HA renames
    each live entity in place and its current state (points, claims) carries over.

    Deliberately narrow: an ID that doesn't end in the entity's own canonical ID was
    customised by the user and is left alone, and so is one whose canonical ID is already
    taken."""
    ent_reg = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if not reg_entry.original_name:
            continue
        domain, object_id = split_entity_id(reg_entry.entity_id)
        expected = canonical_object_id(reg_entry.original_name)
        if object_id == expected or not object_id.endswith(f"_{expected}"):
            continue
        target = f"{domain}.{expected}"
        if ent_reg.async_is_registered(target) or hass.states.get(target) is not None:
            _LOGGER.warning(
                "Family Dashboard: can't rename %s to %s - that ID is already in use",
                reg_entry.entity_id,
                target,
            )
            continue
        _LOGGER.info("Family Dashboard: renaming %s to %s", reg_entry.entity_id, target)
        ent_reg.async_update_entity(reg_entry.entity_id, new_entity_id=target)
