"""Storage-mode Lovelace dashboard registration.

CRITICAL CORRECTION (verified directly against live HA source, not assumed): an earlier
version of this module's docstring claimed `dashboards_collection.async_create_item()` was
reachable via `hass.data` - it isn't. `dashboards_collection` is a local variable inside
`homeassistant.components.lovelace.async_setup()`, never stored anywhere else. There is no
public Python API for another integration to reach the actual running collection instance;
the only built-in way to add a storage dashboard at runtime is the frontend's websocket API,
which isn't callable from backend Python code without simulating a websocket client.

What actually works, found by reading `lovelace/__init__.py`'s own `storage_dashboard_changed`
listener (the code that runs when a human adds a dashboard via the UI) and replicating
exactly what it does:
  1. A SEPARATE `DashboardsCollection(hass)` instance - it wraps the same underlying
     `Store(hass, DASHBOARDS_STORAGE_VERSION, DASHBOARDS_STORAGE_KEY)` the real one does, so
     writes land in the same file - used to persist the dashboard's metadata.
  2. A `LovelaceStorage(hass, item)` for that url_path, stored in
     `hass.data[LOVELACE_DATA].dashboards[url_path]` (so the frontend's own "get config"
     queries find it) and saved with the actual views/cards.
  3. The sidebar panel/frontend route, registered via `frontend.async_register_built_in_panel`
     with the same kwargs `lovelace`'s private `_register_panel` helper uses - inlined here
     rather than importing that private function, since there's no guarantee it stays stable
     across HA versions and it's simple enough to replicate safely.

Accepted, documented risk: a second `DashboardsCollection` instance writing to the same
`Store` as the real one could theoretically race if a human edits dashboards via the UI at
the exact moment this runs (only at config entry setup, not continuously) - vanishingly
unlikely in practice, not engineered around.

SECOND CORRECTION, found by the pinned pytest environment (HA 2025.1.4) failing where the
live 2026.7.2 container had passed: `hass.data[lovelace.LOVELACE_DATA]` (a typed dataclass
key) doesn't exist on that older version at all - it stores the same information as a plain
dict at `hass.data[lovelace.DOMAIN]["dashboards"]` instead (confirmed by reading that
version's `lovelace/__init__.py` directly). Both shapes expose the same underlying
`{url_path: LovelaceConfig}` dict lovelace's own code reads from - `_dashboards_dict` below
picks whichever one the running HA version actually has, so this module works unmodified on
both the pinned test version and current HA, rather than silently only being validated
against whichever one I happened to check first.

THIRD CORRECTION, same lesson as the second: `frontend.async_register_built_in_panel`'s
`show_in_sidebar` keyword (live 2026.7.2) doesn't exist on the pinned 2025.1.4 version's
signature at all - that version has no sidebar-visibility parameter for this call. Panel
registration below inspects the real signature at call time and only passes the parameter
name that version actually has (`show_in_sidebar` or the older `sidebar_default_visible`),
omitting it entirely if neither exists rather than guessing.
"""
from __future__ import annotations

import inspect

from homeassistant.components import frontend, lovelace
from homeassistant.components.lovelace import dashboard as lovelace_dashboard
from homeassistant.components.lovelace import resources as lovelace_resources
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

DASHBOARD_URL_PATH = "family-dashboard"
DASHBOARD_TITLE = "Family Dashboard"
DASHBOARD_ICON = "mdi:home-heart"

STRATEGY_RESOURCE_URL = "/local/family_dashboard/family-dashboard-strategy.js"


def _resources_collection(hass: HomeAssistant) -> lovelace_resources.ResourceStorageCollection:
    """The REAL, live `ResourceStorageCollection` lovelace's own `async_setup()` created and
    is actively serving over websocket to the frontend - unlike `DashboardsCollection` (see
    this module's own docstring), this ONE is reachable via `hass.data`, because
    `LovelaceData` (the typed dataclass `hass.data[LOVELACE_DATA]` holds on current HA) has a
    `resources` field pointing straight at it. Live-verified this matters, not just a style
    preference: an earlier version of `async_register_strategy_resource` created its own
    SECOND `ResourceStorageCollection` instance (mirroring `_dashboards_dict`'s dashboard
    pattern, which explicitly has no live-reachable equivalent) - that second instance wrote
    the new resource entry to the same underlying storage FILE correctly, but the REAL,
    running collection the frontend actually queries over websocket never learned about it,
    so the browser never even requested the script and `customElements.define(...)` never
    ran - confirmed via `hass.callWS({type: 'lovelace/resources'})` still showing only the
    original HACS-installed entries, and a real `Error: Timeout waiting for strategy element
    ll-strategy-dashboard-family-dashboard to be registered` in the browser console. Fixed by
    reaching the actual live object instead of creating a competing one - same dual-shape
    check as `_dashboards_dict` for the same reason (older HA versions store this as a plain
    dict, not the `LovelaceData` dataclass).
    """
    lovelace_data_key = getattr(lovelace, "LOVELACE_DATA", None)
    if lovelace_data_key is not None and lovelace_data_key in hass.data:
        data = hass.data[lovelace_data_key]
        if hasattr(data, "resources"):
            return data.resources
    return hass.data[lovelace.DOMAIN]["resources"]


