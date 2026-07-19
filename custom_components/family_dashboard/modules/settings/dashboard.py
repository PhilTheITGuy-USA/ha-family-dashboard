"""Dashboard-template contribution for Settings/Roster - the one tab with a single shared,
unrestricted view (no bucketing, same content for every viewer - see
`dashboard/registry.py`'s module docstring). Family member cards using the already-built
`select`/`text` entities (`modules/settings/select.py`/`text.py`), each with an avatar
thumbnail that opens a picture-grid picker pop-up and a color swatch that opens the 16-color
picker pop-up (`_color_picker_popup`), plus the guided "Change Parent PIN" flow
(`modules/chores/dashboard.py`'s `async_change_pin_button`/`async_pin_change_popup_card`,
reused not duplicated) if any member has Chores enabled.

The avatar picker's grid IS built via `custom:config-template-card`'s `.map()` over the
avatars sensor's live `file_list` attribute, producing a genuinely dynamic-length `cards:`
array - this is a direct, proven port of `REPO/ha-family-hub/dashboards/family-hub.yaml`'s own
avatar-picker pop-ups (`#personal-avatar`/`#family-avatar`/`#lhen-avatar`), which use exactly
this mechanism in the shipped legacy product. An earlier version of this file concluded the
mechanism itself was unreliable after its own hand-written attempt rendered an empty grid -
that conclusion was WRONG, found only after actually reading the legacy dashboard's working
example (should have been the first step, not a last resort - see
`feedback_reread_planning_docs`/legacy-source-first practice). The real bug was a brace-
counting mistake in the generated JS (an f-string first line's `{{`/`}}` escaping got mixed
with plain-string continuation lines that used literal single/double braces, silently
producing one extra stray `}` - a real, live-verified `pageerror: Unexpected token '}'`, not a
config-template-card limitation). Built here with plain string concatenation instead of an
f-string specifically to avoid that whole class of mistake - every `{`/`}` below is a literal
character, not something relying on `{{`/`}}` doubling to reason about.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ...const import (
    COLOR_OPTIONS,
    CONF_CHORES,
    CONF_FEATURES,
    CONF_REWARDS,
    CONF_ROSTER,
    DOMAIN,
    FEATURES,
    ROSTER_COLOR_HEX,
    roster_color_hex_js_map,
)
from ..chores.dashboard import async_change_pin_button, async_pin_change_popup_card
from .sensor import AVATARS_SENSOR_ENTITY_ID
from .text import BIRTHDATE_SCRATCH_UNIQUE_ID

_NAV_BUTTON_STYLE = {
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
    "name": [{"color": "white"}, {"font-weight": "600"}, {"font-size": "13px"}],
}


def _avatar_select_entity_id(member_id: str) -> str:
    return f"select.family_dashboard_{member_id}_avatar"


def _color_select_entity_id(member_id: str) -> str:
    return f"select.family_dashboard_{member_id}_color"


_PLAIN_PILL_STYLE = {
    "card": [
        {"border-radius": "16px"},
        {"height": "44px"},
        {"padding": "4px 12px 4px 6px"},
        {"box-shadow": "none"},
        {"background-color": "white"},
    ],
    "grid": [
        {"grid-template-areas": "'i n'"},
        {"grid-template-columns": "30px auto"},
        {"align-items": "center"},
        {"justify-items": "start"},
    ],
    "icon": [{"width": "18px"}, {"color": "#8a8a8a"}],
    "name": [
        {"color": "#2b2b2b"},
        {"font-size": "13px"},
        {"font-weight": "600"},
        {"padding-left": "4px"},
        {"white-space": "nowrap"},
    ],
}


def _name_pill(name_entity_id: str) -> dict:
    """'Name: <value>' - matches `Better-Settings.png`'s compact per-field card layout.
    Tapping opens the text entity's own native more-info dialog to edit it (no custom edit UI
    needed, HA's stock text-entity dialog already provides one)."""
    return {
        "type": "custom:button-card",
        "entity": name_entity_id,
        "show_name": True,
        "show_icon": True,
        "icon": "mdi:pencil",
        "name": f"[[[ return 'Name: ' + states['{name_entity_id}'].state ]]]",
        "tap_action": {"action": "more-info"},
        "styles": _PLAIN_PILL_STYLE,
    }


def _birthdate_pill(member_id: str, birthdate_entity_id: str) -> dict:
    """'Birthdate: DD/MM/YYYY' - opens `_birthdate_edit_popup` instead of tapping straight
    into this entity's stock `date`-domain more-info dialog. That native dialog uses HA's
    built-in date picker widget, which is popup-only (no way to type a date directly) with no
    year-jump in its calendar grid (confirmed by reading `DateSelectorConfig`'s source - zero
    configurable options - and live-testing the popup itself), making it unusable for old
    birthdates - the exact same live-reported gap the wizard's own Birthdate step already
    worked around (see `util.ddmmyyyy_to_iso`'s docstring). Reformats the stored ISO state to
    DD/MM/YYYY for display (client-side JS, not baked in at generation time) to match what the
    edit popup expects you to type. Shows "Not set" when no birthdate has been chosen yet
    (optional field - not every member has to set one). `entity_id` can be `None` in
    dashboard-only tests that build config without a full entry setup - degrades gracefully
    rather than crashing, same defensive posture as `_feature_toggle_pill`'s own
    `entity_id or ""` guard (this pill uses `+` string concatenation, unlike `_name_pill`'s
    f-string, which does NOT crash on a `None` substitution - "+" does)."""
    birthdate_entity_id = birthdate_entity_id or ""
    return {
        "type": "custom:button-card",
        "entity": birthdate_entity_id,
        "show_name": True,
        "show_icon": True,
        "icon": "mdi:cake-variant",
        "name": (
            "[[[ var s = states['" + birthdate_entity_id + "'].state; "
            "if (s === 'unknown') return 'Birthdate: Not set'; "
            "var p = s.split('-'); "
            "return 'Birthdate: ' + p[2] + '/' + p[1] + '/' + p[0]; ]]]"
        ),
        "tap_action": {"action": "navigate", "navigation_path": f"#birthdate-{member_id}"},
        "styles": _PLAIN_PILL_STYLE,
    }


