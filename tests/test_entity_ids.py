"""Entity IDs stay `<domain>.family_dashboard_<name>` no matter how the device is set up.

The dashboard hardcodes IDs like `select.family_dashboard_<member>_avatar`, so a new entity
whose ID HA derives from the device's area or user-given name (e.g.
`select.living_room_family_dashboard_...`) silently breaks its card. Covers: new entities
pin the canonical ID even after the device is renamed, and setup repairs IDs that already
picked up such a prefix - without losing restored state, and without touching an ID the
user customised or taking one that's already in use.

The pytest harness's HA predates the area prefix itself, so the prevention test renames the
device instead - same derivation path (device name -> entity ID), reproducible here.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.family_dashboard.const import DOMAIN


def _member(name, member_id, features=("calendar", "lists", "chores")):
    return {
        "member_id": member_id,
        "name": name,
        "color": "Blue",
        "features": list(features),
        "ha_user_id": None,
        "calendar_entity_id": None,
        "notify_entity_id": None,
        "list_presets": ["to_do"],
    }


def _entry(roster: list[dict], chores=None) -> MockConfigEntry:
    return MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Family Dashboard",
        data={"roster": roster, "chores": chores or [], "rewards": []},
        source="user",
        unique_id=DOMAIN,
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _fd_entity_ids(hass: HomeAssistant, entry: MockConfigEntry) -> list[str]:
    return [
        e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    ]


async def test_new_entities_keep_canonical_ids_after_device_renamed(hass: HomeAssistant):
    entry = _entry([_member("Ada", "ada")])
    entry.add_to_hass(hass)
    await _setup(hass, entry)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    dev_reg.async_update_device(device.id, name_by_user="Kitchen Screen")

    before = set(_fd_entity_ids(hass, entry))
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "roster": [*entry.data["roster"], _member("Grace", "grace")],
            "chores": [
                {
                    "chore_id": "trash",
                    "name": "Trash",
                    "points": 10,
                    "frequency": "daily",
                    "assigned_to": "grace",
                }
            ],
        },
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    new_ids = set(_fd_entity_ids(hass, entry)) - before
    assert "select.family_dashboard_grace_avatar" in new_ids
    assert "sensor.family_dashboard_grace_points" in new_ids
    assert "select.family_dashboard_trash_assigned_to" in new_ids
    assert [i for i in new_ids if not i.split(".", 1)[1].startswith("family_dashboard_")] == []


async def test_setup_repairs_area_prefixed_ids_and_keeps_restored_state(hass: HomeAssistant):
    entry = _entry([_member("Ada", "ada", features=("chores",))])
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_ada_points",
        suggested_object_id="living_room_family_dashboard_ada_points",
        config_entry=entry,
    )
    mock_restore_cache(hass, [State("sensor.living_room_family_dashboard_ada_points", "42")])

    await _setup(hass, entry)

    assert ent_reg.async_get("sensor.living_room_family_dashboard_ada_points") is None
    assert ent_reg.async_get("sensor.family_dashboard_ada_points") is not None
    assert hass.states.get("sensor.family_dashboard_ada_points").state == "42"
    assert hass.states.get("sensor.living_room_family_dashboard_ada_points") is None


async def test_setup_leaves_user_customised_ids_alone(hass: HomeAssistant):
    entry = _entry([_member("Ada", "ada", features=("chores",))])
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_ada_points",
        suggested_object_id="ada_star_count",
        config_entry=entry,
    )

    await _setup(hass, entry)

    assert ent_reg.async_get("sensor.ada_star_count") is not None
    assert ent_reg.async_get("sensor.family_dashboard_ada_points") is None


async def test_setup_skips_repair_when_canonical_id_is_taken(hass: HomeAssistant):
    entry = _entry([_member("Ada", "ada", features=("chores",))])
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    # Something else already owns the canonical ID.
    ent_reg.async_get_or_create(
        "sensor", "other_integration", "x", suggested_object_id="family_dashboard_ada_points"
    )
    ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_ada_points",
        suggested_object_id="living_room_family_dashboard_ada_points",
        config_entry=entry,
    )

    await _setup(hass, entry)

    assert ent_reg.async_get("sensor.living_room_family_dashboard_ada_points") is not None
    assert ent_reg.async_get("sensor.family_dashboard_ada_points").platform == "other_integration"
