"""Dashboard template + registry system - assembles the multi-view Lovelace config from each
module's dashboard-template contribution function.

CORRECTED ARCHITECTURE (2026-07-13, replacing an earlier build that literally named views
after roster members - "Everyone"/"Ada"/"Grace" as nav destinations. That was wrong and is
NOT what the rebuild plan's principle 9 or the Code Mockup reference app actually specify):

Dashboard nav is always exactly **four uniformly-labeled tabs - Calendar, Lists, Chores,
Settings - the same for every viewer.** Nobody ever sees a person's name in the nav. What
varies per viewer is the CONTENT inside each tab, not the tabs themselves.

Mechanically, since a Lovelace view's cards are static and can't change based on who's
viewing, this still requires generating one Lovelace view per (viewer-bucket, tab) pair under
the hood - `_build_viewer_buckets` computes a **Kiosk bucket** (every active,
non-system-generated HA user - `hass.auth.async_get_users()`, same filter
`config_flow.py`'s `link_users` step already uses - minus every roster member's linked
`ha_user_id`; this includes any admin account not specifically added to the roster) plus one
bucket per HA-user-linked roster member. Every bucket's Calendar/Lists/Chores/Settings views are `visibility`-restricted to that
bucket's user IDs and ALL use the exact same title/icon per tab across every bucket - the
multi-view-per-bucket structure is an invisible implementation detail, never a "pick your
view" UI. Settings' CONTENT is identical across every bucket (see
`modules/settings/dashboard.py`) - it's still generated once per bucket, not truly shared,
purely so each bucket's own Settings view has a self-consistent nav row pointing back at
THAT bucket's Calendar/Lists/Chores (a single shared view has no way to know which bucket its
own nav pills should target).

Per-tab content by bucket (see the rebuild plan's "Decided" section for the full reasoning):
- Calendar: Kiosk overlays every calendar-mapped member with interactive toggle-filter pills
  (`modules/calendar/dashboard.py`'s `async_kiosk_calendar_card`); a linked member's bucket
  shows just their own calendar plus the shared Family calendar (if any), fixed - no
  per-member toggle pills to show/hide. Both bucket kinds' grids are fixed to a full-month
  view (no view-switcher control - removed 2026-07-25, see `modules/calendar/dashboard.py`'s
  docstring) and DO share the same Family toggle pill (`async_family_calendar_toggle_pill`) -
  a config-entry-scoped entity, not per-viewer, so toggling it in either bucket moves the
  other too. Birthdays/Holidays are always shown in both buckets with no toggle at all
  (2026-07-25, see `modules/calendar/dashboard.py`'s `_overlay_entries` docstring).
- Lists: Kiosk shows every member's lists under a per-member header; a linked member's bucket
  shows just their own, no header.
- Chores: Kiosk shows every kid's chores/rewards with the same kind of toggle-filter pills,
  plus the Parent lock/unlock control and (once unlocked) an inline Review section - gated by
  the household Parent PIN regardless of which bucket is looking, not by identity. A linked
  member's bucket shows just their own chores/rewards, no toggle, no Parent controls.

Stated plainly rather than glossed over: view `visibility` hides a view from the nav bar, it
is not a hard access-control boundary - someone with the exact view URL could still open it.
Accepted, documented tradeoff (rebuild plan architecture principle 9), not a bug to fix.

Each module's dashboard-contribution function is called once per linked member (for their
personal bucket) and once more aggregated across all opted-in members (for the Kiosk bucket) -
this file handles bucket/tab assembly and uniform nav labeling; modules don't implement their
own multi-bucket logic.
"""
from __future__ import annotations