def _birthdate_edit_popup(member_id: str, birthdate_entity_id: str, scratch_entity_id: str) -> dict:
    """Typed DD/MM/YYYY birthdate editor - same "entities card with a scratch field, plus a
    commit button" shape as the Add Event popup (`modules/calendar/dashboard.py`'s
    `async_add_event_popup_card`), not a custom widget invented from scratch. The scratch
    field (`scratch_entity_id`, `text.py`'s `_BirthdateScratchText`) is HOUSEHOLD-scoped (one
    shared instance, not per-member) - fine because only one of these popups can ever be open
    at a time - and the Save button's `perform_action` targets THIS member's own birthdate
    entity specifically, so `modules/settings/date.py`'s `async_set_birthdate` service knows
    which member it's setting even though it reads the shared scratch value. `entity_id`s can
    be `None` in dashboard-only tests that build config without a full entry setup."""
    birthdate_entity_id = birthdate_entity_id or ""
    scratch_entity_id = scratch_entity_id or ""
    return {
        "type": "custom:bubble-card",
        "card_type": "pop-up",
        "hash": f"#birthdate-{member_id}",
        "name": "Edit Birthdate",
        "icon": "mdi:cake-variant",
        "cards": [
            {
                "type": "entities",
                "title": "Edit Birthdate",
                "entities": [
                    {"entity": scratch_entity_id, "name": "New Birthdate (DD/MM/YYYY)"},
                ],
                "show_header_toggle": False,
            },
            {
                "type": "button",
                "name": "Save",
                "icon": "mdi:content-save",
                "tap_action": {
                    "action": "perform-action",
                    "perform_action": "family_dashboard.set_birthdate",
                    "target": {"entity_id": birthdate_entity_id},
                },
            },
        ],
    }


def _contrast_text_color(hex_value: str) -> str:
    """Perceived-luminance based text color (near-black or white) for legible text over an
    arbitrary swatch background - computed from the hex value rather than hardcoded per color
    name, so the swatch grid stays legible if `ROSTER_COLOR_HEX` is ever edited."""
    r, g, b = (int(hex_value[i : i + 2], 16) for i in (1, 3, 5))
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#1a2235" if luminance > 150 else "#ffffff"


def _color_swatch_card(color_name: str, color_entity_id: str) -> dict:
    """One cell of the color-picker popup grid - a solid swatch of that color with its name
    label, bordered when it's the member's current selection. Static per-name styling (the
    16-color palette is fixed Python data, unlike the avatars sensor's dynamic file list) -
    only the selection border needs to read live entity state."""
    hex_value = ROSTER_COLOR_HEX[color_name]
    return {
        "type": "custom:button-card",
        "name": color_name,
        "show_name": True,
        "show_icon": False,
        "tap_action": {
            "action": "perform-action",
            "perform_action": "select.select_option",
            "target": {"entity_id": color_entity_id},
            "data": {"option": color_name},
        },
        "styles": {
            "card": [
                {"background-color": hex_value},
                {"border-radius": "14px"},
                {"box-shadow": "none"},
                {"height": "64px"},
                {
                    "border": (
                        "[[[ return states['" + color_entity_id + "'].state === '"
                        + color_name + "' ? '3px solid #1a2235' : '3px solid transparent' ]]]"
                    )
                },
            ],
            "name": [
                {"color": _contrast_text_color(hex_value)},
                {"font-size": "11px"},
                {"font-weight": "700"},
                # Several palette names are two words joined by "/" (e.g. "Emerald / Dark
                # Green") - too long for a fixed 4-wide swatch cell at the old 12px/nowrap
                # styling, which button-card silently ellipsis-truncated (only caught by
                # actually rendering this popup, not from the config JSON shape). Wrap
                # instead of truncate.
                {"white-space": "normal"},
                {"line-height": "1.2"},
                {"padding": "0 4px"},
            ],
        },
    }


def _color_picker_popup(member_id: str, color_entity_id: str) -> dict:
    """The standard color picker - a 4-wide grid of all 16 basic colors, each showing its
    swatch and name, replacing the old plain-text select dropdown (explicit user request)."""
    swatches = [_color_swatch_card(name, color_entity_id) for name in COLOR_OPTIONS]
    return {
        "type": "custom:bubble-card",
        "card_type": "pop-up",
        "hash": f"#color-{member_id}",
        "name": "Choose Color",
        "icon": "mdi:palette",
        "cards": [{"type": "grid", "columns": 4, "square": False, "cards": swatches}],
    }


