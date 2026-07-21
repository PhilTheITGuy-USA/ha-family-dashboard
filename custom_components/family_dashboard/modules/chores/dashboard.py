"""Dashboard-template contribution for the Chores & Rewards module.

Entity IDs are resolved via the entity registry at build time (same
`unique_id -> entity_id` lookup `modules/chores/button.py`'s Claim/Approve buttons already
use to find their sibling sensor), not guessed by re-deriving HA's slugification - more
robust than reconstructing `sensor.family_dashboard_<name>_<item>` by hand.

Kiosk bucket: one column per kid (member with "chores" enabled), each wrapped in a
`type: conditional` card keyed on that member's `switch.family_dashboard_<id>_shown` state -
the same toggle-filter mechanism Calendar uses, just via a whole-card conditional instead of
a per-entry `filter:` string (Chores has no equivalent to week-planner-card's overlay, so
showing/hiding the whole column is the natural fit). Plus a Parent lock/unlock control and,
once unlocked, an inline Parent Review section AND a Chores & Rewards management section
(Add/edit/delete chores and rewards, `async_chores_rewards_management_card`) - both gated on
the SAME `binary_sensor.family_dashboard_parent_mode` conditional, both ported from the legacy
`REPO/ha-family-hub/dashboards/family-hub.yaml`'s proven mechanism: a `custom:bubble-card`
pop-up (already installed via HACS) anchored at `#parentpin` for the PIN numpad (button-card's
own `[[[ ]]]` template syntax for the lock button's state-dependent name/icon/color/tap_action,
exactly as legacy did it - no config-template-card needed for this piece), and each pending
claim's Approve/Deny row wrapped in its own `type: conditional` keyed on that item's sensor
state being "claimed" - so the Review list updates live as claims come in/get resolved,
without needing the dashboard to regenerate. The management section moved here from
`modules/settings/dashboard.py` on 2026-07-20 (live-reported: that Settings location was
Kiosk-only but had no PIN gate at all - any kid could add/reassign/repoint/delete chores and
rewards freely).

Personal buckets: just that member's own points + chore/reward cards, no toggle, no Parent
controls (the PIN gate and Review are Kiosk-bucket-only, per the mockup and the rebuild plan's
"Decided" section - a kid's own login isn't where Review happens, PIN knowledge is).

Deny has a real free-text reason field (`modules/chores/text.py`'s `TaskDenyReasonText`, one
per chore/reward), not a fixed string - no "load then open a popup" chained tap_action is
needed to get there (button-card's installed source has no array/chained tap_action, the same
constraint that shaped the per-item Modify fields), because each item's own Reason tile is
always present in its Review row and the Deny action reads it live via button-card's `[[[ ]]]`
templating in `tap_action.data` (already proven in this file for `async_parent_lock_card`'s
state-dependent action/color) rather than needing a shared scratch field pre-loaded first.

Chores can optionally be day-of-week scheduled (2026-07-21, `_member_task_cards`): splitting
one chore across multiple kids means creating one independent chore record per kid, each with
its own `schedule_days` subset (e.g. two "Dishes" chores, Tristan Mon/Wed/Fri and Harlee
Tue/Thu/Sat) - NOT one record holding a day->assignee map, since claim/approve/points has no
"who claimed it today" concept separate from a chore's fixed `assigned_to` (see
`modules/chores/sensor.py`'s docstring). A scheduled chore's tile is wrapped in one
`type: conditional` per configured day, keyed on the household's day-of-week sensor
(`FamilyDashboardDayOfWeekSensor`) - the same conditional mechanism already proven for the
Parent PIN gate, just watching a different entity. An unscheduled chore (`schedule_days`
absent/`None`, the default) is unaffected - visible every day, exactly as before this feature.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ...const import CONF_CHORES, CONF_FEATURES, CONF_REWARDS, DOMAIN
from ...util import format_schedule_days
from ..calendar.dashboard import member_avatar_toggle_pill
from .sensor import (
    _day_of_week_unique_id,
    _deny_reason_unique_id,
    _points_unique_id,
    _schedule_scratch_unique_id,
    _task_unique_id,
)


def _shown_switch_entity_id(member_id: str) -> str:
    return f"switch.family_dashboard_{member_id}_shown"


def _avatar_header(member: dict) -> dict:
    """Same avatar+header pattern as `dashboard/registry.py`'s Lists header - kept as a small
    local copy rather than a cross-module import, since it's just markup.

    NOT a markdown card with a raw `<img>` tag, after two live-verified failed attempts at
    that: HA's markdown card strips inline `style=` attributes from rendered HTML entirely
    (`img.getAttribute('style')` came back `null`, leaving the seeded 640x640 avatar PNGs at
    native size), and even a `card_mod.style` fix using card_mod's documented shadow-piercing
    `"<selector>$"` syntax still didn't reach the `<img>` - a shadow-DOM host-chain trace
    showed it two boundaries deep inside `ha-markdown-element`'s own nested shadow root.
    Switched to `custom:button-card`'s `custom_fields.pic` mechanism instead - the same
    avatar-image technique already proven reliable elsewhere this session
    (`modules/calendar/dashboard.py`'s `member_avatar_toggle_pill`), since button-card doesn't
    sanitize its custom-field HTML the way markdown does. See `dashboard/registry.py`'s
    `_avatar_header` for the full investigation trail.
    """
    avatar_entity = f"select.family_dashboard_{member['member_id']}_avatar"
    return {
        "type": "custom:button-card",
        "show_name": True,
        "show_icon": False,
        "name": member["name"],
        "custom_fields": {
            "pic": (
                "[[[ return `<img src='${states['" + avatar_entity + "'].state}' "
                "onerror='this.remove()' style='width:28px;height:28px;border-radius:50%;"
                "object-fit:cover;display:block;'>` ]]]"
            )
        },
        "styles": {
            "card": [
                {"box-shadow": "none"},
                {"background": "transparent"},
                {"padding": "8px 0 8px 44px"},
                {"height": "auto"},
                {"position": "relative"},
            ],
            "grid": [
                {"grid-template-areas": "'n'"},
                {"align-items": "center"},
                {"justify-items": "start"},
            ],
            "name": [
                {"font-size": "20px"},
                {"font-weight": "700"},
                {"justify-self": "start"},
            ],
            "custom_fields": {
                "pic": [
                    {"position": "absolute"},
                    {"left": "0"},
                    {"top": "50%"},
                    {"transform": "translateY(-50%)"},
                    {"pointer-events": "none"},
                ]
            },
        },
    }


def _tile(entity_id: str, name: str, icon: str, tap_target: str | None = None) -> dict:
    """A `tile` card that presses a button-domain entity on tap (explicit `tap_action`
    rather than relying on the tile card's default behavior for the entity's domain)."""
    card: dict = {"type": "tile", "entity": entity_id, "name": name, "icon": icon}
    if tap_target:
        card["tap_action"] = {
            "action": "perform-action",
            "perform_action": "button.press",
            "target": {"entity_id": tap_target},
        }
    return card


async def _member_task_cards(hass: HomeAssistant, entry: ConfigEntry, member: dict) -> list[dict]:
    """Points tile plus one tile per chore/reward assigned to this member. Empty if they have
    neither chores nor rewards assigned (still shows Points if they have the feature).

    A chore with `schedule_days` set (see `util.parse_schedule_days_text`) is only visible on
    those days: its tile is wrapped in one `type: conditional` per configured day, keyed on
    the household's `FamilyDashboardDayOfWeekSensor` state - deliberately N separate
    single-state conditionals rather than one multi-value condition, since nothing in this
    codebase currently uses or has verified list-based OR state-matching, while this exact
    single-state conditional shape is already proven for the Parent PIN gate. An unscheduled
    chore (`schedule_days` absent/`None` - every existing chore before this feature, and the
    default for every new one) renders exactly as before, unconditionally."""
    ent_reg = er.async_get(hass)
    cards: list[dict] = []

    points_entity_id = ent_reg.async_get_entity_id(
        "sensor", DOMAIN, _points_unique_id(entry, member["member_id"])
    )
    if points_entity_id:
        cards.append(_tile(points_entity_id, "Points", "mdi:star-four-points-circle"))

    chores = [c for c in entry.data.get(CONF_CHORES, []) if c["assigned_to"] == member["member_id"]]
    if chores:
        cards.append({"type": "markdown", "content": "#### Chores"})
        day_of_week_entity_id = None
        for chore in chores:
            task_uid = _task_unique_id(entry, chore["chore_id"], "chore")
            sensor_id = ent_reg.async_get_entity_id("sensor", DOMAIN, task_uid)
            claim_id = ent_reg.async_get_entity_id("button", DOMAIN, f"{task_uid}_claim")
            if not sensor_id:
                continue
            tile = _tile(sensor_id, chore["name"], "mdi:broom", tap_target=claim_id)
            schedule_days = chore.get("schedule_days")
            if not schedule_days:
                cards.append(tile)
                continue
            if day_of_week_entity_id is None:
                day_of_week_entity_id = ent_reg.async_get_entity_id(
                    "sensor", DOMAIN, _day_of_week_unique_id(entry)
                )
            if not day_of_week_entity_id:
                cards.append(tile)
                continue
            for day in schedule_days:
                cards.append(
                    {
                        "type": "conditional",
                        "conditions": [{"entity": day_of_week_entity_id, "state": day}],
                        "card": tile,
                    }
                )

    rewards = [r for r in entry.data.get(CONF_REWARDS, []) if r["assigned_to"] == member["member_id"]]
    if rewards:
        cards.append({"type": "markdown", "content": "#### Rewards"})
        for reward in rewards:
            task_uid = _task_unique_id(entry, reward["reward_id"], "reward")
            sensor_id = ent_reg.async_get_entity_id("sensor", DOMAIN, task_uid)
            claim_id = ent_reg.async_get_entity_id("button", DOMAIN, f"{task_uid}_claim")
            if sensor_id:
                cards.append(_tile(sensor_id, reward["name"], "mdi:gift", tap_target=claim_id))

    return cards


async def async_chores_cards_for_member(
    hass: HomeAssistant, entry: ConfigEntry, member: dict
) -> list[dict]:
    """A personal bucket's fixed Chores content - just this member's own points/chores/
    rewards, no toggle, no Parent controls."""
    if "chores" not in member.get(CONF_FEATURES, []):
        return []
    return await _member_task_cards(hass, entry, member)


def _review_item_card(
    sensor_entity_id: str,
    approve_entity_id: str | None,
    reason_entity_id: str | None,
    name: str,
) -> dict:
    """One pending claim's Reason/Approve/Deny row, only rendered while that item's sensor is
    actually "claimed" - updates live without a dashboard regenerate as claims resolve.

    The Reason tile is a plain `text` entity tile (tap opens the native more-info text-entry
    dialog, same pattern as the per-item Name/Points fields) sitting right next to Deny. Deny
    itself is `custom:button-card` (not a stock `tile`) so its `tap_action.data.reason` can be
    a `[[[ ]]]` JS template reading that same reason entity's live state at tap time - no
    separate "load the value, then open a popup" step needed.
    """
    action_cards = []
    if approve_entity_id:
        action_cards.append(
            {
                "type": "tile",
                "entity": approve_entity_id,
                "name": "Approve",
                "icon": "mdi:check-decagram",
                "tap_action": {
                    "action": "perform-action",
                    "perform_action": "button.press",
                    "target": {"entity_id": approve_entity_id},
                },
            }
        )
    if reason_entity_id:
        action_cards.append(
            {"type": "tile", "entity": reason_entity_id, "name": "Reason", "icon": "mdi:comment-text-outline"}
        )
    action_cards.append(
        {
            "type": "custom:button-card",
            "entity": sensor_entity_id,
            "name": "Deny",
            "icon": "mdi:close-octagon",
            "show_name": True,
            "show_icon": True,
            "tap_action": {
                "action": "perform-action",
                "perform_action": "family_dashboard.deny_task",
                "target": {"entity_id": sensor_entity_id},
                "data": {
                    "reason": (
                        "[[[ return states['" + (reason_entity_id or "") + "'] ? "
                        "states['" + (reason_entity_id or "") + "'].state : '' ]]]"
                    )
                },
            },
            "styles": {
                "card": [{"box-shadow": "none"}],
            },
        }
    )
    return {
        "type": "conditional",
        "conditions": [{"entity": sensor_entity_id, "state": "claimed"}],
        "card": {
            "type": "horizontal-stack",
            "cards": [{"type": "tile", "entity": sensor_entity_id, "name": name}, *action_cards],
        },
    }


async def async_parent_review_card(
    hass: HomeAssistant, entry: ConfigEntry, chores_members: list[dict]
) -> dict:
    """The Kiosk bucket's Parent Review section - every chores-enabled member's pending
    claims, gated by `binary_sensor.family_dashboard_parent_mode` being "on". PIN knowledge
    unlocks it, not identity - see this module's docstring."""
    ent_reg = er.async_get(hass)
    cards: list[dict] = [{"type": "markdown", "content": "## Parent Review"}]

    for member in chores_members:
        member_cards: list[dict] = []
        for chore in entry.data.get(CONF_CHORES, []):
            if chore["assigned_to"] != member["member_id"]:
                continue
            task_uid = _task_unique_id(entry, chore["chore_id"], "chore")
            sensor_id = ent_reg.async_get_entity_id("sensor", DOMAIN, task_uid)
            if sensor_id:
                approve_id = ent_reg.async_get_entity_id("button", DOMAIN, f"{task_uid}_approve")
                reason_id = ent_reg.async_get_entity_id(
                    "text", DOMAIN, _deny_reason_unique_id(entry, chore["chore_id"], "chore")
                )
                member_cards.append(
                    _review_item_card(sensor_id, approve_id, reason_id, chore["name"])
                )
        for reward in entry.data.get(CONF_REWARDS, []):
            if reward["assigned_to"] != member["member_id"]:
                continue
            task_uid = _task_unique_id(entry, reward["reward_id"], "reward")
            sensor_id = ent_reg.async_get_entity_id("sensor", DOMAIN, task_uid)
            if sensor_id:
                approve_id = ent_reg.async_get_entity_id("button", DOMAIN, f"{task_uid}_approve")
                reason_id = ent_reg.async_get_entity_id(
                    "text", DOMAIN, _deny_reason_unique_id(entry, reward["reward_id"], "reward")
                )
                member_cards.append(
                    _review_item_card(sensor_id, approve_id, reason_id, reward["name"])
                )
        if member_cards:
            cards.append({"type": "markdown", "content": f"### {member['name']}"})
            cards.extend(member_cards)

    if len(cards) == 1:
        cards.append({"type": "markdown", "content": "_Nothing awaiting review._"})

    return {
        "type": "conditional",
        "conditions": [{"entity": "binary_sensor.family_dashboard_parent_mode", "state": "on"}],
        "card": {"type": "vertical-stack", "cards": cards},
    }


def _pin_digit_button(digit: str, service: str = "family_dashboard.append_pin_digit") -> dict:
    """`service` defaults to the original auto-submit-at-4 unlock service; the PIN-change
    popup passes `family_dashboard.append_pin_digit_raw` instead (plain accumulate, no
    auto-submit - see modules/chores/text.py's module docstring for why the two flows can't
    share the same append behavior)."""
    return {
        "type": "custom:button-card",
        "name": digit,
        "show_name": True,
        "tap_action": {
            "action": "perform-action",
            "perform_action": service,
            "target": {"entity_id": "text.family_dashboard_pin_entry"},
            "data": {"digit": digit},
        },
        "styles": {
            "card": [
                {"height": "68px"},
                {"border-radius": "12px"},
                {"box-shadow": "none"},
                {"background-color": "rgba(255,255,255,0.92)"},
            ],
            "name": [{"color": "#2b2b2b"}, {"font-size": "22px"}, {"font-weight": "600"}],
        },
    }


def _pin_clear_button() -> dict:
    """Clears the PIN-entry buffer outright (a full reset, not a single-character backspace -
    a 4-digit PIN doesn't need finer granularity). Fills the numpad's otherwise-empty
    bottom-left cell with something useful rather than a blank filler card (an earlier version
    used an empty `markdown` card there, which HA rejected as invalid config - live-verified
    via a real browser screenshot, not assumed)."""
    return {
        "type": "custom:button-card",
        "name": "Clear",
        "show_name": True,
        "tap_action": {
            "action": "perform-action",
            "perform_action": "text.set_value",
            "target": {"entity_id": "text.family_dashboard_pin_entry"},
            "data": {"value": ""},
        },
        "styles": {
            "card": [
                {"height": "68px"},
                {"border-radius": "12px"},
                {"box-shadow": "none"},
                {"background-color": "rgba(255,255,255,0.7)"},
            ],
            # 14px -> 16px (2026-07-20 kiosk legibility pass) - matches the digit buttons'
            # own 22px better than the old mismatch did.
            "name": [{"color": "#5a6270"}, {"font-size": "16px"}, {"font-weight": "600"}],
        },
    }


def async_pin_popup_card() -> dict:
    """The PIN numpad - a `custom:bubble-card` pop-up anchored at `#parentpin`, ported
    directly from the legacy dashboard's proven mechanism (see module docstring). Each digit
    calls `family_dashboard.append_pin_digit`; the masked-length display reads
    `text.family_dashboard_pin_entry` via a Jinja template, same as legacy's
    `input_text.pin_entry` equivalent. `square: False` on the grid card is required - the
    `grid` card type defaults to forcing square cells sized to the grid's width, which inside
    a Bubble-Card pop-up produces huge vertical gaps between rows (live-verified via a real
    browser screenshot).
    """
    digit_grid = [_pin_digit_button(str(n)) for n in range(1, 10)]
    digit_grid += [_pin_clear_button(), _pin_digit_button("0")]
    return {
        "type": "custom:bubble-card",
        "card_type": "pop-up",
        "hash": "#parentpin",
        "name": "Parent PIN",
        "icon": "mdi:shield-lock",
        "cards": [
            {
                "type": "markdown",
                "content": (
                    "<div style='text-align:center;font-size:30px;letter-spacing:8px;"
                    "height:36px;'>{{ '●' * "
                    "(states('text.family_dashboard_pin_entry')|length) }}</div>"
                ),
                "card_mod": {
                    "style": (
                        "ha-card{background:transparent !important;box-shadow:none "
                        "!important;border:none !important;}"
                    )
                },
            },
            {"type": "grid", "columns": 3, "square": False, "cards": digit_grid},
        ],
    }


def async_parent_lock_card() -> dict:
    """Locked/Unlocked toggle for the Kiosk bucket's Chores tab - button-card's own
    `[[[ ]]]` JS template syntax (native to button-card, no config-template-card wrapper
    needed) for state-dependent name/icon/color/tap_action, ported from the legacy pattern.
    Locked: navigates to the PIN pop-up. Unlocked: presses the Lock button directly.

    Full row width, matching every other row on this tab (toggle pills, per-kid columns) -
    a centered, content-width version was tried first (`width: fit-content` + `margin: 0
    auto` on the inner `ha-card`) but a live screenshot showed it still flush-left, not
    centered, inside its `horizontal-stack` wrapper. Per explicit user direction: if it
    can't be reliably centered, full-width is the fallback for visual consistency with the
    rest of the view, rather than leaving it in a half-fixed, oddly-positioned state.
    """
    parent_mode = "binary_sensor.family_dashboard_parent_mode"
    return {
        "type": "custom:button-card",
        "show_name": True,
        "show_icon": True,
        "name": (
            f"[[[ return states['{parent_mode}'].state === 'on' ? "
            "'Parent: Unlocked' : 'Parent: Locked' ]]]"
        ),
        "icon": (
            f"[[[ return states['{parent_mode}'].state === 'on' ? "
            "'mdi:shield-account' : 'mdi:shield-lock' ]]]"
        ),
        "tap_action": {
            "action": (
                f"[[[ return states['{parent_mode}'].state === 'on' ? "
                "'perform-action' : 'navigate' ]]]"
            ),
            "perform_action": "button.press",
            "target": {"entity_id": "button.family_dashboard_lock_parent_mode"},
            "navigation_path": "#parentpin",
        },
        "styles": {
            "card": [
                {"border-radius": "26px"},
                {"height": "52px"},
                {"padding": "4px 14px 4px 6px"},
                {"box-shadow": "none"},
                {
                    "background-color": (
                        f"[[[ return states['{parent_mode}'].state === 'on' ? "
                        "'#33a02c' : '#5a6270' ]]]"
                    )
                },
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
                {"font-weight": "600"},
                # 13px -> 16px (2026-07-20 kiosk legibility pass) - see registry.py's
                # `_pill_styles` for why.
                {"font-size": "16px"},
                {"padding-left": "6px"},
                {"white-space": "nowrap"},
            ],
        },
    }


_MANAGE_NAV_BUTTON_STYLE = {
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
    # 16px, not the 13px `modules/settings/dashboard.py`'s original `_NAV_BUTTON_STYLE` had -
    # matches this tab's own 2026-07-20 kiosk legibility pass (every other pill here is 16px)
    # now that this section lives here instead of Settings.
    "name": [{"color": "white"}, {"font-weight": "600"}, {"font-size": "16px"}],
}

_MANAGE_FIELD_PILL_STYLE = {
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
        # 16px, not 13px - same legibility-pass reasoning as _MANAGE_NAV_BUTTON_STYLE above.
        {"font-size": "16px"},
        {"font-weight": "600"},
        {"padding-left": "4px"},
        {"white-space": "nowrap"},
    ],
}