import dataclasses

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import (
    CONF_DISABLED,
    CONF_FEATURES,
    CONF_HA_USER_ID,
    CONF_ROSTER,
)
from ..modules.calendar.dashboard import (
    async_add_event_button,
    async_add_event_popup_card,
    async_calendar_view_card,
    async_family_calendar_toggle_pill,
    async_kiosk_calendar_card,
    async_member_toggle_pills,
)
from ..modules.chores.dashboard import async_chores_cards_for_member, async_kiosk_chores_cards
from ..modules.lists.dashboard import async_lists_cards_for_member
from ..modules.settings.dashboard import async_settings_view_cards

_NO_CALENDARS_CARD = {
    "type": "markdown",
    "content": "No calendars are mapped yet. Re-run the Family Dashboard setup wizard to map one.",
}

_NO_LISTS_CARD = {
    "type": "markdown",
    "content": "No lists are set up yet. Re-run the Family Dashboard setup wizard to add some.",
}

_NO_CHORES_CARD = {
    "type": "markdown",
    "content": "No chores are set up yet. Re-run the Family Dashboard setup wizard to add some.",
}

_TABS = ("calendar", "lists", "chores")
_TAB_TITLES = {"calendar": "Calendar", "lists": "Lists", "chores": "Chores"}
_TAB_ICONS = {"calendar": "mdi:calendar-heart", "lists": "mdi:clipboard-list", "chores": "mdi:trophy"}

# Ported forward from the legacy dashboard's own per-view background block (2026-07-13
# feature audit) - `assets.py` seeds this file to /config/www/family_dashboard/background.png
# on first setup; `/local/` is HA frontend's standard alias for /config/www/.
_VIEW_BACKGROUND = {
    "image": "/local/family_dashboard/background.png",
    "alignment": "center",
    "size": "cover",
    "opacity": 100,
}

_MAX_COLUMNS = 4

# Must match themes/family_dashboard.yaml's own top-level key exactly. Set on EVERY view
# individually (`_build_view`), not just once at the dashboard's own top level - live-verified
# real bug (2026-07-25): this dashboard uses a custom client-side STRATEGY
# (`www/family-dashboard-strategy.js`), and a strategy's return value becomes the entire
# resolved dashboard config, not a patch merged onto the stored one. The strategy already
# forwards `views` unmodified, so a per-view theme survives that resolution even though the
# dashboard-level `theme` key (also still set below, harmless, matches what "Manage
# dashboards" shows) empirically does not - confirmed by checking computed styles in a real
# browser (`--primary-font-family` was empty and zero requests to Google Fonts fired) both
# before AND after passing `theme` through the strategy's own return value, so the fix had to
# be per-view instead, not just forwarding the key through the strategy.
_THEME_NAME = "Family Dashboard"


def _build_view(
    title: str, path: str, cards: list[dict], user_ids: list[str], *, subview: bool = True
) -> dict:
    """Every generated view, in the legacy dashboard's own proven `type: sections` layout
    strategy (`REPO/ha-family-hub/dashboards/family-hub.yaml` - every one of its views uses
    `type: sections` + `max_columns`, cards live inside `sections: [...]`, not a flat
    top-level `cards:` list). An earlier version of this file used the classic default
    "masonry" layout (no `type` key at all) - live-verified (not assumed) that this produces
    exactly the chaotic auto-flowed card positioning the user reported ("screen hopping all
    over the place"), and that `background:` may not render reliably under masonry either
    (both the legacy example and this integration's own working case pair `background:` with
    `type: sections`). Cards get `grid_options: {columns: "full"}` here in one place rather
    than in every individual card-building function scattered across `modules/*/dashboard.py`
    - none of them set their own `grid_options`, so this is a safe uniform default (everything
    stacks full-width, one after another, matching this dashboard's single-column content
    shape - unlike the legacy's fancier multi-card-per-row sections).

    `subview: True` (the Kiosk bucket's default) removes this view from HA's own native
    per-view tab strip. The Kiosk device always runs with HA's own sidebar/header chrome
    hidden (kiosk browser mode), so the custom `_nav_row` pills are its ONLY navigation and
    the native strip must stay suppressed there. A personal (linked-member) bucket's views
    pass `subview=False` instead and rely on the native tab strip - explicit user requirement:
    Companion App users need real native tabs, not a custom pill row (which renders a
    "back-arrow to parent" sub-page treatment when combined with `subview: True`, and looks
    sloppy on what should be a clean top-level view). A real duplicate-tabs bug WAS found live
    for this path (see the project's own memory/notes for the investigation) - the fix for
    that is native-`visibility` correctness, not abandoning native tabs for personal buckets.
    """
    for card in cards:
        card.setdefault("grid_options", {"columns": "full"})
    return {
        "title": title,
        "path": path,
        "type": "sections",
        "max_columns": _MAX_COLUMNS,
        "subview": subview,
        "theme": _THEME_NAME,
        "sections": [{"type": "grid", "column_span": _MAX_COLUMNS, "cards": cards}],
        "background": _VIEW_BACKGROUND,
        # View visibility hides a view from the nav bar; it is NOT a hard access-control
        # boundary - someone with the exact view URL could still open it. Accepted,
        # documented tradeoff (rebuild plan architecture principle 9), not a bug.
        "visibility": [{"condition": "user", "users": user_ids}],
    }


