"""Keeps the generated dashboard's Kiosk bucket in sync with HA's own user registry.

`dashboard/registry.py`'s `_build_viewer_buckets` computes the Kiosk bucket (every active,
non-system-generated HA user not already linked to a roster member) ONCE, at config-entry
setup/reload time - it has no way to notice a user account created/removed/changed afterward.
Live-verified gap (not assumed): creating a new HA user account after initial setup and
logging in as them showed a blank Family Dashboard page, because the stored dashboard config's
views never included that user's ID in any bucket's `visibility` list - reloading the entry
fixed it, confirming the computation itself was correct, just stale.

This module closes that gap by listening for HA's own real `user_added`/`user_updated`/
`user_removed` bus events (`homeassistant.auth.EVENT_USER_*`, fired by the auth manager itself
- not a custom mechanism) and triggering `hass.config_entries.async_reload` only when the
computed Kiosk-bucket user-ID set actually changes as a result. NOT on every event
unconditionally: `user_updated` also fires for changes irrelevant to bucket membership
(password, display name), and a reload tears down/recreates every entity this integration
owns, not just the dashboard - reloading on every irrelevant event would be needless flicker.
Debounced (`async_call_later`) so a burst of user changes (several accounts created
back-to-back) collapses into one reload instead of one per event.
"""
from __future__ import annotations

import logging
from typing import Callable

from homeassistant.auth import EVENT_USER_ADDED, EVENT_USER_REMOVED, EVENT_USER_UPDATED
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import CONF_ROSTER
from .dashboard.registry import async_compute_kiosk_user_ids

_LOGGER = logging.getLogger(__name__)
_DEBOUNCE_SECONDS = 3


async def async_register_user_change_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> Callable[[], None]:
    """Call once from `async_setup_entry`; call the returned unsub once from
    `async_unload_entry`. The initial snapshot is computed synchronously here (not lazily on
    the first event) so the very first real user-registry change is compared against the
    ACTUAL current bucket state, not against an empty placeholder - otherwise the first event
    of any kind, even an irrelevant one, would always look like a change and trigger a
    needless reload.
    """
    roster = entry.data.get(CONF_ROSTER, [])
    state: dict = {
        "snapshot": await async_compute_kiosk_user_ids(hass, roster),
        "cancel_debounce": None,
    }

    async def _recheck(_now=None) -> None:
        state["cancel_debounce"] = None
        current = await async_compute_kiosk_user_ids(hass, entry.data.get(CONF_ROSTER, []))
        if current != state["snapshot"]:
            _LOGGER.info(
                "Family Dashboard: HA user registry change affects the Kiosk dashboard "
                "bucket (was %s, now %s) - reloading entry to regenerate it",
                set(state["snapshot"]),
                set(current),
            )
            state["snapshot"] = current
            await hass.config_entries.async_reload(entry.entry_id)

    @callback
    def _on_user_event(_event: Event) -> None:
        if state["cancel_debounce"] is not None:
            state["cancel_debounce"]()
        state["cancel_debounce"] = async_call_later(hass, _DEBOUNCE_SECONDS, _recheck)

    unsub_added = hass.bus.async_listen(EVENT_USER_ADDED, _on_user_event)
    unsub_updated = hass.bus.async_listen(EVENT_USER_UPDATED, _on_user_event)
    unsub_removed = hass.bus.async_listen(EVENT_USER_REMOVED, _on_user_event)

    @callback
    def _unsub_all() -> None:
        if state["cancel_debounce"] is not None:
            state["cancel_debounce"]()
        unsub_added()
        unsub_updated()
        unsub_removed()

    return _unsub_all