def _manage_nav_button(name: str, icon: str, hash_suffix: str) -> dict:
    """Opens a Chores & Rewards management popup (Add Chore/Add Reward) - same visual shape
    as `async_change_pin_button` above, kept as a small local copy over a cross-module
    import since it's just markup (this codebase's established convention, e.g.
    `_avatar_header`'s own duplication between this file and `modules/settings/dashboard.py`).
    """
    return {
        "type": "custom:button-card",
        "name": name,
        "icon": icon,
        "show_name": True,
        "show_icon": True,
        "tap_action": {"action": "navigate", "navigation_path": f"#{hash_suffix}"},
        "styles": _MANAGE_NAV_BUTTON_STYLE,
    }


def _field_pill(label: str, entity_id: str | None) -> dict:
    """A generic "<Label>: <value>" pill opening the entity's own native more-info dialog -
    used for chore/reward fields (name/points-or-cost/frequency/assigned-to). `entity_id` can
    be `None` before the platform has forwarded - degrades gracefully instead of crashing."""
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
        "styles": _MANAGE_FIELD_PILL_STYLE,
    }


def _manage_delete_tile(entity_id: str | None, item_name: str) -> dict:
    """Genuinely deletes a chore/reward (`family_dashboard.delete_task` - see `crud.py`'s
    module docstring for why this is a real removal, not `hidden_by`) - gated behind a native
    Lovelace `confirmation:` prompt (stock tap_action feature, no custom popup needed) since
    there's no undo. Now doubly-gated in practice: this whole card only renders once the
    Parent PIN is unlocked (see `async_chores_rewards_management_card`)."""
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
                {"font-size": "16px"},
                {"font-weight": "600"},
                {"padding-left": "4px"},
            ],
        },
    }


