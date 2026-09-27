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
    # Local import - sensor.py starts this engine.
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
                "Family Dashboard: chore reminder for %s to %s failed: %s",
                member["name"],
                targets,
                err,
            )


def async_start_chore_reminders(hass: HomeAssistant, entry: ConfigEntry) -> CALLBACK_TYPE:
    """Schedule the reminders; returns the unsub, called on unload (see __init__.py)."""

    @callback
    def _fire(_now) -> None:
        # @callback, like the Calendar engine's tick - see modules/calendar/reminders.py.
        hass.async_create_task(async_send_chore_reminders(hass, entry))

    return async_track_time_change(hass, _fire, hour=list(REMINDER_HOURS), minute=0, second=0)
