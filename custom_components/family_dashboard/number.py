"""Platform shim - HA requires platform files at the integration's top level.

Real entity classes live in modules/chores/number.py, grouped there for clarity/module
ownership. This file just re-exports the module's async_setup_entry. Plain 1:1 shim, not an
aggregator - only Chores needs the `number` domain today (see modules/__init__.py's docstring
for the shim vs aggregator distinction).
"""
from .modules.chores.number import async_setup_entry as async_setup_entry  # noqa: F401