def _color_pill(member_id: str, color_entity_id: str) -> dict:
    """'Color: <value>' filled with the member's own live roster color - tapping opens the
    swatch-grid color-picker pop-up (`_color_picker_popup`), same pattern as `_avatar_pill`."""
    return {
        "type": "custom:button-card",
        "entity": color_entity_id,
        "show_name": True,
        "show_icon": False,
        "name": f"[[[ return 'Color: ' + states['{color_entity_id}'].state ]]]",
        "tap_action": {"action": "navigate", "navigation_path": f"#color-{member_id}"},
        "styles": {
            "card": [
                {"border-radius": "16px"},
                {"height": "44px"},
                {"padding": "4px 12px"},
                {"box-shadow": "none"},
                {
                    "background-color": (
                        "[[[ var m = " + roster_color_hex_js_map() + "; "
                        "return m[states['" + color_entity_id + "'].state] || '#8a8a8a'; ]]]"
                    )
                },
            ],
            "name": [
                {"color": "white"},
                {"font-size": "13px"},
                {"font-weight": "600"},
                {"text-align": "center"},
            ],
        },
    }


def _avatar_pill(member_id: str, avatar_entity_id: str) -> dict:
    """'Avatar' with a small live preview image - tapping opens the avatar-picker pop-up
    (`_avatar_picker_popup`), same live-templated `<img>` pattern already proven in
    `modules/calendar/dashboard.py`'s `async_member_toggle_pills`."""
    return {
        "type": "custom:button-card",
        "show_name": True,
        "show_icon": False,
        "name": "Avatar",
        "tap_action": {"action": "navigate", "navigation_path": f"#avatar-{member_id}"},
        "custom_fields": {
            "pic": (
                "[[[ return `<img src='${states['" + avatar_entity_id + "'].state}' "
                "onerror='this.remove()' style='width:26px;height:26px;border-radius:50%;"
                "object-fit:cover;display:block;'>` ]]]"
            )
        },
        "styles": {
            "card": [
                {"border-radius": "16px"},
                {"height": "44px"},
                {"padding": "4px 12px 4px 6px"},
                {"box-shadow": "none"},
                {"background-color": "white"},
                {"position": "relative"},
            ],
            "grid": [
                {"grid-template-areas": "'i n'"},
                {"grid-template-columns": "30px auto"},
                {"align-items": "center"},
                {"justify-items": "start"},
            ],
            "name": [
                {"color": "#2b2b2b"},
                {"font-size": "13px"},
                {"font-weight": "600"},
                {"padding-left": "4px"},
            ],
            "custom_fields": {
                "pic": [
                    {"position": "absolute"},
                    {"left": "8px"},
                    {"top": "50%"},
                    {"transform": "translateY(-50%)"},
                    {"pointer-events": "none"},
                ]
            },
        },
    }


def _member_settings_stack(member_id: str, name_entity_id: str, birthdate_entity_id: str) -> dict:
    """One member's compact Name/Color/Avatar/Birthdate mini-card column, matching
    `Better-Settings.png`'s per-member layout - replaces the earlier full-width markdown
    header + horizontal-stack entities-card row, which didn't match the mockup's dense card
    grid at all."""
    return {
        "type": "vertical-stack",
        "cards": [
            _name_pill(name_entity_id),
            _color_pill(member_id, _color_select_entity_id(member_id)),
            _avatar_pill(member_id, _avatar_select_entity_id(member_id)),
            _birthdate_pill(member_id, birthdate_entity_id),
        ],
    }


def _avatar_grid_js(entity_id: str, color_entity_id: str) -> str:
    """The dynamic picture-grid array, ported from the legacy avatar-picker pop-ups (see
    module docstring). Built with plain `+` concatenation, not an f-string - every `{`/`}`
    character below is literal, nothing relies on doubled-brace escaping, specifically to
    avoid the brace-counting mistake that broke an earlier version of this feature.

    Every cell gets the member's own roster-color tint (the icon PNGs are transparent-
    background glyphs) so the picker itself previews how each option will actually look once
    picked, not a flat colorless grid.

    config-template-card's real templating mechanism, read directly from
    `config/www/community/config-template-card/config-template-card.js` after a live
    `pageerror: Unexpected token '{'` survived a fix that looked correct by every syntax check
    tried until then: it is NOT real JS-template-literal interpolation. It's
    `eval(varDef + template.substring(2, template.length - 1))` - a blind "chop off the first 2
    and last 1 characters" of the field's entire string value, so that value must be ENTIRELY
    `${...}` with nothing else outside it. A field like `"ha-card { ... } background:
    ${ ... } !important; }"` (literal CSS text surrounding an embedded `${}`) silently
    mis-strips to garbage - stripping 2 chars off the front of "ha-card" instead of off the
    real `${`. `eval` itself happily runs multiple statements (a `var x = ...; return ...;`
    body is fine on its own) - the `(() => { ... })()` wrapper below is just for consistency
    with any future per-cell logic that needs multiple statements, not a required fix.
    """
    color_map = roster_color_hex_js_map()
    return (
        "${ (() => { var tint = (" + color_map + ")[states['" + color_entity_id + "'].state] || '#cfd8e3'; "
        "return (states['" + AVATARS_SENSOR_ENTITY_ID + "'] && "
        "states['" + AVATARS_SENSOR_ENTITY_ID + "'].attributes.file_list || []).map(p => { "
        "var sel = states['" + entity_id + "'].state === p; "
        "return { "
        "type: 'picture', "
        "image: p, "
        "tap_action: { "
        "action: 'perform-action', "
        "perform_action: 'select.select_option', "
        "target: { entity_id: '" + entity_id + "' }, "
        "data: { option: p } "
        "}, "
        # 25% smaller than the grid cell itself (width/height:75%, centered via margin:auto) -
        # explicit user request, avatar icons read as too large in the picker popup.
        "card_mod: { style: 'ha-card{background:' + tint + ' !important;border-radius:14px !important;"
        "overflow:hidden;box-shadow:none;border:3px solid ' + (sel ? '#4A90E2' : 'transparent') + ' !important;"
        "width:75% !important;height:75% !important;margin:auto !important;}' "
        "} "
        "}; "
        "}); })() }"
    )


