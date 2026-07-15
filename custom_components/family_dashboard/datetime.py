"""Platform shim - HA requires platform files at the integration's top level.

Real entity classes live in modules/calendar/datetime.py, grouped there for clarity/module
ownership. This file just re-exports the module's async_setup_entry.
"""
from .modules.calendar.datetime import async_setup_entry as async_setup_entry  # noqa: F401