def _dashboards_dict(hass: HomeAssistant) -> dict:
    """The mutable {url_path: LovelaceConfig} dict lovelace itself maintains - see the
    module docstring's second correction for why this needs to check both storage shapes.
    """
    lovelace_data_key = getattr(lovelace, "LOVELACE_DATA", None)
    if lovelace_data_key is not None and lovelace_data_key in hass.data:
        return hass.data[lovelace_data_key].dashboards
    return hass.data[lovelace.DOMAIN]["dashboards"]


async def async_register_dashboard(
    hass: HomeAssistant, entry: ConfigEntry, config: dict
) -> bool:
    """Idempotent: creates the storage-mode dashboard if it doesn't exist yet, otherwise
    just updates its saved config in place. Safe to call on every entry setup (including
    every HA restart and entry reload)."""
    dashboards = _dashboards_dict(hass)
    existing = dashboards.get(DASHBOARD_URL_PATH)
    if existing is not None:
        await existing.async_save(config)
        return True

    collection = lovelace_dashboard.DashboardsCollection(hass)
    await collection.async_load()
    item = await collection.async_create_item(
        {
            "url_path": DASHBOARD_URL_PATH,
            "title": DASHBOARD_TITLE,
            "icon": DASHBOARD_ICON,
            "show_in_sidebar": True,
            "require_admin": False,
        }
    )

    storage = lovelace_dashboard.LovelaceStorage(hass, item)
    dashboards[DASHBOARD_URL_PATH] = storage
    await storage.async_save(config)

    panel_kwargs = {
        "frontend_url_path": DASHBOARD_URL_PATH,
        "require_admin": False,
        "sidebar_title": DASHBOARD_TITLE,
        "sidebar_icon": DASHBOARD_ICON,
        "config": {"mode": lovelace.MODE_STORAGE},
        "update": False,
    }
    panel_params = inspect.signature(frontend.async_register_built_in_panel).parameters
    if "show_in_sidebar" in panel_params:
        panel_kwargs["show_in_sidebar"] = True
    elif "sidebar_default_visible" in panel_params:
        panel_kwargs["sidebar_default_visible"] = True

    frontend.async_register_built_in_panel(hass, "lovelace", **panel_kwargs)
    return True


async def async_register_strategy_resource(hass: HomeAssistant) -> bool:
    """Registers `family-dashboard-strategy.js` (seeded to `/config/www/family_dashboard/` by
    `assets.py`, same "ship it with the integration, copy on first run" pattern as the theme/
    background/avatars) as a Lovelace resource, so the frontend actually loads it and
    `customElements.define('ll-strategy-dashboard-family-dashboard', ...)` runs before the
    dashboard's own `"strategy"` config tries to resolve that tag.

    Uses `_resources_collection` (the REAL, live collection - see its own docstring for why a
    second instance doesn't work here, unlike `async_register_dashboard`'s dashboard
    registration above).
    """
    collection = _resources_collection(hass)
    # `async_items()` is a sync accessor (HA's "async_" prefix convention doesn't always mean
    # coroutine) over whatever's already loaded into `collection.data`. The real collection is
    # already loaded by the time any config entry sets up (lovelace's own `async_setup()`
    # loads it before the frontend can query it over websocket), but `async_get_info()` -
    # `ResourceStorageCollection`'s own public method that calls its private
    # `_async_ensure_loaded()` internally - is called here anyway as a cheap, harmless
    # guarantee rather than assuming that ordering always holds.
    await collection.async_get_info()
    existing = [item for item in collection.async_items() if item["url"] == STRATEGY_RESOURCE_URL]
    if existing:
        return True

    await collection.async_create_item({"res_type": "module", "url": STRATEGY_RESOURCE_URL})
    return True