def _avatar_picker_popup(member_id: str) -> dict:
    entity_id = _avatar_select_entity_id(member_id)
    color_entity_id = _color_select_entity_id(member_id)
    return {
        "type": "custom:bubble-card",
        "card_type": "pop-up",
        "hash": f"#avatar-{member_id}",
        "name": "Choose Avatar",
        "icon": "mdi:face-man-profile",
        "cards": [
            {
                "type": "custom:config-template-card",
                "entities": [AVATARS_SENSOR_ENTITY_ID, entity_id, color_entity_id],
                "card": {
                    # 7 columns (up from 4) - with the live avatars sensor's current file count
                    # (35), this yields 5 rows instead of 9. `square: True` ties row height to
                    # column width, so more columns shrinks both dimensions at once and is the
                    # actual lever for fitting the whole grid on-screen without scrolling, not
                    # just a cosmetic change - the per-cell 75% inner scale (`_avatar_grid_js`)
                    # then shrinks the icon further within each now-smaller cell.
                    "type": "grid",
                    "columns": 7,
                    "square": True,
                    "cards": _avatar_grid_js(entity_id, color_entity_id),
                },
            }
        ],
    }


def _feature_toggle_pill(feature_key: str, entity_id: str) -> dict:
    """One small on/off pill per FEATURES key (Calendar/Lists/Chores & Rewards), bound to its
    `RosterFeatureSwitch` entity (`modules/settings/switch.py`) - tapping calls stock
    `switch.toggle`, same "call a stock service via tap_action" precedent `_color_swatch_card`
    already established with `select.select_option`. Kiosk/parent-only - see
    `async_settings_view_cards`'s own `only_member` gating.

    `entity_id` is passed in by the caller, resolved via the entity registry
    (`ent_reg.async_get_entity_id`) rather than guessed from a naming convention - live-verified
    this matters, not just style: this switch's OWN name ("<Name> Calendar") can collide with
    another entity's name (the Calendar module's own proxy, also named "<Name> Calendar"),
    which makes HA's registry disambiguate the actual entity_id with an area-name prefix
    (`switch.living_room_family_dashboard_<id>_calendar` instead of the "obvious" guessed
    `switch.family_dashboard_<id>_calendar`) - a guessed string would silently point at a
    nonexistent entity, exactly the class of bug this file's existing `name_id` resolution
    (in `async_settings_view_cards`) already avoids for the Name pill; this follows the same
    pattern instead of reintroducing the guessed-string mistake. `entity_id` can legitimately
    be `None` if this is called before the switch platform has actually forwarded (e.g. a
    dashboard-config build in isolation, without a full entry setup, as several tests do) -
    degrade to a harmless non-functional placeholder rather than crashing card generation over
    it, same defensive posture `_name_pill`'s own `name_entity_id` already has."""
    entity_id = entity_id or ""
    return {
        "type": "custom:button-card",
        "entity": entity_id,
        "name": FEATURES[feature_key]["name"],
        "show_name": True,
        "show_icon": False,
        "tap_action": {
            "action": "perform-action",
            "perform_action": "switch.toggle",
            "target": {"entity_id": entity_id},
        },
        "styles": {
            "card": [
                {"border-radius": "16px"},
                {"height": "40px"},
                {"padding": "4px 10px"},
                {"box-shadow": "none"},
                {
                    "background-color": (
                        "[[[ return states['" + entity_id + "'].state === 'on' "
                        "? '#33a02c' : '#e6e6e6' ]]]"
                    )
                },
            ],
            "name": [
                {
                    "color": (
                        "[[[ return states['" + entity_id + "'].state === 'on' "
                        "? 'white' : '#555' ]]]"
                    )
                },
                {"font-size": "12px"},
                {"font-weight": "600"},
                {"text-align": "center"},
            ],
        },
    }


def _feature_toggles_row(feature_entity_ids: dict[str, str]) -> dict:
    """This member's feature-toggle pills, side by side. `feature_entity_ids` maps each
    FEATURES key to its already-registry-resolved entity_id (see `_feature_toggle_pill`)."""
    return {
        "type": "horizontal-stack",
        "cards": [
            _feature_toggle_pill(key, entity_id) for key, entity_id in feature_entity_ids.items()
        ],
    }


