"""One-time upgrade of pre-scheduling chore data, run at the start of every entry setup.

Chores used to store a `frequency` (daily/weekly/one_time) that nothing enforced; they now
store `repeat` plus `schedule_days`/`month_days` (see `schedule.upgrade_chore` for the exact
mapping). The Frequency select entities that edited the old field are retired along with it.
Idempotent: an already-upgraded install changes nothing.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from ...const import CONF_CHORES, DOMAIN
from .schedule import upgrade_chore


@callback
def async_upgrade_chores(hass: HomeAssistant, entry: ConfigEntry) -> None:
    chores = entry.data.get(CONF_CHORES, [])
    upgraded = [upgrade_chore(chore) for chore in chores]
    if any(new is not old for new, old in zip(upgraded, chores)):
        # Setup is already running, so no reload - the platforms forwarded next read this.
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_CHORES: upgraded})

    registry = er.async_get(hass)
    retired = [f"{entry.entry_id}_new_chore_frequency"]
    retired += [f"{entry.entry_id}_{chore['chore_id']}_frequency" for chore in upgraded]
    for unique_id in retired:
        if entity_id := registry.async_get_entity_id("select", DOMAIN, unique_id):
            registry.async_remove(entity_id)
