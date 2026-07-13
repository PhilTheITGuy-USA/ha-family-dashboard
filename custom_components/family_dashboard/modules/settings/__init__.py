"""Settings/Roster module - always-on core, not a toggleable module.

Provisions one color (`select`) and one name (`text`) entity per roster member, created
live in `async_setup_entry` - no YAML, no restart. Both use HA's `RestoreEntity` mixin so
edits made later via the dashboard (tap a name to edit it, tap a color to cycle it) persist
across restarts without ever touching the config entry or writing a file.

This module is the REFERENCE IMPLEMENTATION for "own entity platform, no YAML" - the exact
principle `ha-family-hub-setup` v1 violated by writing static YAML packages and hoping for a
restart (see the `feedback_ha_setup_wizard_needs_runtime_helpers` memory / the rebuild
plan's "Why this exists"). Calendar/Lists/Chores should follow this same shape once built
out: entities created directly in a module-owned platform file, `unique_id` derived from the
stable `member_id` (never the mutable display name - see `util.slugify_unique`'s
docstring), `RestoreEntity` for anything the user can change post-setup.
"""