def _entity_map_grid_js(entity_id: str, domain_prefix: str) -> str:
    """The dynamic mapping-picker grid: a "None" tile plus one tile per live entity whose
    entity_id starts with `domain_prefix` (e.g. "calendar." or "notify.") - enumerated from
    config-template-card's own `states` object at TEMPLATE-EVAL time (confirmed directly
    against `config-template-card.js`: `const states = this.hass ? this.hass.states :
    undefined` - the FULL live states map, not limited to whatever this card's own `entities:`
    list happens to declare; that list only controls when the card re-renders, not what the
    template itself can read), so newly-added calendars/notify targets show up on the next
    render without regenerating the dashboard. Built with plain `+` concatenation, not an
    f-string - same brace-counting-mistake avoidance as `_avatar_grid_js`.

    `entity_id` can be `None` before the select platform has forwarded - see
    `_feature_toggle_pill`'s docstring for why this degrades gracefully instead of crashing.
    """
    entity_id = entity_id or ""
    return (
        "${ (() => { var ids = Object.keys(states).filter(id => "
        "id.indexOf('" + domain_prefix + "') === 0).sort(); "
        "var cur = states['" + entity_id + "'].state; "
        "var noneCard = { "
        "type: 'custom:button-card', name: 'None', show_name: true, "
        "tap_action: { action: 'perform-action', perform_action: 'select.select_option', "
        "target: { entity_id: '" + entity_id + "' }, data: { option: '' } }, "
        "styles: { card: [ {'border-radius': '14px'}, {'box-shadow': 'none'}, "
        "{height: '48px'}, {'background-color': cur === '' ? '#5a6270' : '#e6e6e6'}, "
        "{border: '3px solid transparent'} ], "
        "name: [ {color: cur === '' ? 'white' : '#555'}, {'font-size': '12px'}, "
        "{'font-weight': '700'} ] } }; "
        "var entityCards = ids.map(id => { "
        "var sel = cur === id; "
        "var name = (states[id].attributes.friendly_name || id); "
        "return { "
        "type: 'custom:button-card', name: name, show_name: true, "
        "tap_action: { action: 'perform-action', perform_action: 'select.select_option', "
        "target: { entity_id: '" + entity_id + "' }, data: { option: id } }, "
        "styles: { card: [ {'border-radius': '14px'}, {'box-shadow': 'none'}, "
        "{height: '48px'}, {'background-color': '#ffffff'}, "
        "{border: sel ? '3px solid #4A90E2' : '3px solid transparent'} ], "
        "name: [ {color: '#2b2b2b'}, {'font-size': '12px'}, {'font-weight': '600'} ] } "
        "}; "
        "}); "
        "return [noneCard, ...entityCards]; "
        "})() }"
    )


def _mapping_picker_popup(member_id: str, entity_id: str, domain_prefix: str, *, hash_suffix: str, title: str, icon: str) -> dict:
    return {
        "type": "custom:bubble-card",
        "card_type": "pop-up",
        "hash": f"#{hash_suffix}-{member_id}",
        "name": title,
        "icon": icon,
        "cards": [
            {
                "type": "custom:config-template-card",
                "entities": [entity_id],
                "card": {
                    "type": "grid",
                    "columns": 3,
                    "square": False,
                    "cards": _entity_map_grid_js(entity_id, domain_prefix),
                },
            }
        ],
    }


def _calendar_map_popup(member_id: str, entity_id: str) -> dict:
    return _mapping_picker_popup(
        member_id,
        entity_id,
        "calendar.",
        hash_suffix="calendarmap",
        title="Map Calendar",
        icon="mdi:calendar-sync",
    )


def _notify_map_popup(member_id: str, entity_id: str) -> dict:
    return _mapping_picker_popup(
        member_id,
        entity_id,
        "notify.",
        hash_suffix="notifymap",
        title="Map Notify Target",
        icon="mdi:bell-ring",
    )


def _mapping_pill(name: str, member_id: str, entity_id: str, hash_suffix: str) -> dict:
    """'<Name>: <value>' pill, opening the matching mapping-picker popup - same shape as
    `_color_pill`, with 'None' shown in place of an empty (unmapped) state. `entity_id` can be
    `None` before the select platform has forwarded - see `_feature_toggle_pill`'s docstring
    for why this degrades gracefully instead of crashing."""
    entity_id = entity_id or ""
    return {
        "type": "custom:button-card",
        "entity": entity_id,
        "show_name": True,
        "show_icon": False,
        "name": (
            "[[[ var v = states['" + entity_id + "'].state; "
            "return '" + name + ": ' + (v ? v : 'None'); ]]]"
        ),
        "tap_action": {"action": "navigate", "navigation_path": f"#{hash_suffix}-{member_id}"},
        "styles": _PLAIN_PILL_STYLE,
    }


def _member_enabled_pill(enabled_entity_id: str) -> dict:
    """Whole-member Disable/re-enable toggle - a distinct, administrative concept from the
    per-feature toggle pills above (see `modules/settings/switch.py`'s `RosterEnabledSwitch`
    docstring): disabling excludes the member from the generated dashboard entirely and stops
    their calendar reminders, keeping all their data intact. Red when disabled (not the
    feature pills' neutral gray) - a deliberately more alarming color, since this affects
    everything about the member at once, not one feature. `entity_id` can be `None` before
    the switch platform has forwarded - see `_feature_toggle_pill`'s docstring for why this
    degrades gracefully instead of crashing."""
    entity_id = enabled_entity_id or ""
    return {
        "type": "custom:button-card",
        "entity": entity_id,
        "show_name": True,
        "show_icon": False,
        "name": (
            "[[[ return states['" + entity_id + "'].state === 'on' "
            "? 'Status: Enabled' : 'Status: Disabled' ]]]"
        ),
        "tap_action": {
            "action": "perform-action",
            "perform_action": "switch.toggle",
            "target": {"entity_id": entity_id},
        },
        "styles": {
            "card": [
                {"border-radius": "16px"},
                {"height": "40px"},
                {"padding": "4px 10px"},
                {"box-shadow": "none"},
                {
                    "background-color": (
                        "[[[ return states['" + entity_id + "'].state === 'on' "
                        "? '#33a02c' : '#c62828' ]]]"
                    )
                },
            ],
            "name": [
                {"color": "white"},
                {"font-size": "12px"},
                {"font-weight": "600"},
                {"text-align": "center"},
            ],
        },
    }


