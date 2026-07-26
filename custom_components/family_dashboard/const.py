"""Constants and the per-member feature registry for Family Dashboard.

Decisions locked in `family-hub-v2-rebuild-plan.md` (revised 2026-07-12/13):
- Settings/Roster is ALWAYS-ON CORE, not a toggleable feature - it's the one thing every
  other module depends on. Its platforms (`SETTINGS_PLATFORMS`) are forwarded
  unconditionally by `__init__.py`, and it deliberately has no entry in `FEATURES` below.
- `FEATURES` lists only the genuinely optional pieces the wizard's per-member features step
  offers: Calendar, Lists, Chores & Rewards (Meals is a planned-later addition - it should
  slot into this same dict without touching the others). Each roster member picks their own
  subset of these (stored as that member's own `CONF_FEATURES` list in `config_flow.py`'s
  `confirm` step) - this is NOT a household-wide toggle, see the rebuild plan's "Wizard
  flow" section for why (list isolation between siblings was the deciding reason).
"""
from __future__ import annotations

DOMAIN = "family_dashboard"

CONF_ROSTER = "roster"
CONF_FEATURES = "features"
CONF_HA_USER_ID = "ha_user_id"

# Optional per-member birthdate (ISO date string, or None if not provided) - powers the
# computed `calendar.family_dashboard_birthdays` overlay (modules/calendar/birthdays.py)
# rather than depending on any external "Birthdays" integration (HA has no built-in one).
CONF_BIRTHDATE = "birthdate"

# Whole-member Disable (distinct from any single CONF_FEATURES toggle) - hides the member
# everywhere on the generated dashboard and stops their calendar reminders, but keeps every
# bit of their data intact and reversible. See roster.py's async_set_member_disabled/
# async_delete_member for the Disable-vs-permanently-Delete distinction.
CONF_DISABLED = "disabled"

ROSTER_MAX_MEMBERS = 8

# A 16-color UI design system palette (2026-07-18, replacing the earlier 16 basic CSS/web
# color keywords) - explicit user request after walking through setup and finding the CSS
# keyword palette's choices "just not good". Named/purposed per a design-system reference
# table (e.g. "Amber / Yellow" for pending statuses, "Emerald / Dark Green" for high-contrast
# success states) rather than raw CSS keywords - see ROSTER_COLOR_HEX below for the matching
# hex values. Order here is the display order of modules/settings/dashboard.py's swatch grid.
COLOR_OPTIONS = [
    "Slate / Dark",
    "White",
    "Light Gray",
    "Medium Gray",
    "Red",
    "Orange",
    "Amber / Yellow",
    "Green",
    "Emerald / Dark Green",
    "Cyan / Teal",
    "Light Blue / Sky",
    "Blue",
    "Indigo",
    "Purple",
    "Pink",
    "Rose / Magenta",
]

# Always-on: forwarded for every config entry regardless of any member's selected features.
# "date" added for each roster member's Birthdate field (RosterBirthdateDate).
SETTINGS_PLATFORMS = ["select", "text", "switch", "sensor", "date"]

# Per-member avatar (2026-07-13 feature audit): a file path under /local/family_dashboard/
# avatars/ (frontend-servable alias for /config/www/family_dashboard/avatars/), chosen from a
# dashboard picture-grid picker built from sensor.family_dashboard_avatars' live file list -
# NOT a fixed enum in const.py, since the whole point is new avatar images can be dropped into
# that folder without touching code. Same always-present-key convention as color/name.
CONF_AVATAR = "avatar"

# Seeded into /config/www/family_dashboard/avatars/ on first entry setup if that folder is
# empty - generic starting icons (ported forward as concept from the legacy
# person-solid.png/people-group-solid.png set), not tied to any specific roster member.
DEFAULT_AVATAR_FILENAMES = ["person-solid.png", "people-group-solid.png"]

# Toggleable features offered per roster member in the wizard's `features` step. Each
# feature's "platforms" list is only forwarded via async_forward_entry_setups when at least
# one roster member has that feature key in their own `features` list.
#
# "implemented" is a SCAFFOLD-STAGE marker, not a permanent field: False means the
# top-level platform file(s) for that feature are currently stubs that add zero entities
# (see modules/<key>/ for what still needs building). Remove the key entirely once a
# feature is genuinely built out - don't leave stale "implemented: True" markers lying
# around as scope creeps.
FEATURES: dict[str, dict] = {
    "calendar": {
        # "select"/"text"/"switch"/"date"/"number" are all HOUSEHOLD-level scratch/display
        # entities (Birthdays/Holidays toggles, Add Event popup fields including its
        # weeks/days/hours/minutes-before reminder fields and its Date+Hour+Minute+AM-PM
        # Start/End fields - see event_time.py's docstring for why there's no "datetime"
        # platform here anymore) - forwarded once if ANY member has "calendar" enabled, same
        # mechanism as per-member platforms, just not per-member entities within them. See
        # modules/calendar/{select,text,switch,date,number}.py.
        "name": "Calendar",
        "platforms": ["calendar", "select", "text", "switch", "date", "number"],
        "default_selected": True,
        "implemented": True,
    },
    "lists": {
        "name": "Lists",
        "platforms": ["todo"],
        "default_selected": True,
        "implemented": True,
    },
    "chores": {
        "name": "Chores & Rewards",
        # "select"/"number" added for live Add/Modify/Delete of chores/rewards from the
        # Settings dashboard (points/cost, frequency, assigned-to fields) - see
        # modules/chores/select.py's and modules/chores/number.py's own module docstrings.
        "platforms": ["sensor", "button", "text", "binary_sensor", "select", "number"],
        "default_selected": True,
        "implemented": True,
    },
}