@dataclasses.dataclass
class _Bucket:
    """One viewer bucket - either the Kiosk/unlinked-login aggregate, or a single
    HA-user-linked roster member. `key` is the internal view-path suffix (never shown in the
    UI - nav pill labels are the uniform tab names, not this)."""

    key: str
    user_ids: list[str]
    member: dict | None


async def async_compute_kiosk_user_ids(hass: HomeAssistant, roster: list[dict]) -> frozenset[str]:
    """The Kiosk bucket's user-ID set: every active, non-system-generated HA user not already
    linked to a roster member (see this module's own docstring's "Kiosk bucket" paragraph).
    Factored out of `_build_viewer_buckets` so `user_watch.py` can cheaply recompute just this
    set to check whether an HA user-registry change actually affects the dashboard, without
    rebuilding the whole multi-view config to find out. Returns a `frozenset` (hashable,
    stable equality) rather than a list, since the only thing callers outside this module do
    with it is compare it against a previous snapshot.
    """
    linked_user_ids = {m[CONF_HA_USER_ID] for m in roster if m.get(CONF_HA_USER_ID)}
    users = await hass.auth.async_get_users()
    return frozenset(
        user.id
        for user in users
        if user.is_active and not user.system_generated and user.id not in linked_user_ids
    )


async def _build_viewer_buckets(hass: HomeAssistant, roster: list[dict]) -> list[_Bucket]:
    linked_members = [m for m in roster if m.get(CONF_HA_USER_ID)]
    kiosk_user_ids = list(await async_compute_kiosk_user_ids(hass, roster))

    buckets = []
    if kiosk_user_ids:
        buckets.append(_Bucket(key="kiosk", user_ids=kiosk_user_ids, member=None))
    buckets.extend(
        _Bucket(key=member["member_id"], user_ids=[member[CONF_HA_USER_ID]], member=member)
        for member in linked_members
    )
    return buckets


_NAV_PILL_WIDTH = "160px"