def _delete_member_tile(name_entity_id: str, member_name: str) -> dict:
    """Permanently deletes a roster member (`family_dashboard.delete_member` - see
    `roster.py`'s `async_delete_member` docstring for why this is a real removal, not
    `hidden_by`) - gated behind a native Lovelace `confirmation:` prompt, same mechanism as
    `_delete_tile` for chores/rewards, but with a deliberately stronger warning since this
    removes a whole person's data, not one item."""
    entity_id = name_entity_id or ""
    return {
        "type": "custom:button-card",
        "name": "Delete Member",
        "icon": "mdi:account-remove",
        "show_name": True,
        "show_icon": True,
        "tap_action": {
            "action": "perform-action",
            "perform_action": "family_dashboard.delete_member",
            "target": {"entity_id": entity_id},
            "confirmation": {
                "text": (
                    f"Permanently delete {member_name} and ALL their data - chores, "
                    "points, lists, calendar/notify mapping? This cannot be undone."
                )
            },
        },
        "styles": {
            "card": [
                {"border-radius": "16px"},
                {"height": "40px"},
                {"padding": "4px 10px"},
                {"box-shadow": "none"},
                {"background-color": "#c62828"},
            ],
            "name": [
                {"color": "white"},
                {"font-size": "12px"},
                {"font-weight": "600"},
            ],
            "icon": [{"color": "white"}],
        },
    }


def _feature_and_mapping_stack(
    member_id: str,
    member_name: str,
    feature_entity_ids: dict[str, str],
    calendar_entity_id: str,
    notify_entity_id: str,
    enabled_entity_id: str,
    name_entity_id: str,
) -> dict:
    """Kiosk/parent-only controls (Feature toggles + Calendar/Notify mapping + Remove Member)
    for one member - kept SEPARATE from `_member_settings_stack` (Name/Color/Avatar/
    Birthdate), which is shown to every bucket, because these must only ever appear when
    `only_member is None` (explicit user decision: a linked member should not be able to
    change their own feature selection, calendar/notify mapping, or remove themselves, from
    their personal bucket). All entity ids are pre-resolved by the caller via the entity
    registry, not guessed - see `_feature_toggle_pill`'s docstring for why guessing is unsafe
    here."""
    return {
        "type": "vertical-stack",
        "cards": [
            _feature_toggles_row(feature_entity_ids),
            _mapping_pill("Calendar", member_id, calendar_entity_id, "calendarmap"),
            _mapping_pill("Notify", member_id, notify_entity_id, "notifymap"),
            {
                "type": "horizontal-stack",
                "cards": [
                    _member_enabled_pill(enabled_entity_id),
                    _delete_member_tile(name_entity_id, member_name),
                ],
            },
        ],
    }


def _nav_button(name: str, icon: str, hash_suffix: str) -> dict:
    """Opens a Chores & Rewards popup (Add Chore/Add Reward) - same visual shape as
    `async_change_pin_button` (modules/chores/dashboard.py), kept as a small local copy since
    it's just markup, matching this file's own existing "small local copy over cross-module
    import for pure markup" convention (see `_avatar_header`-style precedents elsewhere)."""
    return {
        "type": "custom:button-card",
        "name": name,
        "icon": icon,
        "show_name": True,
        "show_icon": True,
        "tap_action": {"action": "navigate", "navigation_path": f"#{hash_suffix}"},
        "styles": _NAV_BUTTON_STYLE,
    }


def _field_pill(label: str, entity_id: str | None) -> dict:
    """A generic "<Label>: <value>" pill opening the entity's own native more-info dialog -
    used for chore/reward fields (name/points-or-cost/frequency/assigned-to). Unlike Avatar/
    Color, there's nothing image/swatch-like to preview, so HA's stock more-info dialog (a
    text box, a number box/slider, or a dropdown) is enough on its own - no custom picker
    popup needed. `entity_id` can be `None` before the platform has forwarded - see
    `_feature_toggle_pill`'s docstring for why this degrades gracefully instead of crashing."""
    entity_id = entity_id or ""
    return {
        "type": "custom:button-card",
        "entity": entity_id,
        "show_name": True,
        "show_icon": False,
        "name": (
            "[[[ var s = states['" + entity_id + "']; "
            "return '" + label + ": ' + (s ? s.state : ''); ]]]"
        ),
        "tap_action": {"action": "more-info"},
        "styles": _PLAIN_PILL_STYLE,
    }


