"""Opt-in per-event reminder engine, ported from `ha-family-hub`'s
`packages/family_hub_calendar.yaml` as this module's own background task (a scheduled
Python coroutine, not a YAML script+automation pair) - a 5-minute-tick poll that scans each
mapped member's calendar for `[[reminder:...]]`-tagged events and pushes a notification when
an event's lead time falls in the current tick window.

Extends the legacy single-total-minutes tag to support MULTIPLE independent reminders per
event, each specified in days/hours/minutes: e.g. a description containing both
`[[reminder:1d]]` and `[[reminder:30m]]` fires two separate notifications for that one event
(one day before, and again 30 minutes before). The legacy code technically already found
every tag match via regex but only ever used the first (`evt_tag_matches[0]`) - iterating
every match instead is what makes multiple reminders work.

Matches the legacy automation's exact firing semantics deliberately (this is a port, not an
upgrade): a 5-minute tick, a half-open `[tick_start, tick_end)` window, best-effort rather
than an exactly-once guarantee. All-day events have no meaningful lead-time countdown and are
skipped, same as the legacy code's `'T' in evt_start` check.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from homeassistant.components.calendar import CalendarEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from ...const import CONF_DISABLED, CONF_HA_USER_ID, CONF_NOTIFY_ENTITY_ID, CONF_ROSTER

_LOGGER = logging.getLogger(__name__)

_MOBILE_APP_DOMAIN = "mobile_app"


async def async_resolve_member_notify_targets(hass: HomeAssistant, member: dict) -> list[str]:
    """Who to notify for this member's reminders, in priority order:

    1. An explicit manual `notify_entity_id` mapping (set via the Settings dashboard's
       notify-mapping picker, or the wizard) always wins - an intentional override.
    2. Else, if this member is linked to an HA user (`ha_user_id`), auto-resolve LIVE from
       that user's registered mobile_app device(s) - not stored anywhere, so it stays correct
       automatically if they get a new phone (a new phone registration is just a new
       `mobile_app` config entry sharing the same `user_id`, found fresh on the next call).
       Confirmed directly against the installed HA source: each mobile_app config entry
       carries its own `user_id` in `entry.data`, and that device's notify entity's
       `unique_id` equals `entry.data["device_id"]`.
    3. Else, no target (matches the pre-existing "skip, nothing configured" behavior).

    Returns every matching entity_id (0, 1, or more devices) - callers pass the whole list as
    a single `notify.send_message` call's `entity_id` target.
    """
    manual = member.get(CONF_NOTIFY_ENTITY_ID)
    if manual:
        return [manual]

    ha_user_id = member.get(CONF_HA_USER_ID)
    if not ha_user_id:
        return []

    registry = er.async_get(hass)
    targets = []
    for mobile_entry in hass.config_entries.async_entries(_MOBILE_APP_DOMAIN):
        if mobile_entry.data.get("user_id") != ha_user_id:
            continue
        device_id = mobile_entry.data.get("device_id")
        entity_id = registry.async_get_entity_id("notify", _MOBILE_APP_DOMAIN, device_id)
        if entity_id is not None:
            targets.append(entity_id)
    return targets

_REMINDER_TAG = re.compile(r"\[\[reminder:(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?\]\]")
_LOOKAHEAD = timedelta(days=15)
_TICK_INTERVAL = timedelta(minutes=5)


def _lead_minutes(match: re.Match) -> int | None:
    """Total lead minutes for one `[[reminder:...]]` match, or None for a tag with no
    day/hour/minute component at all (e.g. a bare `[[reminder:]]`, which isn't a real
    reminder)."""
    days, hours, minutes = match.groups()
    if not (days or hours or minutes):
        return None
    return int(days or 0) * 1440 + int(hours or 0) * 60 + int(minutes or 0)


async def _async_check_reminders(
    hass: HomeAssistant, roster: list[dict], calendar_entities: dict[str, CalendarEntity]
) -> None:
    """Core reminder-scanning logic. Called both by the scheduled 5-minute tick and directly
    by tests (wrapped in freezegun's freeze_time to control "now" - no fake-clock/interval
    gymnastics needed to test this). Works with real CalendarEvent objects the whole way
    through (via the proxy entities' own async_get_events) - no entity_id strings or
    service-response dicts to parse.
    """
    now = dt_util.now()
    tick_start, tick_end = now.timestamp(), now.timestamp() + _TICK_INTERVAL.total_seconds()
    window_start, window_end = now, now + _LOOKAHEAD

    for member in roster:
        # Disabled (roster.py's async_set_member_disabled) means "keep everything, just
        # don't show it or action calendar reminders" - their calendar mapping/entity stays
        # completely intact, only the reminder engine's own per-tick processing skips them.
        if member.get(CONF_DISABLED):
            continue
        notify_ids = await async_resolve_member_notify_targets(hass, member)
        entity = calendar_entities.get(member["member_id"])
        if not notify_ids or entity is None:
            continue

        for event in await entity.async_get_events(hass, window_start, window_end):
            if event.all_day:
                continue
            for match in _REMINDER_TAG.finditer(event.description or ""):
                lead_minutes = _lead_minutes(match)
                if lead_minutes is None:
                    continue
                reminder_ts = event.start_datetime_local.timestamp() - lead_minutes * 60
                if not (tick_start <= reminder_ts < tick_end):
                    continue
                _LOGGER.debug(
                    "Family Dashboard: firing %s-minute reminder for '%s' (%s) to %s",
                    lead_minutes,
                    event.summary,
                    member["name"],
                    notify_ids,
                )
                await hass.services.async_call(
                    "notify",
                    "send_message",
                    {
                        "entity_id": notify_ids,
                        "title": f"Upcoming: {event.summary or member['name'] + ' event'}",
                        "message": (
                            f"Starting at {event.start_datetime_local:%-I:%M %p}"
                        ),
                    },
                )


def async_start_reminder_engine(
    hass: HomeAssistant, entry: ConfigEntry, calendar_entities: dict[str, CalendarEntity]
) -> CALLBACK_TYPE:
    """Register the 5-minute reminder poll for this config entry. Returns the unsub callback -
    callers must call it on unload (see __init__.py's async_unload_entry) so the timer
    doesn't leak across reload/unload.
    """
    roster = entry.data[CONF_ROSTER]

    async def _tick(_now) -> None:
        await _async_check_reminders(hass, roster, calendar_entities)

    @callback
    def _schedule_tick(now) -> None:
        # Live-verified: `async_track_time_interval`'s callback is not guaranteed to run on
        # the event loop thread unless the callback itself is `@callback`-marked - a plain
        # lambda calling `hass.async_create_task` directly raised a real
        # "calls hass.async_create_task from a thread other than the event loop" RuntimeError
        # once the 5-minute tick actually fired, not caught by pytest (which only ever calls
        # `_async_check_reminders` directly, never exercises the real scheduling path).
        hass.async_create_task(_tick(now))

    return async_track_time_interval(hass, _schedule_tick, _TICK_INTERVAL)
