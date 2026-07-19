"""Dashboard-template contribution for the Calendar module.

Two distinct calendar-grid card builders, one per bucket kind (see `dashboard/registry.py`'s
module docstring for what a "bucket" is):

- `async_kiosk_calendar_card`: the Kiosk bucket's overlaid, interactively-filterable grid -
  every calendar-mapped member at once, with toggle-filter pills
  (`switch.family_dashboard_<id>_shown`) controlling which are shown. Ported from the proven
  legacy mechanism in `REPO/ha-family-hub/dashboards/family-hub.yaml`: `week-planner-card`
  already supports a per-calendar `filter:` regex (`.*` matches every event = shown, `^$`
  matches none = hidden) - the `calendars:` array stays a fixed, static list; only each
  entry's `filter` string is templated per member via `custom:config-template-card`.
- `async_calendar_view_card`: content for a personal bucket - that member's own calendar plus
  the Family/Birthdays/Holidays overlays (see below); no per-member toggle (nothing to filter,
  only one or two personal calendars ever shown here), but the overlays ARE toggleable here
  too (see below - a live-reported requirement, not fixed/always-shown).

Plus (2026-07-13 feature audit additions, all ported from the same legacy dashboard file, and
the 2026-07-18 Family calendar redesign):
- Family (any `calendar.*` entity whose OWN name matches "Family" case-insensitively -
  `_family_calendar_entity` - a household-shared Google/CalDAV/etc. calendar, e.g. a Google
  Calendar literally named "Family" shared to everyone. NOT tied to any roster member's own
  calendar mapping - replaces the earlier design where one member's personal calendar slot
  had to double as the shared one, which made it impossible to have a genuinely separate
  shared calendar without sacrificing that member's own personal view)/Birthdays
  (`calendar.family_dashboard_birthdays`, OUR OWN computed entity - see
  `modules/calendar/birthdays.py`, since HA has no built-in "Birthdays" integration)/Holidays
  (any HA "Holiday" integration entries, auto-provisioned for US + Philippines by
  `holidays_setup.py` and detected generically via `_holiday_calendar_entities` - not one
  hardcoded country) overlay layers - added to BOTH bucket kinds, toggle-filter pills for them
  on BOTH bucket kinds too (`switch.family_dashboard_family_calendar_shown`/
  `..._birthdays_shown`/`..._holidays_shown`, same mechanism as member toggles; one combined
  Holidays toggle covers every detected country, not one per country; Family defaults on).
- The view-granularity selector (`select.family_dashboard_calendar_view`) - a nav pill that
  cycles it via `select.select_next`, and its value is templated into BOTH the Kiosk card's
  and a personal bucket's own card's `days`/`startingDay` fields (exact `Today/Tomorrow/Week/
  Biweek/Month` -> day-count/anchor mapping ported from the legacy dashboard's own JS). It's a
  single config-entry-scoped entity, not per-viewer - a linked member changing it moves the
  Kiosk bucket's own view too, and vice versa.
- The Add Event popup (`async_add_event_popup_card`/`async_add_event_button`) - a
  `custom:bubble-card` pop-up with the scratch fields from `text.py`/`switch.py`/
  `datetime.py`/`date.py`, submitting via the `family_dashboard.add_event` service
  (see `events.py`).

card_mod styling adapted from the legacy file's proven week-planner-card block, with the
'Ovo' theme font reference dropped from THIS specific block (the theme now provides it
globally instead - see `themes/family_dashboard.yaml`/`assets.py`).
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ...const import (
    CONF_CALENDAR_ENTITY_ID,
    CONF_FEATURES,
    ROSTER_COLOR_HEX,
    roster_color_hex_js_map,
)

# Neutral fallback matching the "unknown state" gray already used in this module's own JS
# templates (e.g. `roster_color_hex_js_map()` lookups' `|| '#8a8a8a'`) - a roster member's
# stored `color` can be stale (e.g. from a palette that has since changed) and must not crash
# dashboard/entry setup, same defensive posture as the JS-side lookups.
_FALLBACK_COLOR_HEX = "#8a8a8a"


def _member_color_hex(member: dict) -> str:
    return ROSTER_COLOR_HEX.get(member["color"], _FALLBACK_COLOR_HEX)


def _member_has_calendar(member: dict) -> bool:
    """A member's calendar proxy only exists once BOTH a source entity is mapped AND the
    Calendar feature is currently selected - a dashboard toggle can turn the feature off
    while intentionally leaving the mapping intact (so re-enabling restores it without
    re-picking a calendar), so both conditions must be checked, not just the mapping."""
    return bool(member.get(CONF_CALENDAR_ENTITY_ID)) and "calendar" in member.get(
        CONF_FEATURES, []
    )

_CARD_MOD_STYLE = (
    "ha-card { background: rgba(255,255,255,0.85) !important; border-radius: 24px "
    "!important; box-shadow: none !important; height: clamp(420px,64vh,860px) !important; "
    "max-height: clamp(420px,64vh,860px) !important; color: #2b2b2b !important; } "
    ".navigation, .navigation * { color: #2b2b2b !important; font-weight: 600 !important; } "
    ".day.header .date .text { font-weight: 600 !important; color: #2b2b2b !important; } "
    ".day .date .text { font-size: 0.8em !important; font-weight: bold !important; "
    "color: #2b2b2b !important; } "
    ".day .date .number { font-weight: bold !important; font-size: 1.6em !important; "
    "color: #2b2b2b !important; } "
    ".today .number { border-radius: 6px !important; background-color: #ff9800 !important; "
    "color: white !important; padding: 0 5px !important; } "
    ".event { color: #222 !important; background-color: var(--border-color) !important; "
    "border-radius: 8px !important; font-size: 0.9em !important; padding: 2px 5px !important; } "
    ".event.past { opacity: .35 !important; } "
    ".time { color: #444 !important; font-size: 0.78em !important; } "
    ".none { background-color: transparent !important; color: #9aa0a6 !important; "
    "box-shadow: none !important; border: none !important; }"
)

_WEEK_PLANNER_STATIC_OPTIONS = {
    "showNavigation": True,
    "showLocation": True,
    "combineSimilarEvents": True,
    "hidePastEvents": False,
    "compact": False,
}

# Our OWN computed entity (modules/calendar/birthdays.py) - not an external "Birthdays"
# integration (HA has no built-in one, confirmed against the installed source).
BIRTHDAYS_ENTITY_ID = "calendar.family_dashboard_birthdays"

# HA's built-in "Holiday" integration (`homeassistant.components.holiday`) - auto-provisioned
# for US + Philippines by `holidays_setup.py`, but detected generically here (any Holiday
# config entry's own calendar entity, not one hardcoded country) so a user-added additional
# country shows up too, with no code change needed.
_HOLIDAY_INTEGRATION_DOMAIN = "holiday"

_VIEW_SELECT_ENTITY_ID = "select.family_dashboard_calendar_view"
_BIRTHDAYS_SHOWN_ENTITY_ID = "switch.family_dashboard_birthdays_shown"
_HOLIDAYS_SHOWN_ENTITY_ID = "switch.family_dashboard_holidays_shown"
_FAMILY_CALENDAR_SHOWN_ENTITY_ID = "switch.family_dashboard_family_calendar_shown"

# Name family members use for their household's shared calendar (e.g. a Google Calendar
# literally named "Family", shared to everyone). Matched case-insensitively against every
# calendar.* entity's own name - not tied to any roster member's own mapping (see this
# module's docstring's "Family calendar" bullet - replaces the earlier
# CONF_FAMILY_CALENDAR_MEMBER_ID member-flagging design, which forced giving up a member's
# own personal calendar slot to host it).
_FAMILY_CALENDAR_NAME = "family"

# Ported verbatim from the legacy dashboard's own view-selector JS (see
# family-hub.yaml's STARTDAY/DAYS variables) - Today/Tomorrow get week-planner-card's special
# 'today'/'tomorrow' anchor keywords instead of a weekday name, everything else anchors on
# Sunday with a day-count matching the label.

# NOTE on brace-counting: config-template-card wants SINGLE braces (`${ ... }`), unlike
# Jinja's double braces - an earlier version of these two constants accidentally emitted an
# extra trailing `}` (mixing an f-string first line with plain-string continuation lines,
# losing track of how many literal `}` each contributed), producing invalid JS that broke
# EVERY card on the Calendar tab silently. Live-verified via a real browser console
# `pageerror: Unexpected token '}'`, not assumed - config-template-card's parser doesn't
# fail gracefully on a stray brace, it just closes the whole custom element with no visible
# card at all, which is why this needed an actual console check to catch, not just a
# config-shape read.
_DAYS_JS = (
    f"${{ (function(){{ var v = states['{_VIEW_SELECT_ENTITY_ID}']?.state; "
    "if (v === 'Today') return 1; if (v === 'Tomorrow') return 2; if (v === 'Week') return 7; "
    "if (v === 'Biweek') return 14; return 35; })() }"
)
_STARTING_DAY_JS = (
    f"${{ (function(){{ var v = states['{_VIEW_SELECT_ENTITY_ID}']?.state; "
    "if (v === 'Today') return 'today'; if (v === 'Tomorrow') return 'tomorrow'; "
    "return 'sunday'; })() }"
)


def _shown_switch_entity_id(member_id: str) -> str:
    return f"switch.family_dashboard_{member_id}_shown"


def _avatar_select_entity_id(member_id: str) -> str:
    return f"select.family_dashboard_{member_id}_avatar"


def _color_select_entity_id(member_id: str) -> str:
    return f"select.family_dashboard_{member_id}_color"


def _family_calendar_entity(hass: HomeAssistant) -> tuple[str, str] | None:
    """(entity_id, display_name) of the household's shared calendar - any `calendar.*` entity
    whose own name matches `_FAMILY_CALENDAR_NAME` case-insensitively (e.g. a Google Calendar
    literally named "Family"), or `None` if no such entity currently exists. Auto-detected
    fresh on every call rather than a stored id, same "compute live, existence-gated" pattern
    `_holiday_calendar_entities` already uses - so renaming/removing/re-adding the calendar on
    the provider side just works without a reconfigure. If more than one entity matches, the
    first one found wins (no disambiguation UI - a genuine edge case, not worth a picker for)."""
    for state in hass.states.async_all("calendar"):
        if state.name.strip().lower() == _FAMILY_CALENDAR_NAME:
            return state.entity_id, state.name
    return None


def _holiday_calendar_entities(hass: HomeAssistant) -> list[tuple[str, str]]:
    """(entity_id, display_name) for every calendar entity belonging to ANY HA "Holiday"
    integration config entry - so a US AND a Philippines entry (or any others the user adds
    later) all show up automatically, rather than one hardcoded country's entity_id. Same
    "iterate config entries for a domain, then registry entries for that config entry"
    combination `reminders.py` already uses for `mobile_app` devices."""
    registry = er.async_get(hass)
    pairs: list[tuple[str, str]] = []
    for config_entry in hass.config_entries.async_entries(_HOLIDAY_INTEGRATION_DOMAIN):
        for entity in er.async_entries_for_config_entry(registry, config_entry.entry_id):
            if entity.domain != "calendar":
                continue
            state = hass.states.get(entity.entity_id)
            name = (
                (state.attributes.get("friendly_name") if state else None)
                or entity.name
                or config_entry.title
            )
            pairs.append((entity.entity_id, name))
    return pairs


def _overlay_entries(hass: HomeAssistant, toggled: bool) -> list[dict]:
    """Birthdays/Holidays calendar entries, only for ones that actually exist on this HA
    instance - Birthdays is our own always-created entity (see `modules/calendar/
    birthdays.py`), Holidays is however many Holiday integration entries currently exist, all
    sharing ONE combined toggle switch (not one per country).

    IMPORTANT - `filter` is an EXCLUSION regex, not an inclusion one: live-verified directly
    against the installed `week-planner-card.js` source (`_isFilterEvent`/its one call site in
    `_updateEvents`), an event whose summary MATCHES `calendars[i].filter` is SKIPPED (hidden),
    not shown. So "shown" (switch on) must use `'^$'` (matches nothing real -> nothing
    excluded -> everything shown), and "hidden" (switch off) must use `'.*'` (matches
    everything -> everything excluded) - the OPPOSITE of the naive "`.*`=show-all,
    `^$`=hide-all" reading an earlier version of this code (and every other toggle-filtered
    calendar in this module) assumed. A live user report ("Birthdays only shows when the pill
    is gray/off") caught this - pytest alone couldn't, since it only ever asserted the
    generated STRING content, never how the third-party card actually interprets it."""
    entries = []
    family_calendar = _family_calendar_entity(hass)
    if family_calendar is not None:
        entity_id, name = family_calendar
        entry = {"entity": entity_id, "name": name, "color": "#6366F1"}
        if toggled:
            entry["filter"] = (
                f"${{ states['{_FAMILY_CALENDAR_SHOWN_ENTITY_ID}']?.state === 'on' "
                "? '^$' : '.*' }"
            )
        entries.append(entry)

    if hass.states.get(BIRTHDAYS_ENTITY_ID) is not None:
        entry = {"entity": BIRTHDAYS_ENTITY_ID, "name": "Birthdays", "color": "#33a02c"}
        if toggled:
            entry["filter"] = (
                f"${{ states['{_BIRTHDAYS_SHOWN_ENTITY_ID}']?.state === 'on' ? '^$' : '.*' }}"
            )
        entries.append(entry)

    holiday_filter = (
        f"${{ states['{_HOLIDAYS_SHOWN_ENTITY_ID}']?.state === 'on' ? '^$' : '.*' }}"
        if toggled
        else None
    )
    for entity_id, name in _holiday_calendar_entities(hass):
        entry = {"entity": entity_id, "name": name, "color": "#ff7f00"}
        if holiday_filter:
            entry["filter"] = holiday_filter
        entries.append(entry)
    return entries


def async_kiosk_calendar_card(hass: HomeAssistant, members: list[dict]) -> dict | None:
    """The Kiosk bucket's calendar card - every given member's calendar always listed, each
    one's visibility toggled by its own `switch.family_dashboard_<id>_shown` state, plus
    Birthdays/Holidays (toggled the same way, if they exist). `days`/`startingDay` are
    templated from the view-granularity selector. Returns None if none of the given members
    have a mapped calendar AND neither overlay exists - the caller omits the card entirely
    rather than showing an empty grid.
    """
    calendar_members = [m for m in members if _member_has_calendar(m)]
    overlays = _overlay_entries(hass, toggled=True)
    if not calendar_members and not overlays:
        return None

    color_map = roster_color_hex_js_map()
    calendars = [
        {
            "entity": f"calendar.family_dashboard_{member['member_id']}_calendar",
            "name": member["name"],
            # Live-templated (not the Python-computed hex baked in at generation time) so a
            # roster color change - via the Settings tab's color select - reflects on this
            # member's events immediately, matching their toggle pill, without needing a
            # dashboard regenerate/reload. Falls back to the color known at generation time
            # if the live lookup ever comes back empty.
            "color": (
                "${ (" + color_map + ")[states['" + _color_select_entity_id(member["member_id"])
                + "']?.state] || '" + _member_color_hex(member) + "' }"
            ),
            # Exclusion regex, not inclusion - see `_overlay_entries`'s docstring for the
            # live-verified `week-planner-card` semantics this depends on.
            "filter": (
                f"${{ states['{_shown_switch_entity_id(member['member_id'])}']?.state === "
                "'on' ? '^$' : '.*' }"
            ),
        }
        for member in calendar_members
    ] + overlays

    toggle_entities = [_shown_switch_entity_id(m["member_id"]) for m in calendar_members]
    toggle_entities += [_color_select_entity_id(m["member_id"]) for m in calendar_members]
    if _family_calendar_entity(hass) is not None:
        toggle_entities.append(_FAMILY_CALENDAR_SHOWN_ENTITY_ID)
    if hass.states.get(BIRTHDAYS_ENTITY_ID) is not None:
        toggle_entities.append(_BIRTHDAYS_SHOWN_ENTITY_ID)
    if _holiday_calendar_entities(hass):
        toggle_entities.append(_HOLIDAYS_SHOWN_ENTITY_ID)

    return {
        "type": "custom:config-template-card",
        "entities": [*toggle_entities, _VIEW_SELECT_ENTITY_ID],
        "card": {
            "type": "custom:week-planner-card",
            "calendars": calendars,
            "days": _DAYS_JS,
            "startingDay": _STARTING_DAY_JS,
            **_WEEK_PLANNER_STATIC_OPTIONS,
            "card_mod": {"style": _CARD_MOD_STYLE},
        },
    }


async def async_calendar_view_card(
    hass: HomeAssistant, entry: ConfigEntry, members: list[dict]
) -> dict | None:
    """One week-planner-card listing every given member's mapped calendar proxy entity,
    color-coded to their roster color, plus Family/Birthdays/Holidays - used for a personal
    bucket's Calendar tab. Returns None if there's nothing at all to show.

    Family/Birthdays/Holidays ARE toggleable here too (`toggled=True`, a live-reported
    requirement - "always visible... though their view should be a toggle like any Roster
    user"), via the
    SAME shared switches the Kiosk bucket's card uses (`dashboard/registry.py`'s
    `_personal_calendar_cards` wires in the matching toggle pills) - unlike per-member
    calendars, which still have no per-member toggle in a personal bucket (nothing to filter,
    there's only ever one or two calendars shown here).

    `days`/`startingDay` are templated from the SAME `select.family_dashboard_calendar_view`
    entity the Kiosk bucket's card uses (see `_DAYS_JS`/`_STARTING_DAY_JS`) - it's a single,
    config-entry-scoped selector (not per-viewer), so a personal-bucket viewer changing it
    also moves the Kiosk bucket's own view, and vice versa. A live-reported gap: a linked
    member's Calendar tab had a working calendar but no View: Month/Week/.../Today button at
    all - `async_view_selector_pill()` (wired in by `dashboard/registry.py`'s
    `_personal_calendar_cards`) is the button; this card needs the matching templated
    `days`/`startingDay` (previously hardcoded to a fixed 14/sunday) for that button to
    actually do anything once tapped there.
    """
    calendars = [
        {
            "entity": f"calendar.family_dashboard_{member['member_id']}_calendar",
            "name": member["name"],
            "color": _member_color_hex(member),
        }
        for member in members
        if _member_has_calendar(member)
    ] + _overlay_entries(hass, toggled=True)
    if not calendars:
        return None

    toggle_entities = []
    if _family_calendar_entity(hass) is not None:
        toggle_entities.append(_FAMILY_CALENDAR_SHOWN_ENTITY_ID)
    if hass.states.get(BIRTHDAYS_ENTITY_ID) is not None:
        toggle_entities.append(_BIRTHDAYS_SHOWN_ENTITY_ID)
    if _holiday_calendar_entities(hass):
        toggle_entities.append(_HOLIDAYS_SHOWN_ENTITY_ID)

    return {
        "type": "custom:config-template-card",
        "entities": [*toggle_entities, _VIEW_SELECT_ENTITY_ID],
        "card": {
            "type": "custom:week-planner-card",
            "calendars": calendars,
            "days": _DAYS_JS,
            "startingDay": _STARTING_DAY_JS,
            **_WEEK_PLANNER_STATIC_OPTIONS,
            "card_mod": {"style": _CARD_MOD_STYLE},
        },
    }


def _nav_style_button(name: str, icon: str, tap_action: dict) -> dict:
    return {
        "type": "custom:button-card",
        "name": name,
        "icon": icon,
        "show_name": True,
        "show_icon": True,
        "tap_action": tap_action,
        "styles": {
            "card": [
                {"border-radius": "26px"},
                {"height": "52px"},
                {"padding": "4px 14px 4px 6px"},
                {"box-shadow": "none"},
                {"background-color": "#5a6270"},
            ],
            "grid": [
                {"grid-template-areas": "'i n'"},
                {"grid-template-columns": "42px auto"},
                {"align-items": "center"},
                {"justify-items": "start"},
            ],
            "icon": [{"width": "30px"}, {"color": "white"}],
            "name": [
                {"color": "white"},
                {"font-size": "13px"},
                {"font-weight": "600"},
                {"padding-left": "4px"},
                {"white-space": "nowrap"},
            ],
        },
    }


def async_view_selector_pill() -> dict:
    """Cycles select.family_dashboard_calendar_view via select_next - exact tap-to-cycle
    pattern as the legacy dashboard's own view-selector button."""
    return {
        "type": "custom:button-card",
        "icon": "mdi:calendar-expand-horizontal",
        "show_name": True,
        "show_icon": True,
        "name": f"[[[ return 'View: ' + states['{_VIEW_SELECT_ENTITY_ID}'].state ]]]",
        "tap_action": {
            "action": "perform-action",
            "perform_action": "select.select_next",
            "target": {"entity_id": _VIEW_SELECT_ENTITY_ID},
        },
        "styles": {
            "card": [
                {"border-radius": "26px"},
                {"height": "52px"},
                {"padding": "4px 14px 4px 6px"},
                {"box-shadow": "none"},
                {"background-color": "#5a6270"},
            ],
            "grid": [
                {"grid-template-areas": "'i n'"},
                {"grid-template-columns": "42px auto"},
                {"align-items": "center"},
                {"justify-items": "start"},
            ],
            "icon": [{"width": "30px"}, {"color": "white"}],
            "name": [
                {"color": "white"},
                {"font-size": "13px"},
                {"font-weight": "600"},
                {"padding-left": "4px"},
                {"white-space": "nowrap"},
            ],
        },
    }


def async_add_event_button() -> dict:
    """Opens the Add Event pop-up (see async_add_event_popup_card)."""
    return _nav_style_button(
        "Add Event", "mdi:calendar-plus", {"action": "navigate", "navigation_path": "#addevent"}
    )


def _toggle_pill_base_styles(shown_entity_id: str) -> dict:
    """The styling every toggle pill shares - fixed compact size (not flex-stretched to fill
    a wide `horizontal-stack` slot the way a stock `tile` card's own default sizing does,
    which was the real cause of a live-reported "Birthdays/Holidays are far wider than Ada/
    Grace" bug: two different card TYPES (`tile` vs `custom:button-card`) size themselves
    differently in the same row even with identical `horizontal-stack` parenting. Both
    `async_member_toggle_pills` and `async_birthdays_holidays_toggle_pills` build on this one
    shared base so they can never visually drift apart again - name/icon color both fade to
    gray when off, matching the legacy dashboard's own toggle-pill behavior.
    """
    return {
        "card": [
            {"border-radius": "26px"},
            {"height": "52px"},
            {"padding": "4px 14px 4px 6px"},
            {"box-shadow": "none"},
            {"position": "relative"},
        ],
        "grid": [
            {"grid-template-areas": "'i n'"},
            {"grid-template-columns": "42px auto"},
            {"align-items": "center"},
            {"justify-items": "start"},
        ],
        "name": [
            {
                "color": (
                    "[[[ return states['" + shown_entity_id + "'].state === 'on' "
                    "? 'white' : '#555' ]]]"
                )
            },
            {"font-size": "14px"},
            {"font-weight": "600"},
            {"padding-left": "4px"},
            {"justify-self": "start"},
            {"white-space": "nowrap"},
        ],
    }


def member_avatar_toggle_pill(member: dict, shown_entity_id: str) -> dict:
    """A single avatar+roster-color toggle pill for one member, keyed off whatever `shown`
    switch the caller supplies - factored out of `async_member_toggle_pills` so Chores' own
    per-kid toggle pills (`modules/chores/dashboard.py`'s `async_kiosk_chores_cards`) can reuse
    the exact same look instead of the plain generic-icon `tile` card they had before, which a
    live user report caught as visibly inconsistent with Calendar's pills ("old style button
    and not the new style"). Cross-module import here matches this codebase's established
    pattern for dashboard-contribution helpers (e.g. `modules/settings/dashboard.py` already
    imports Chores' PIN widgets the same way) - not duplicated, since keeping two copies of
    this much button-card styling in sync by hand is exactly how they drifted apart the first
    time.

    Ported from the legacy dashboard's own Personal/Lhen/Family toggle pills
    (`dashboards/family-hub.yaml` lines ~113-230). Shows the member's live avatar image and
    fills with their live roster color while shown, fading to flat gray (`#e6e6e6`) when
    hidden - matches `Calendar.png`'s mockup reference (colored pill + small circular avatar +
    name).

    button-card's `[[[ ]]]` mechanism, read directly from `config/www/community/button-card/
    button-card.js` (`_evalTemplate`/`_getTemplateOrValue`): the field's entire *trimmed*
    string is matched against `^(\\[{3,})(.*?)(\\]{3,})$` and, if it matches, the middle group
    is run through `new Function(...)` as a real function BODY (statements + explicit `return`
    both work, unlike config-template-card's blind substring+eval - see `_avatar_thumbnail` in
    `modules/settings/dashboard.py` for that mechanism's own writeup). Still requires the WHOLE
    field value to be exactly `[[[...]]]`, though - the same "don't mix literal text with a
    template marker in one field" mistake that broke `_avatar_thumbnail` would break this too.
    """
    avatar_entity_id = _avatar_select_entity_id(member["member_id"])
    color_entity_id = _color_select_entity_id(member["member_id"])
    fallback_hex = _member_color_hex(member)
    styles = _toggle_pill_base_styles(shown_entity_id)
    styles["card"].append(
        {
            "background-color": (
                "[[[ var m = " + roster_color_hex_js_map() + "; "
                "return states['" + shown_entity_id + "'].state === 'on' "
                "? (m[states['" + color_entity_id + "']?.state] || '"
                + fallback_hex + "') : '#e6e6e6'; ]]]"
            )
        }
    )
    styles["custom_fields"] = {
        "pic": [
            {"position": "absolute"},
            {"left": "9px"},
            {"top": "50%"},
            {"transform": "translateY(-50%)"},
            {"pointer-events": "none"},
        ]
    }
    return {
        "type": "custom:button-card",
        "show_name": True,
        "show_icon": False,
        "name": member["name"],
        "icon": "mdi:account",
        "tap_action": {
            "action": "perform-action",
            "perform_action": "switch.toggle",
            "target": {"entity_id": shown_entity_id},
        },
        "custom_fields": {
            "pic": (
                "[[[ return `<img src='${states['" + avatar_entity_id + "'].state}' "
                "onerror='this.remove()' style='width:38px;height:38px;"
                "border-radius:50%;object-fit:cover;display:block;'>` ]]]"
            )
        },
        "styles": styles,
    }


def async_member_toggle_pills(members: list[dict]) -> list[dict]:
    """Kiosk-only toggle-filter pills, one per calendar-mapped member - see
    `member_avatar_toggle_pill` for the pill itself."""
    return [
        member_avatar_toggle_pill(member, _shown_switch_entity_id(member["member_id"]))
        for member in members
        if _member_has_calendar(member)
    ]


def _fixed_toggle_pill(shown_entity_id: str, name: str, icon: str, color_hex: str) -> dict:
    """A toggle pill for a fixed (non-member) overlay like Birthdays/Holidays - same shared
    base styling as `async_member_toggle_pills`, a plain mdi icon instead of a live avatar
    image, and a fixed on-color instead of a live roster-color lookup."""
    styles = _toggle_pill_base_styles(shown_entity_id)
    styles["card"].append(
        {
            "background-color": (
                "[[[ return states['" + shown_entity_id + "'].state === 'on' "
                "? '" + color_hex + "' : '#e6e6e6' ]]]"
            )
        }
    )
    styles["icon"] = [
        {"width": "22px"},
        {
            "color": (
                "[[[ return states['" + shown_entity_id + "'].state === 'on' "
                "? 'white' : '#8a8a8a' ]]]"
            )
        },
    ]
    return {
        "type": "custom:button-card",
        "show_name": True,
        "show_icon": True,
        "name": name,
        "icon": icon,
        "tap_action": {
            "action": "perform-action",
            "perform_action": "switch.toggle",
            "target": {"entity_id": shown_entity_id},
        },
        "styles": styles,
    }


def async_birthdays_holidays_toggle_pills(hass: HomeAssistant) -> list[dict]:
    """Toggle-filter pills for Family/Birthdays/Holidays - used on BOTH the Kiosk bucket's and
    every personal bucket's Calendar tab (see `dashboard/registry.py`'s
    `_kiosk_calendar_cards`/`_personal_calendar_cards`), same shared pill styling as member
    toggles (`_toggle_pill_base_styles`/`_fixed_toggle_pill`) - empty list entries omitted for
    whichever overlay doesn't exist on this instance. One combined Holidays pill covers every
    detected Holiday integration entry (US, Philippines, or any others added later). Name kept
    as-is (not renamed to include "family") to avoid an unrelated diff across every caller -
    it's simply "the fixed-overlay toggle pills" now, Family included."""
    pills = []
    if _family_calendar_entity(hass) is not None:
        pills.append(
            _fixed_toggle_pill(
                _FAMILY_CALENDAR_SHOWN_ENTITY_ID, "Family", "mdi:home-heart", "#6366F1"
            )
        )
    if hass.states.get(BIRTHDAYS_ENTITY_ID) is not None:
        pills.append(
            _fixed_toggle_pill(_BIRTHDAYS_SHOWN_ENTITY_ID, "Birthdays", "mdi:cake-variant", "#33a02c")
        )
    if _holiday_calendar_entities(hass):
        pills.append(
            _fixed_toggle_pill(_HOLIDAYS_SHOWN_ENTITY_ID, "Holidays", "mdi:flag-variant", "#ff7f00")
        )
    return pills


def async_add_event_popup_card() -> dict:
    """The Add Event pop-up - ports `dashboards/family-hub.yaml` lines ~503-563's proven
    structure (plain entities card + all-day/timed conditional cards + submit button) onto
    this integration's own owned scratch entities instead of `input_*` helpers."""
    return {
        "type": "custom:bubble-card",
        "card_type": "pop-up",
        "hash": "#addevent",
        "name": "Add Calendar Event",
        "icon": "mdi:calendar-plus",
        "cards": [
            {
                "type": "entities",
                "title": "Add Calendar Event",
                "entities": [
                    {"entity": "select.family_dashboard_event_calendar", "name": "Calendar"},
                    {"entity": "text.family_dashboard_event_title", "name": "Title"},
                    {"entity": "text.family_dashboard_event_description", "name": "Description"},
                    {"entity": "switch.family_dashboard_event_all_day", "name": "All Day Event"},
                ],
                "show_header_toggle": False,
            },
            {
                "type": "conditional",
                "conditions": [{"entity": "switch.family_dashboard_event_all_day", "state": "off"}],
                "card": {
                    "type": "entities",
                    "entities": [
                        {"entity": "datetime.family_dashboard_event_start", "name": "Start"},
                        {"entity": "datetime.family_dashboard_event_end", "name": "End"},
                    ],
                },
            },
            {
                "type": "conditional",
                "conditions": [{"entity": "switch.family_dashboard_event_all_day", "state": "on"}],
                "card": {
                    "type": "entities",
                    "entities": [
                        {"entity": "date.family_dashboard_event_start_date", "name": "Start Date"},
                        {"entity": "date.family_dashboard_event_end_date", "name": "End Date"},
                    ],
                },
            },
            {
                "type": "entities",
                "title": "Remind me",
                "entities": [
                    {
                        "entity": "switch.family_dashboard_event_remind_1_week_before",
                        "name": "1 Week Before",
                    },
                    {
                        "entity": "switch.family_dashboard_event_remind_1_day_before",
                        "name": "1 Day Before",
                    },
                    {
                        "entity": "switch.family_dashboard_event_remind_1_hour_before",
                        "name": "1 Hour Before",
                    },
                ],
                "show_header_toggle": False,
            },
            {
                "type": "button",
                "name": "Add to Calendar",
                "icon": "mdi:calendar-check",
                "tap_action": {
                    "action": "perform-action",
                    "perform_action": "family_dashboard.add_event",
                    "target": {"entity_id": "select.family_dashboard_event_calendar"},
                },
            },
        ],
    }