def _delete_tile(entity_id: str | None, item_name: str) -> dict:
    """Genuinely deletes a chore/reward (`family_dashboard.delete_task` - see `crud.py`'s
    module docstring for why this is a real removal, not `hidden_by`) - gated behind a native
    Lovelace `confirmation:` prompt (stock tap_action feature, no custom popup needed) since
    there's no undo."""
    entity_id = entity_id or ""
    return {
        "type": "custom:button-card",
        "name": "Delete",
        "icon": "mdi:trash-can",
        "show_name": True,
        "show_icon": True,
        "tap_action": {
            "action": "perform-action",
            "perform_action": "family_dashboard.delete_task",
            "target": {"entity_id": entity_id},
            "confirmation": {"text": f"Delete '{item_name}'? This cannot be undone."},
        },
        "styles": {
            "card": [
                {"border-radius": "16px"},
                {"height": "44px"},
                {"padding": "4px 12px 4px 6px"},
                {"box-shadow": "none"},
                {"background-color": "#d9534f"},
            ],
            "grid": [
                {"grid-template-areas": "'i n'"},
                {"grid-template-columns": "30px auto"},
                {"align-items": "center"},
                {"justify-items": "start"},
            ],
            "icon": [{"width": "18px"}, {"color": "white"}],
            "name": [
                {"color": "white"},
                {"font-size": "13px"},
                {"font-weight": "600"},
                {"padding-left": "4px"},
            ],
        },
    }


def _chore_row(ent_reg, entry: ConfigEntry, chore: dict) -> dict:
    chore_id = chore["chore_id"]
    name_id = ent_reg.async_get_entity_id("text", DOMAIN, f"{entry.entry_id}_{chore_id}_name")
    points_id = ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_{chore_id}_points")
    frequency_id = ent_reg.async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_{chore_id}_frequency")
    assigned_id = ent_reg.async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_{chore_id}_assigned_to")
    sensor_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{chore_id}_chore")
    return {
        "type": "horizontal-stack",
        "cards": [
            _field_pill("Name", name_id),
            _field_pill("Points", points_id),
            _field_pill("Frequency", frequency_id),
            _field_pill("Assigned To", assigned_id),
            _delete_tile(sensor_id, chore["name"]),
        ],
    }


def _reward_row(ent_reg, entry: ConfigEntry, reward: dict) -> dict:
    reward_id = reward["reward_id"]
    name_id = ent_reg.async_get_entity_id("text", DOMAIN, f"{entry.entry_id}_{reward_id}_name")
    cost_id = ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_{reward_id}_cost")
    assigned_id = ent_reg.async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_{reward_id}_assigned_to")
    sensor_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{reward_id}_reward")
    return {
        "type": "horizontal-stack",
        "cards": [
            _field_pill("Name", name_id),
            _field_pill("Cost", cost_id),
            _field_pill("Assigned To", assigned_id),
            _delete_tile(sensor_id, reward["name"]),
        ],
    }


def _add_item_popup(
    *, hash_suffix: str, title: str, icon: str, entities: list[dict], service: str
) -> dict:
    return {
        "type": "custom:bubble-card",
        "card_type": "pop-up",
        "hash": f"#{hash_suffix}",
        "name": title,
        "icon": icon,
        "cards": [
            {"type": "entities", "entities": entities, "show_header_toggle": False},
            {
                "type": "button",
                "name": title,
                "icon": icon,
                "tap_action": {
                    "action": "perform-action",
                    "perform_action": service,
                    "target": {"entity_id": entities[0]["entity"]},
                },
            },
        ],
    }


def _add_chore_popup(ent_reg, entry: ConfigEntry) -> dict:
    name_id = ent_reg.async_get_entity_id("text", DOMAIN, f"{entry.entry_id}_new_chore_name") or ""
    points_id = ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_new_chore_points") or ""
    frequency_id = ent_reg.async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_new_chore_frequency") or ""
    assigned_id = ent_reg.async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_new_chore_assigned_to") or ""
    return _add_item_popup(
        hash_suffix="addchore",
        title="Add Chore",
        icon="mdi:broom",
        entities=[
            {"entity": name_id, "name": "Name"},
            {"entity": points_id, "name": "Points"},
            {"entity": frequency_id, "name": "Frequency"},
            {"entity": assigned_id, "name": "Assigned To"},
        ],
        service="family_dashboard.add_chore",
    )


def _add_reward_popup(ent_reg, entry: ConfigEntry) -> dict:
    name_id = ent_reg.async_get_entity_id("text", DOMAIN, f"{entry.entry_id}_new_reward_name") or ""
    cost_id = ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_new_reward_cost") or ""
    assigned_id = ent_reg.async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_new_reward_assigned_to") or ""
    return _add_item_popup(
        hash_suffix="addreward",
        title="Add Reward",
        icon="mdi:gift",
        entities=[
            {"entity": name_id, "name": "Name"},
            {"entity": cost_id, "name": "Cost"},
            {"entity": assigned_id, "name": "Assigned To"},
        ],
        service="family_dashboard.add_reward",
    )


def _chores_rewards_section(ent_reg, entry: ConfigEntry) -> list[dict]:
    """The Chores & Rewards management section - Add Chore/Add Reward buttons, one row per
    existing chore/reward with live-editable fields + a confirmed Delete, and the two Add
    popups. Kiosk/parent-only - see `async_settings_view_cards`'s own gating, same as Features
    & Mapping."""
    cards: list[dict] = [
        {"type": "markdown", "content": "## Chores & Rewards"},
        {"type": "horizontal-stack", "cards": [
            _nav_button("Add Chore", "mdi:broom", "addchore"),
            _nav_button("Add Reward", "mdi:gift", "addreward"),
        ]},
    ]
    for chore in entry.data.get(CONF_CHORES, []):
        cards.append(_chore_row(ent_reg, entry, chore))
    for reward in entry.data.get(CONF_REWARDS, []):
        cards.append(_reward_row(ent_reg, entry, reward))
    cards.append(_add_chore_popup(ent_reg, entry))
    cards.append(_add_reward_popup(ent_reg, entry))
    return cards