def _schedule_pill(chore: dict, chore_id: str) -> dict:
    """Like `_field_pill`, but for `schedule_days` - there's no single entity holding this
    value to open a native more-info dialog on (it's derived from `entry.data`, not backed by
    its own per-chore entity), so this navigates to the `#schedule-{chore_id}` edit popup
    instead, same reasoning `modules/settings/dashboard.py`'s birthdate pill already
    established for a field with no natural entity of its own."""
    return {
        "type": "custom:button-card",
        "show_name": True,
        "show_icon": False,
        "name": f"Schedule: {format_schedule_days(chore.get('schedule_days'))}",
        "tap_action": {"action": "navigate", "navigation_path": f"#schedule-{chore_id}"},
        "styles": _MANAGE_FIELD_PILL_STYLE,
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
            _schedule_pill(chore, chore_id),
            _manage_delete_tile(sensor_id, chore["name"]),
        ],
    }


def _schedule_edit_popup(ent_reg, entry: ConfigEntry, chore: dict) -> dict:
    """Save button calls `family_dashboard.set_chore_schedule_days` targeted at THIS chore's
    own task sensor (same per-row targeting `_manage_delete_tile` already does), reading the
    SHARED `ChoreScheduleScratchText` scratch field (only one such popup is ever open at a
    time - see that entity's own docstring)."""
    chore_id = chore["chore_id"]
    scratch_id = ent_reg.async_get_entity_id("text", DOMAIN, _schedule_scratch_unique_id(entry)) or ""
    sensor_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{chore_id}_chore") or ""
    return {
        "type": "custom:bubble-card",
        "card_type": "pop-up",
        "hash": f"#schedule-{chore_id}",
        "name": f"{chore['name']} Schedule",
        "icon": "mdi:calendar-week",
        "cards": [
            {
                "type": "markdown",
                "content": (
                    "Comma-separated days - Mon, Tue, Wed, Thu, Fri, Sat, Sun - or leave "
                    "blank for every day."
                ),
            },
            {"type": "entities", "entities": [{"entity": scratch_id, "name": "Days"}], "show_header_toggle": False},
            {
                "type": "button",
                "name": "Save",
                "icon": "mdi:content-save",
                "tap_action": {
                    "action": "perform-action",
                    "perform_action": "family_dashboard.set_chore_schedule_days",
                    "target": {"entity_id": sensor_id},
                },
            },
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
            _manage_delete_tile(sensor_id, reward["name"]),
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
    schedule_id = ent_reg.async_get_entity_id("text", DOMAIN, f"{entry.entry_id}_new_chore_schedule") or ""
    return _add_item_popup(
        hash_suffix="addchore",
        title="Add Chore",
        icon="mdi:broom",
        entities=[
            {"entity": name_id, "name": "Name"},
            {"entity": points_id, "name": "Points"},
            {"entity": frequency_id, "name": "Frequency"},
            {"entity": assigned_id, "name": "Assigned To"},
            {"entity": schedule_id, "name": "Schedule (optional - blank = every day)"},
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


async def async_chores_rewards_management_card(
    hass: HomeAssistant, entry: ConfigEntry, chores_members: list[dict]
) -> dict:
    """Add Chore/Add Reward + one editable row per existing chore/reward (including
    Unassigned ones, which have no per-kid column to live in otherwise - see
    `_member_task_cards`) + Delete. Moved here from `modules/settings/dashboard.py`
    (2026-07-20, live-reported gap: that location was Kiosk-only but had NO Parent PIN gate
    at all, so any kid could add/reassign/repoint/delete chores and rewards) - same PIN gate
    as `async_parent_review_card`, appended right after it in `async_kiosk_chores_cards` so
    review and management live in the same locked section, matching the user's own framing
    ("these should fall under the Parent Review section")."""
    ent_reg = er.async_get(hass)
    cards: list[dict] = [
        {"type": "markdown", "content": "## Manage Chores & Rewards"},
        {
            "type": "horizontal-stack",
            "cards": [
                _manage_nav_button("Add Chore", "mdi:broom", "addchore"),
                _manage_nav_button("Add Reward", "mdi:gift", "addreward"),
            ],
        },
    ]
    for chore in entry.data.get(CONF_CHORES, []):
        cards.append(_chore_row(ent_reg, entry, chore))
        cards.append(_schedule_edit_popup(ent_reg, entry, chore))
    for reward in entry.data.get(CONF_REWARDS, []):
        cards.append(_reward_row(ent_reg, entry, reward))
    cards.append(_add_chore_popup(ent_reg, entry))
    cards.append(_add_reward_popup(ent_reg, entry))

    return {
        "type": "conditional",
        "conditions": [{"entity": "binary_sensor.family_dashboard_parent_mode", "state": "on"}],
        "card": {"type": "vertical-stack", "cards": cards},
    }


async def async_kiosk_chores_cards(
    hass: HomeAssistant, entry: ConfigEntry, chores_members: list[dict]
) -> list[dict]:
    """The Kiosk bucket's full Chores tab content: toggle-filter pills, per-kid columns
    (each hidden/shown by its own switch), the Parent lock control, the inline Review
    section, the Chores & Rewards management section (Add/edit/delete - moved here from
    Settings 2026-07-20, see `async_chores_rewards_management_card`), and the PIN pop-up.
    Returns an empty list if nobody has chores enabled - the caller shows a fallback card
    instead.
    """
    if not chores_members:
        return []

    pills = [
        member_avatar_toggle_pill(member, _shown_switch_entity_id(member["member_id"]))
        for member in chores_members
    ]

    # Parent lock BEFORE the toggle pills (live-reported ordering fix), and wrapped in its
    # own horizontal-stack rather than left as a bare top-level card - a `type: sections` grid
    # cell stretches a bare card to the row's full height, but a horizontal-stack sizes to its
    # tallest child's own declared height instead (the same reason the toggle-pill row below
    # renders at its correct 52px rather than stretched taller - live-verified height
    # mismatch between the two, both declaring identical `height: 52px` in their own styles).
    cards: list[dict] = [
        {"type": "horizontal-stack", "cards": [async_parent_lock_card()]},
        {"type": "horizontal-stack", "cards": pills},
    ]

    # Every kid's column side by side in ONE horizontal-stack (matches `Chores - 1.png`'s
    # mockup layout) rather than each kid's content as a separate full-width card stacking
    # vertically one after another - a live-reported layout gap, not a stylistic preference.
    member_columns = []
    for member in chores_members:
        member_cards = await _member_task_cards(hass, entry, member)
        if not member_cards:
            continue
        member_columns.append(
            {
                "type": "conditional",
                "conditions": [
                    {"entity": _shown_switch_entity_id(member["member_id"]), "state": "on"}
                ],
                "card": {
                    "type": "vertical-stack",
                    "cards": [_avatar_header(member), *member_cards],
                },
            }
        )
    if member_columns:
        cards.append({"type": "horizontal-stack", "cards": member_columns})

    cards.append(await async_parent_review_card(hass, entry, chores_members))
    cards.append(await async_chores_rewards_management_card(hass, entry, chores_members))
    cards.append(async_pin_popup_card())
    return cards


def async_change_pin_button() -> dict:
    """Opens the PIN-change pop-up (see async_pin_change_popup_card) - lives on the Settings
    tab, next to the Parent PIN's raw editable field (see modules/settings/dashboard.py)."""
    return {
        "type": "custom:button-card",
        "name": "Change Parent PIN",
        "icon": "mdi:lock-reset",
        "show_name": True,
        "show_icon": True,
        "tap_action": {"action": "navigate", "navigation_path": "#pinchange"},
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
            # 13px -> 16px (2026-07-20 kiosk legibility pass) - see registry.py's
            # `_pill_styles` for why.
            "name": [{"color": "white"}, {"font-weight": "600"}, {"font-size": "16px"}],
        },
    }


def async_pin_change_popup_card() -> dict:
    """The PIN-change flow's pop-up: verify the old PIN, then (once the 60-second authorized
    window opens) enter and save a new one. Two-phase content via `type: conditional` on
    `binary_sensor.family_dashboard_pin_change_authorized`, reusing the same digit-button/
    clear-button/masked-display building blocks as the unlock pop-up (see
    `async_pin_popup_card`) but with `append_pin_digit_raw` (no auto-submit - a new PIN isn't
    a fixed 4 digits) and explicit Verify/Save buttons instead.
    """
    authorized = "binary_sensor.family_dashboard_pin_change_authorized"
    digit_grid = [_pin_digit_button(str(n), service="family_dashboard.append_pin_digit_raw") for n in range(1, 10)]
    digit_grid += [
        _pin_clear_button(),
        _pin_digit_button("0", service="family_dashboard.append_pin_digit_raw"),
    ]
    masked_display = {
        "type": "markdown",
        "content": (
            "<div style='text-align:center;font-size:30px;letter-spacing:8px;height:36px;'>"
            "{{ '●' * (states('text.family_dashboard_pin_entry')|length) }}</div>"
        ),
        "card_mod": {
            "style": "ha-card{background:transparent !important;box-shadow:none !important;border:none !important;}"
        },
    }
    numpad_grid = {"type": "grid", "columns": 3, "square": False, "cards": digit_grid}

    return {
        "type": "custom:bubble-card",
        "card_type": "pop-up",
        "hash": "#pinchange",
        "name": "Change Parent PIN",
        "icon": "mdi:lock-reset",
        "cards": [
            {
                "type": "conditional",
                "conditions": [{"entity": authorized, "state": "off"}],
                "card": {
                    "type": "vertical-stack",
                    "cards": [
                        {"type": "markdown", "content": "Enter the **current** PIN, then Verify."},
                        masked_display,
                        numpad_grid,
                        {
                            "type": "button",
                            "name": "Verify",
                            "icon": "mdi:lock-question",
                            "tap_action": {
                                "action": "perform-action",
                                "perform_action": "family_dashboard.verify_old_pin",
                                "target": {"entity_id": "text.family_dashboard_pin_entry"},
                            },
                        },
                    ],
                },
            },
            {
                "type": "conditional",
                "conditions": [{"entity": authorized, "state": "on"}],
                "card": {
                    "type": "vertical-stack",
                    "cards": [
                        {"type": "markdown", "content": "Enter the **new** PIN (3-8 digits), then Save."},
                        masked_display,
                        numpad_grid,
                        {
                            "type": "button",
                            "name": "Save",
                            "icon": "mdi:content-save-lock",
                            "tap_action": {
                                "action": "perform-action",
                                "perform_action": "family_dashboard.save_new_pin",
                                "target": {"entity_id": "text.family_dashboard_pin_entry"},
                            },
                        },
                    ],
                },
            },
        ],
    }