def _pill_styles(is_current: bool) -> dict:
    """Shared button-card styling for every Kiosk nav pill (tab links AND the Home pill) -
    factored out so `_nav_pill`/`_home_pill` can't visually drift apart from each other.

    Fixed `width` here, paired with `_nav_row`'s `card_mod` override of `horizontal-stack`'s
    own default `flex: 1 1 0%` child styling - without that override, `horizontal-stack`
    stretches every child to equally fill the row regardless of a card's own configured
    width (live-verified: a 2-pill row split 50/50 across the full row width, each pill far
    wider than its content needed). Explicit user requirement: nav pills should be a fixed,
    uniform size and left-justified, not stretched to fill the row.
    """
    return {
        "card": [
            {"border-radius": "26px"},
            {"height": "52px"},
            {"width": _NAV_PILL_WIDTH},
            {"padding": "4px 14px 4px 6px"},
            {"box-shadow": "none"},
            {"background-color": "#1a2235" if is_current else "#e6e6e6"},
        ],
        "grid": [
            {"grid-template-areas": "'i n'"},
            {"grid-template-columns": "42px auto"},
            {"align-items": "center"},
            {"justify-items": "start"},
        ],
        "icon": [{"width": "30px"}, {"color": "white" if is_current else "#8a8a8a"}],
        "name": [
            {"color": "white" if is_current else "#555"},
            # 13px -> 16px (2026-07-20 kiosk legibility pass): the primary nav row's own
            # 52px-tall pill made this look disproportionately small on a 1920x1080 15"
            # kiosk panel - every other "52px pill, tiny name text" spot across Calendar/
            # Chores got the same bump, see modules/calendar/dashboard.py's
            # `_toggle_pill_base_styles`/`_nav_style_button` and modules/chores/dashboard.py's
            # parent-lock/PIN-change buttons.
            {"font-size": "16px"},
            {"font-weight": "600"},
            {"padding-left": "4px"},
            {"white-space": "nowrap"},
        ],
    }


def _nav_pill(tab: str, bucket_key: str, current_tab: str) -> dict:
    """A single button-card nav pill linking to one of the four uniform tabs. Unlike the
    reverted per-person design, there is no per-viewer color here - just current-vs-not,
    since these labels ("Calendar"/"Lists"/"Chores"/"Settings") are identical for every
    bucket.
    """
    is_current = tab == current_tab
    path = f"{tab}-{bucket_key}"
    return {
        "type": "custom:button-card",
        "name": "Settings" if tab == "settings" else _TAB_TITLES[tab],
        "icon": "mdi:cog" if tab == "settings" else _TAB_ICONS[tab],
        "show_name": True,
        "show_icon": True,
        "tap_action": {"action": "navigate", "navigation_path": f"/family-dashboard/{path}"},
        "styles": _pill_styles(is_current),
    }


def _home_pill() -> dict:
    """Kiosk-only Home button - navigates to the Kiosk device's own separate root dashboard
    (`/dashboard-home/home`, a fixed external path outside this integration entirely, given
    explicitly by the user - not something this dashboard generates or validates). Always the
    first pill in every Kiosk nav row - see `_nav_row`'s own docstring for the full
    hub-and-spoke design this is part of."""
    return {
        "type": "custom:button-card",
        "name": "Home",
        "icon": "mdi:home",
        "show_name": True,
        "show_icon": True,
        "tap_action": {"action": "navigate", "navigation_path": "/dashboard-home/home"},
        "styles": _pill_styles(False),
    }


