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

    async def async_flush(self) -> None:
        """Write now, instead of after the save delay - called on unload, so a reload (which
        every chore edit triggers) doesn't load the file before a pending change is saved."""
        await self._store.async_save({"entries": self._entries})

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