# Default pre-checked selection for every roster member's row in the `features` step -
# every member starts with all three features on, same least-surprise default the old
# household-wide step used, just applied per-row now instead of once.
DEFAULT_SELECTED_FEATURES = [key for key, feat in FEATURES.items() if feat["default_selected"]]

CONF_LIST_PRESETS = "list_presets"

# Preset To-do lists offered per roster member who opted into "lists" - from the legacy
# ha-family-hub-setup-plan.md preset table (still a good list). Unlike FEATURES, there is no
# default_selected here - the `lists` config-flow step defaults every row to an empty
# selection (see config_flow.py's build_lists_schema), since which specific lists a person
# wants is an affirmative choice, not an on-by-default capability.
LIST_PRESETS: dict[str, dict] = {
    "to_do": {"name": "To-Do", "icon": "mdi:check-circle-outline"},
    "shopping": {"name": "Shopping", "icon": "mdi:cart"},
    "packing": {"name": "Packing", "icon": "mdi:bag-suitcase"},
    "gift_ideas": {"name": "Gift Ideas", "icon": "mdi:gift"},
    "custom": {"name": "Custom", "icon": "mdi:clipboard-text"},
}

# Per-member calendar mapping (config_flow.py's `calendar` step): which existing calendar.*
# entity this member's own proxy CalendarEntity forwards to, and which notify.* entity (if
# any) the reminder engine should push to for their events. Both None if unmapped/skipped -
# same always-present-key convention as ha_user_id/list_presets.
CONF_CALENDAR_ENTITY_ID = "calendar_entity_id"
CONF_NOTIFY_ENTITY_ID = "notify_entity_id"


# Chores & Rewards - top-level entry.data lists (NOT per-roster-member fields, unlike
# everything above): a member can have many chores/rewards, each pointing back at them via
# "assigned_to" (a member_id). Gated on at least one roster member having "chores" in their
# own features list - Rewards has no separate feature toggle, it's part of the combined
# "Chores & Rewards" feature. See config_flow.py's async_step_add_chore/add_reward for how
# these lists get built (a repeat-until-done loop, not a single wizard field) and
# modules/chores/ for the entities built from them.
CONF_CHORES = "chores"
CONF_REWARDS = "rewards"

# Display label only in v1 - not enforced scheduling (no once-per-day/week claim-locking).
# A chore can be claimed and re-claimed any time; claiming always starts a fresh cycle
# regardless of prior status. See modules/chores/__init__.py for the reasoning.
CHORE_FREQUENCIES: dict[str, str] = {
    "daily": "Daily",
    "weekly": "Weekly",
    "one_time": "One-time",
}

# Hex values for each COLOR_OPTIONS name - needed anywhere a generated dashboard card wants
# an actual color (e.g. week-planner-card's per-calendar `color:`) rather than relying on the
# name string itself being a valid CSS value (several of these names, e.g. "Amber / Yellow",
# aren't).
ROSTER_COLOR_HEX: dict[str, str] = {
    "Slate / Dark": "#1E293B",
    "White": "#FFFFFF",
    "Light Gray": "#F1F5F9",
    "Medium Gray": "#94A3B8",
    "Red": "#EF4444",
    "Orange": "#F97316",
    "Amber / Yellow": "#F59E0B",
    "Green": "#10B981",
    "Emerald / Dark Green": "#047857",
    "Cyan / Teal": "#06B6D4",
    "Light Blue / Sky": "#38BDF8",
    "Blue": "#3B82F6",
    "Indigo": "#6366F1",
    "Purple": "#A855F7",
    "Pink": "#EC4899",
    "Rose / Magenta": "#F43F5E",
}


def roster_color_hex_js_map() -> str:
    """`ROSTER_COLOR_HEX` as a JS object-literal string, for any dashboard template (button-
    card `[[[ ]]]`, config-template-card `${ }`) that needs to look up a roster color's hex
    value from a LIVE entity state at render time (e.g. a `select.family_dashboard_<id>_color`
    state) rather than baking in whatever the color was at dashboard-generation time - matches
    the legacy `family-hub.yaml`'s own inline `var m={...}` toggle-pill color map, single
    source of truth here instead of copied into every template that needs it."""
    pairs = ", ".join(f"'{name}': '{hex_}'" for name, hex_ in ROSTER_COLOR_HEX.items())
    return "{" + pairs + "}"