def _nav_row(bucket_key: str, current_tab: str) -> dict:
    """Kiosk-only hub nav row, hub-and-spoke with Calendar as the hub - explicit user
    requirement, matching `Family Dashboard - Main.jpg`'s own kiosk photo. Always its OWN row,
    on top, separate from Calendar's own controls (toggle pills/Add Event/view selector - see
    `_calendar_controls_row`) - an earlier version merged the two into one row, but that row's
    width grows with roster size (one toggle pill per calendar-mapped member) while this row
    is always exactly 2-4 fixed items, so merging them let a large roster push the hub links
    into label-truncated illegibility. Splitting them keeps the hub row a fixed, always-legible
    size regardless of roster size or viewport width - explicit user correction after live
    truncation was observed with a many-member roster on this row.

    FROM Calendar: Home, then links to Lists/Chores/Settings.

    FROM any OTHER tab (Lists/Chores/Settings): just Home + a way back to Calendar - the
    other two tabs are deliberately NOT shown ("when on Lists, Chores and Settings should not
    appear", and the same pattern for Chores/Settings) - Calendar is the only hub, every
    other tab is a dead-end you back out of via Home or Calendar, never directly to a sibling
    tab.
    """
    home = _home_pill()
    if current_tab == "calendar":
        other_tabs = [_nav_pill(t, bucket_key, current_tab) for t in ("lists", "chores", "settings")]
        cards = [home, *other_tabs]
    else:
        cards = [home, _nav_pill("calendar", bucket_key, current_tab)]
    return {
        "type": "horizontal-stack",
        "cards": cards,
        # Defeats horizontal-stack's own default child-stretch rule. Two earlier guesses at
        # the right selector (`.card`, then `:host > *`) each produced ZERO visible change
        # live - live DOM inspection (via a real logged-in Playwright session walking
        # `element.parentElement`/computed styles from the "Home" pill outward) was needed to
        # find the truth: the stretch (`flex: 1 1 0px`, computed) lands on the `<button-card>`
        # element itself, nested one level deeper than `:host`'s direct children (there's a
        # `<hui-card>` wrapper in between). Targeting every descendant inside this row's own
        # shadow root is what actually reaches it, regardless of exact wrapper depth.
        # Left-justified is `justify-content`'s own default once stretch is gone.
        "card_mod": {"style": "* { flex: none !important; }"},
    }


def _calendar_controls_row(extra_pills: list[dict]) -> dict | None:
    """Calendar's own controls (member/Birthdays/Holidays toggle pills, Add Event, view
    selector) - a separate row below `_nav_row`'s fixed hub row (see that function's own
    docstring for why they're no longer merged into one row). Returns `None` when there are no
    controls to show (no calendar-enabled members), so the caller can omit an empty row
    entirely."""
    if not extra_pills:
        return None
    return {"type": "horizontal-stack", "cards": extra_pills}


def _any_calendar_enabled(roster: list[dict]) -> bool:
    """Whether ANY roster member has "calendar" enabled - the view-selector/Add Event/
    Birthdays-Holidays controls all reference entities from Calendar's conditionally-
    forwarded platforms (see const.py's FEATURES["calendar"]["platforms"]), which don't
    exist at all if nobody opted in. Live-verified this gap via a real browser console
    `ButtonCardJSTemplateError: Cannot read properties of undefined (reading 'state')` on a
    roster where neither member had calendar enabled - the Calendar TAB itself always
    exists (one of the four uniform tabs), but its controls must degrade gracefully when
    there's nothing calendar-related to control.
    """
    return any("calendar" in m.get(CONF_FEATURES, []) for m in roster)