async def async_settings_view_cards(
    hass: HomeAssistant, entry: ConfigEntry, only_member: dict | None = None
) -> list[dict]:
    """Matches `Better-Settings.png`'s dense grid of compact per-member cards - a prior version
    used a full-width markdown header + horizontal-stack per member (a plain linear list, not
    the mockup's grid), which the user pointed back to as "not pretty" after other fixes this
    session. Birthdays/Holidays' own colored cards from that mockup are intentionally NOT
    ported here - they'd need new `select` entities for user-configurable colors (real new
    scope, not a restyle), left for a future request rather than assumed.

    `only_member`, when given, restricts the Name/Color/Avatar grid to just that one roster
    member instead of everyone - explicit user requirement: the Kiosk bucket can still see
    and change every member's own settings (matches its "sees/can-adjust everything" role
    everywhere else in this dashboard), but a linked member's own personal bucket should only
    ever show THEIR OWN settings, not another family member's - `dashboard/registry.py`'s
    per-bucket Settings-view loop passes `bucket.member` for a personal bucket and `None` for
    Kiosk. The household Parent PIN section is intentionally NOT scoped by `only_member` - it
    is not any one member's own setting, and stays gated on "does ANYONE in the full roster
    have chores enabled" exactly as before, regardless of which bucket is looking.

    Feature toggles, Calendar/Notify mapping, and Remove Member (Disable/Delete -
    `_feature_and_mapping_stack`) are Kiosk/parent-only - explicit user decision, unlike Name/
    Color/Avatar/Birthdate: they're only added when `only_member is None`, never for a linked
    member's own personal bucket, regardless of whose settings that bucket is otherwise
    allowed to see. Chores & Rewards management (`_chores_rewards_section` - Add/Modify/
    Delete) is gated the same way, on top of the existing "does anyone have chores enabled"
    check the Parent PIN section already uses.
    """
    ent_reg = er.async_get(hass)
    roster = entry.data[CONF_ROSTER]
    visible_roster = [only_member] if only_member is not None else roster

    birthdate_scratch_id = ent_reg.async_get_entity_id(
        "text", DOMAIN, f"{entry.entry_id}_{BIRTHDATE_SCRATCH_UNIQUE_ID}"
    )

    cards: list[dict] = [{"type": "markdown", "content": "## Settings"}]
    member_stacks = []
    popups = []
    for member in visible_roster:
        member_id = member["member_id"]
        name_id = ent_reg.async_get_entity_id("text", DOMAIN, f"{entry.entry_id}_{member_id}_name")
        birthdate_id = ent_reg.async_get_entity_id("date", DOMAIN, f"{entry.entry_id}_{member_id}_birthdate")
        member_stacks.append(_member_settings_stack(member_id, name_id, birthdate_id))
        popups.append(_avatar_picker_popup(member_id))
        popups.append(_color_picker_popup(member_id, _color_select_entity_id(member_id)))
        popups.append(_birthdate_edit_popup(member_id, birthdate_id, birthdate_scratch_id))

    cards.append({"type": "grid", "columns": 4, "square": False, "cards": member_stacks})
    cards.extend(popups)

    if only_member is None:
        cards.append({"type": "markdown", "content": "## Features & Mapping"})
        feature_stacks = []
        mapping_popups = []
        for member in roster:
            member_id = member["member_id"]
            feature_entity_ids = {
                key: ent_reg.async_get_entity_id(
                    "switch", DOMAIN, f"{entry.entry_id}_{member_id}_feature_{key}"
                )
                for key in FEATURES
            }
            calendar_map_id = ent_reg.async_get_entity_id(
                "select", DOMAIN, f"{entry.entry_id}_{member_id}_calendar_map"
            )
            notify_map_id = ent_reg.async_get_entity_id(
                "select", DOMAIN, f"{entry.entry_id}_{member_id}_notify_map"
            )
            enabled_id = ent_reg.async_get_entity_id(
                "switch", DOMAIN, f"{entry.entry_id}_{member_id}_enabled"
            )
            name_id = ent_reg.async_get_entity_id(
                "text", DOMAIN, f"{entry.entry_id}_{member_id}_name"
            )
            feature_stacks.append(
                _feature_and_mapping_stack(
                    member_id,
                    member["name"],
                    feature_entity_ids,
                    calendar_map_id,
                    notify_map_id,
                    enabled_id,
                    name_id,
                )
            )
            mapping_popups.append(_calendar_map_popup(member_id, calendar_map_id))
            mapping_popups.append(_notify_map_popup(member_id, notify_map_id))
        cards.append({"type": "grid", "columns": 4, "square": False, "cards": feature_stacks})
        cards.extend(mapping_popups)

    if only_member is None and any("chores" in member.get(CONF_FEATURES, []) for member in roster):
        cards.extend(_chores_rewards_section(ent_reg, entry))

    if any("chores" in member.get(CONF_FEATURES, []) for member in roster):
        cards.append({"type": "markdown", "content": "## Parent PIN"})
        cards.append(async_change_pin_button())
        cards.append(async_pin_change_popup_card())

    return cards
