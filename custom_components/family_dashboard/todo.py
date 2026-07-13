"""STUB platform file - see modules/lists/__init__.py for what this needs to become.

Adds zero entities so enabling the Lists module in the wizard today doesn't crash - it just
does nothing yet, logged clearly so it's obvious in the logs, not a silent no-op.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    _LOGGER.warning(
        "Family Dashboard: the Lists module is enabled but not yet implemented - no list "
        "entities were created. See modules/lists/__init__.py."
    )