async def _kiosk_calendar_cards(
    hass: HomeAssistant, entry: ConfigEntry, roster: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Returns `(controls_row_pills, content_cards)` - the toggle pills/Add Event controls go
    into their OWN row below the fixed Home/Lists/Chores/Settings hub row (see
    `_nav_row`/`_calendar_controls_row`), decoupled so the hub row's width never depends on
    roster size. Pill order (member toggles, then Family, then Add Event) matches
    `Family Dashboard - Main.jpg`'s own left-to-right order for these controls.
    """
    if not _any_calendar_enabled(roster):
        return [], [_NO_CALENDARS_CARD]

    extra_pills = [
        *async_member_toggle_pills(roster),
        *async_family_calendar_toggle_pill(hass),
        async_add_event_button(),
    ]
    card = async_kiosk_calendar_card(hass, roster)
    grid = [card] if card else [_NO_CALENDARS_CARD]
    return extra_pills, [*grid, async_add_event_popup_card()]


async def _personal_calendar_cards(
    hass: HomeAssistant, entry: ConfigEntry, member: dict
) -> list[dict]:
    if not _any_calendar_enabled(entry.data[CONF_ROSTER]):
        return [_NO_CALENDARS_CARD]

    # The Family calendar (if any) is added automatically by `async_calendar_view_card`
    # itself via `_overlay_entries` - no member lookup needed, unlike the earlier design where
    # one flagged roster member's own mapping had to be passed through explicitly.
    card = await async_calendar_view_card(hass, entry, [member])
    grid = [card] if card else [_NO_CALENDARS_CARD]
    # Add Event + Family toggle pill (Birthdays/Holidays are always shown here too, but have
    # no pill to add - see `_overlay_entries`'s docstring), same shared switch the Kiosk
    # bucket's own controls row uses.
    controls_row = {
        "type": "horizontal-stack",
        "cards": [
            async_add_event_button(),
            *async_family_calendar_toggle_pill(hass),
        ],
    }
    return [controls_row, *grid, async_add_event_popup_card()]


def _avatar_header(member: dict, suffix: str) -> dict:
    """The member's live avatar image + a header label. NOT a markdown card with a raw
    `<img>` tag, after two live-verified failed attempts at that approach: (1) HA's markdown
    card strips inline `style=` attributes from rendered HTML entirely
    (`img.getAttribute('style')` came back `null`), leaving the seeded 640x640 avatar PNGs at
    native size - a real "ridiculously large" bug; (2) a `card_mod.style` fix for that (even
    using card_mod's documented shadow-piercing `"<selector>$"` syntax) still didn't reach the
    actual `<img>`, which a live shadow-DOM host-chain trace showed sitting inside
    `ha-markdown-element`'s own nested shadow root - two boundaries deep, and unreliable to
    keep chasing. Switched to `custom:button-card`'s `custom_fields.pic` mechanism instead -
    the exact same avatar-image technique already proven reliable and correctly-sized
    elsewhere this session (`modules/calendar/dashboard.py`'s `member_avatar_toggle_pill`),
    since button-card doesn't sanitize its custom-field HTML the way markdown does.
    """
    avatar_entity = f"select.family_dashboard_{member['member_id']}_avatar"
    return {
        "type": "custom:button-card",
        "show_name": True,
        "show_icon": False,
        "name": f"{member['name']}{suffix}",
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


async def _kiosk_lists_cards(hass: HomeAssistant, entry: ConfigEntry, roster: list[dict]) -> list[dict]:
    """Every member's lists side by side in ONE horizontal-stack (matches Chores' own
    side-by-side column layout, a live-reported gap this mirrors) rather than each member's
    content as a separate full-width block stacking vertically one after another."""
    columns: list[dict] = []
    for member in roster:
        member_cards = await async_lists_cards_for_member(hass, entry, member)
        if member_cards:
            columns.append(
                {
                    "type": "vertical-stack",
                    "cards": [_avatar_header(member, "'s Lists"), *member_cards],
                }
            )
    if not columns:
        return [_NO_LISTS_CARD]
    return [{"type": "horizontal-stack", "cards": columns}]


async def _kiosk_chores_cards(hass: HomeAssistant, entry: ConfigEntry, roster: list[dict]) -> list[dict]:
    chores_members = [m for m in roster if "chores" in m.get(CONF_FEATURES, [])]
    cards = await async_kiosk_chores_cards(hass, entry, chores_members)
    return cards or [_NO_CHORES_CARD]


async def async_build_dashboard_config(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    roster = entry.data[CONF_ROSTER]
    # A disabled member (roster.py's async_set_member_disabled) must disappear from every
    # bucket-facing part of the dashboard - Kiosk's per-member columns/pills and their own
    # personal bucket (which also frees their linked HA account to fall back into Kiosk, same
    # as any never-linked account - see roster.py's own module docstring). Settings
    # intentionally does NOT use this filtered list - it reads the FULL roster straight from
    # entry.data itself (async_settings_view_cards), since a disabled member must stay visible
    # there to be re-enabled or deleted at all.
    active_roster = [m for m in roster if not m.get(CONF_DISABLED)]

    buckets = await _build_viewer_buckets(hass, active_roster)

    views: list[dict] = []
    for bucket in buckets:
        is_kiosk = bucket.member is None
        for tab in _TABS:
            # Kiosk-only nav-pill row - explicit user requirement: the Kiosk device has no
            # sidebar/header chrome, so the custom pills are its only navigation. Personal
            # (linked-member) buckets keep HA's own native tab strip instead - Companion App
            # users need real native tabs, not a custom pill row (which reads as a sloppy
            # "back-arrow to parent" sub-page treatment when paired with `subview: True`).
            if is_kiosk and tab == "calendar":
                # Calendar's own controls (toggle pills/Add Event/view selector) get their own
                # row below the fixed hub row - see `_nav_row`'s own docstring for why they're
                # no longer merged into one row.
                extra_pills, content = await _kiosk_calendar_cards(hass, entry, active_roster)
                controls_row = _calendar_controls_row(extra_pills)
                cards = [_nav_row(bucket.key, tab), *([controls_row] if controls_row else []), *content]
            elif is_kiosk:
                cards = [_nav_row(bucket.key, tab)]
                if tab == "lists":
                    cards.extend(await _kiosk_lists_cards(hass, entry, active_roster))
                else:  # chores
                    cards.extend(await _kiosk_chores_cards(hass, entry, active_roster))
            else:
                cards = []
                if tab == "calendar":
                    cards.extend(await _personal_calendar_cards(hass, entry, bucket.member))
                elif tab == "lists":
                    member_cards = await async_lists_cards_for_member(hass, entry, bucket.member)
                    cards.extend(member_cards or [_NO_LISTS_CARD])
                else:  # chores
                    member_cards = await async_chores_cards_for_member(hass, entry, bucket.member)
                    cards.extend(member_cards or [_NO_CHORES_CARD])

            views.append(
                _build_view(
                    _TAB_TITLES[tab],
                    f"{tab}-{bucket.key}",
                    cards,
                    bucket.user_ids,
                    subview=is_kiosk,
                )
            )

    # Settings: generated once PER BUCKET, both because a single shared view has no way to
    # know which bucket its OWN nav row's Calendar/Lists/Chores pills should point back at
    # (Lovelace views can't branch content by viewer without per-card visibility, which this
    # design deliberately avoids relying on - see the module docstring), AND because content
    # itself now differs per bucket too: Kiosk still sees/can-adjust every member's own
    # Name/Color/Avatar settings (matches its "sees/can-adjust everything" role everywhere
    # else), but a linked member's own bucket only shows THEIR OWN settings, not another
    # family member's - explicit user requirement, a real access gap the earlier
    # identical-content-for-everyone design left open.
    for bucket in buckets:
        is_kiosk = bucket.member is None
        nav = [_nav_row(bucket.key, "settings")] if is_kiosk else []
        settings_cards = await async_settings_view_cards(hass, entry, only_member=bucket.member)
        views.append(
            _build_view(
                "Settings",
                f"settings-{bucket.key}",
                [*nav, *settings_cards],
                bucket.user_ids,
                subview=is_kiosk,
            )
        )

    # A dashboard STRATEGY, not a flat `views:` list - see `www/family-dashboard-strategy.js`'s
    # own module docstring for the full "why" (a real, live-confirmed bug: HA's native
    # per-view tab strip does not consult `visibility` at all, so a flat shared views list
    # always let every linked member's tabs leak into every OTHER viewer's tab strip). The
    # strategy runs client-side, per viewer, and picks which of these already-fully-built
    # views (unchanged from before - all card/content generation above is untouched) to
    # actually hand to HA, using `user_bucket_map` to resolve the CURRENT viewer's own bucket.
    user_bucket_map = {uid: bucket.key for bucket in buckets for uid in bucket.user_ids}
    return {
        "title": "Family Dashboard",
        "theme": _THEME_NAME,
        "strategy": {
            "type": "custom:family-dashboard",
            "title": "Family Dashboard",
            "views": views,
            "user_bucket_map": user_bucket_map,
            "kiosk_key": "kiosk",
        },
    }
