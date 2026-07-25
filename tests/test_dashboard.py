"""Tests for dashboard generation/registration under the corrected architecture: nav is
always exactly four uniformly-titled tabs (Calendar/Lists/Chores/Settings) - never a person's
name - with one Lovelace view per (viewer-bucket, tab) pair underneath. Covers: the Kiosk
bucket (every active non-system HA user minus linked ones) gets every member's content plus
real toggle-filter switches; a linked member's bucket gets only their own content (+ the
shared Family calendar); every bucket's four view titles are identical; visibility allowlists
are computed correctly from real HA user accounts; and that registration is REAL (not mocked)
and idempotent.
"""
from __future__ import annotations

from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_dashboard.const import DOMAIN
from custom_components.family_dashboard.dashboard.register import (
    DASHBOARD_URL_PATH,
    _dashboards_dict,
    async_register_dashboard,
)
from custom_components.family_dashboard.dashboard.registry import async_build_dashboard_config


def _member(
    name,
    member_id,
    ha_user_id=None,
    calendar_entity_id=None,
    list_presets=None,
    chores=False,
):
    features = []
    if calendar_entity_id:
        features.append("calendar")
    if list_presets:
        features.append("lists")
    if chores:
        features.append("chores")
    return {
        "member_id": member_id,
        "name": name,
        "color": "Blue",
        "features": features,
        "ha_user_id": ha_user_id,
        "calendar_entity_id": calendar_entity_id,
        "notify_entity_id": None,
        "list_presets": list_presets or [],
    }


def _views_by_path(config):
    """Views now live under `config["strategy"]["views"]`, not a flat top-level `views:` key -
    the dashboard is a STRATEGY (see `dashboard/registry.py`'s own docstring and
    `www/family-dashboard-strategy.js`): a live-confirmed bug fix, since HA's native per-view
    tab strip does not respect per-view `visibility` at all, so a flat shared views list let
    every linked member's tabs leak into every other viewer's tab strip. The strategy filters
    this SAME already-built list down to the current viewer's own bucket at render time -
    everything downstream of this helper (which bucket has which cards) is unchanged."""
    return {v["path"]: v for v in config["strategy"]["views"]}


def _view_cards(view):
    """Views are now built with `type: sections` (see registry.py's `_build_view`), so a
    view's cards live at `sections[0]["cards"]`, not a flat top-level `cards:` list."""
    return view["sections"][0]["cards"]


async def test_nav_titles_are_uniform_and_never_name_a_person(hass):
    """The exact mistake the architecture correction fixes: no view title, anywhere, for any
    bucket, may contain a roster member's name - all four tabs are always titled identically.
    """
    kiosk_account = await hass.auth.async_create_user(name="Kiosk Account")
    ada_account = await hass.auth.async_create_user(name="Ada Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", ha_user_id=ada_account.id, calendar_entity_id="calendar.ada_cal"),
                _member("Grace", "grace", calendar_entity_id="calendar.grace_cal"),
            ],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    bucket_views = config["strategy"]["views"]
    titles = {v["title"] for v in bucket_views}
    assert titles == {"Calendar", "Lists", "Chores", "Settings"}
    for view in bucket_views:
        assert "Ada" not in view["title"]
        assert "Grace" not in view["title"]
        assert "Kiosk" not in view["title"]

    # Every bucket contributes exactly one view per tab: Kiosk + Ada = 2 buckets * 4 tabs.
    assert len(bucket_views) == 8
    assert kiosk_account.id  # sanity: real account, not a placeholder


async def test_strategy_user_bucket_map_covers_every_linked_member(hass):
    """The dashboard is a STRATEGY now (see `dashboard/registry.py`'s own docstring and
    `www/family-dashboard-strategy.js`) - a live-confirmed bug fix, not a stylistic choice.
    HA's native per-view tab strip does not respect per-view `visibility` at all (confirmed
    with a genuinely non-admin linked-member account, fresh incognito window, no other login:
    the tab strip showed every linked member's tabs stacked together despite each view's own
    `visibility` being correctly scoped). The strategy filters the SAME already-built views
    list down to the current viewer's own bucket at render time instead, using this map to
    resolve `hass.user.id` -> bucket key - covered here at the Python boundary; the JS
    filtering logic itself is covered separately via direct Node execution, not pytest.
    """
    kiosk_account = await hass.auth.async_create_user(name="Kiosk Account")
    ada_account = await hass.auth.async_create_user(name="Ada Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", ha_user_id=ada_account.id, calendar_entity_id="calendar.ada_cal"),
                _member("Grace", "grace", calendar_entity_id="calendar.grace_cal"),
            ],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    strategy = config["strategy"]
    assert strategy["type"] == "custom:family-dashboard"
    assert strategy["kiosk_key"] == "kiosk"
    assert strategy["user_bucket_map"] == {
        ada_account.id: "ada",
        kiosk_account.id: "kiosk",
    }
    # Grace has no linked HA account - she never gets an entry in the map, only shows up
    # inside the Kiosk bucket's own content.
    assert "grace" not in strategy["user_bucket_map"].values()


async def test_disabled_linked_member_gets_no_personal_bucket_and_falls_back_to_kiosk(hass):
    """Disable (roster.py's async_set_member_disabled) excludes a member from the dashboard
    entirely - a live-reported design requirement, not just "hide their column": their linked
    HA account should fall back to seeing the shared Kiosk view (same as any never-linked
    account) rather than being orphaned with no bucket at all while disabled."""
    ada_account = await hass.auth.async_create_user(name="Ada Account")
    kiosk_account = await hass.auth.async_create_user(name="Kiosk Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                {
                    **_member("Ada", "ada", ha_user_id=ada_account.id, calendar_entity_id="calendar.ada_cal"),
                    "disabled": True,
                },
                _member("Grace", "grace", calendar_entity_id="calendar.grace_cal"),
            ],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    strategy = config["strategy"]

    # No "ada" bucket at all - her personal views were never generated.
    assert "ada" not in _views_by_path(config)
    assert not any(v["path"].endswith("-ada") for v in strategy["views"])

    # Her HA account falls back into Kiosk instead of vanishing from the map entirely.
    assert strategy["user_bucket_map"][ada_account.id] == "kiosk"
    assert strategy["user_bucket_map"][kiosk_account.id] == "kiosk"

    # Grace (still active) keeps her own spot in the Kiosk Calendar tab's toggle pills; Ada's
    # column is gone from it. Card[0] is the fixed Home/Lists/Chores/Settings hub row,
    # card[1] is Calendar's own controls row (member pills/Birthdays/Holidays/Add Event/view
    # selector) - see `_calendar_controls_row`'s own docstring for why they're separate rows.
    kiosk_calendar_cards = _view_cards(_views_by_path(config)["calendar-kiosk"])
    controls_row = kiosk_calendar_cards[1]
    pill_names = [c.get("name") for c in controls_row["cards"]]
    assert "Grace" in pill_names
    assert "Ada" not in pill_names


async def test_kiosk_bucket_visibility_excludes_linked_members(hass):
    kiosk_account = await hass.auth.async_create_user(name="Kiosk Account")
    ada_account = await hass.auth.async_create_user(name="Ada Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", ha_user_id=ada_account.id, calendar_entity_id="calendar.ada_cal"),
                _member("Grace", "grace", calendar_entity_id="calendar.grace_cal"),
            ],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    views = _views_by_path(config)

    assert views["calendar-kiosk"]["visibility"] == [
        {"condition": "user", "users": [kiosk_account.id]}
    ]
    assert views["calendar-ada"]["visibility"] == [
        {"condition": "user", "users": [ada_account.id]}
    ]
    # Grace has no linked account - she never gets her own bucket, only shows up inside Kiosk.
    assert "calendar-grace" not in views


async def test_nav_row_and_subview_differ_kiosk_vs_personal_bucket(hass):
    """The Kiosk device always runs with HA's own sidebar/header chrome hidden, so it needs
    the custom nav-pill row (and `subview: True` to stay off the native tab strip). A linked
    member's personal bucket keeps that chrome, so it relies on the native tab strip instead
    (`subview: False`) and must NOT also render the redundant custom nav-pill row - explicit
    user requirement: Companion App users need real native tabs, not a custom pill row."""
    kiosk_account = await hass.auth.async_create_user(name="Kiosk Account")
    ada_account = await hass.auth.async_create_user(name="Ada Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", ha_user_id=ada_account.id, calendar_entity_id="calendar.ada_cal"),
            ],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    views = _views_by_path(config)

    kiosk_view = views["calendar-kiosk"]
    assert kiosk_view["subview"] is True
    kiosk_cards = _view_cards(kiosk_view)
    assert kiosk_cards[0]["type"] == "horizontal-stack"
    assert any(c.get("type") == "custom:button-card" for c in kiosk_cards[0]["cards"])

    ada_view = views["calendar-ada"]
    assert ada_view["subview"] is False
    ada_cards = _view_cards(ada_view)

    def _is_nav_pill(card):
        path = card.get("tap_action", {}).get("navigation_path", "")
        return card.get("type") == "custom:button-card" and path.startswith("/family-dashboard/")

    # A personal bucket still has its own (non-nav) horizontal-stacks, e.g. the Add Event
    # button row - what must be absent is specifically the four-tab nav-pill row.
    assert not any(
        c.get("type") == "horizontal-stack" and any(_is_nav_pill(inner) for inner in c["cards"])
        for c in ada_cards
    )

    assert kiosk_account.id  # sanity: real account, not a placeholder


async def test_kiosk_nav_is_hub_and_spoke_with_calendar_as_hub(hass):
    """Explicit user requirement, matching `Family Dashboard - Main.jpg`'s own kiosk photo:
    Calendar is the ONLY hub. From Calendar, Home + Lists + Chores + Settings are all
    reachable, as a fixed row separate from Calendar's own controls (toggle pills/Add Event/
    view selector, which live in their own row below - see `_calendar_controls_row`; kept
    apart so the hub row's width never depends on roster size). From any OTHER tab
    (Lists/Chores/Settings), the row shrinks to just Home + a way back to Calendar - the
    other two tabs must NOT be directly reachable from there, only via Calendar or Home
    first. A prior version showed all four uniform tabs on every Kiosk view unconditionally.
    """
    await hass.auth.async_create_user(name="Kiosk Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [_member("Ada", "ada", calendar_entity_id="calendar.ada_cal")],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    views = _views_by_path(config)

    def _nav_targets(view):
        row = _view_cards(view)[0]
        assert row["type"] == "horizontal-stack"
        targets = []
        for card in row["cards"]:
            path = card.get("tap_action", {}).get("navigation_path", "")
            if card["name"] == "Home":
                targets.append("home")
            elif path.startswith("/family-dashboard/"):
                targets.append(path.rsplit("-", 1)[0].rsplit("/", 1)[-1])
        return targets

    # Calendar: Home first, then links to every other tab - never a link back to Calendar
    # itself (redundant, already there). Exactly 4 pills - Calendar's own controls (toggle
    # pills/Add Event/view selector) live in a separate row below, never mixed into this one.
    calendar_hub_row = _view_cards(views["calendar-kiosk"])[0]
    assert len(calendar_hub_row["cards"]) == 4
    calendar_targets = _nav_targets(views["calendar-kiosk"])
    assert calendar_targets[0] == "home"
    assert set(calendar_targets[1:]) == {"lists", "chores", "settings"}

    # Calendar's own controls (at least one member toggle pill) land in the NEXT row, not the
    # hub row.
    controls_row = _view_cards(views["calendar-kiosk"])[1]
    assert controls_row["type"] == "horizontal-stack"
    assert any(
        c.get("tap_action", {}).get("target", {}).get("entity_id") == "switch.family_dashboard_ada_shown"
        for c in controls_row["cards"]
    )

    # Home button navigates to the fixed, external Kiosk root dashboard - not something this
    # integration generates or validates.
    home_pill = _view_cards(views["calendar-kiosk"])[0]["cards"][0]
    assert home_pill["tap_action"] == {
        "action": "navigate",
        "navigation_path": "/dashboard-home/home",
    }

    # Lists/Chores/Settings: exactly Home + Calendar, nothing else - the other two tabs must
    # not appear.
    for path in ("lists-kiosk", "chores-kiosk", "settings-kiosk"):
        assert _nav_targets(views[path]) == ["home", "calendar"]


async def test_kiosk_calendar_has_toggle_filter_switches_for_every_mapped_member(hass):
    """Covers both the filter mechanism itself (week-planner-card `filter:` templating,
    already tested here) AND that a real, clickable pill exists for each one - a prior
    version had the former without the latter (the switches/filtering worked, but nothing
    on the dashboard ever rendered a button to flip a switch), a real gap only caught by a
    live Kiosk-account session, not by config-shape inspection alone."""
    await hass.auth.async_create_user(name="Kiosk Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", calendar_entity_id="calendar.ada_cal"),
                _member("Grace", "grace", calendar_entity_id="calendar.grace_cal"),
                _member("Bob", "bob"),  # no calendar - excluded entirely
            ],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    kiosk_calendar_cards = _view_cards(_views_by_path(config)["calendar-kiosk"])

    def _pill_target(card):
        return card.get("tap_action", {}).get("target", {}).get("entity_id")

    # The toggle pills live in their own controls row alongside Calendar's Add Event/
    # view-selector controls, separate from the fixed Home/Lists/Chores/Settings hub row (see
    # `_nav_row`/`_calendar_controls_row`) - filter down to just the member-toggle pills
    # specifically by their switch target.
    nav_row = next(
        c
        for c in kiosk_calendar_cards
        if c.get("type") == "horizontal-stack"
        and any(_pill_target(card) == "switch.family_dashboard_ada_shown" for card in c["cards"])
    )
    toggle_pills = [
        card
        for card in nav_row["cards"]
        if _pill_target(card) and _pill_target(card).endswith("_shown")
    ]
    pill_targets = [_pill_target(card) for card in toggle_pills]
    assert pill_targets == [
        "switch.family_dashboard_ada_shown",
        "switch.family_dashboard_grace_shown",
    ]
    assert all(card.get("type") == "custom:button-card" for card in toggle_pills)
    ada_pill = toggle_pills[0]
    assert ada_pill["name"] == "Ada"
    assert ada_pill["tap_action"] == {
        "action": "perform-action",
        "perform_action": "switch.toggle",
        "target": {"entity_id": "switch.family_dashboard_ada_shown"},
    }
    # Avatar image and roster-color tint are live-templated (button-card `[[[ ]]]`), not
    # baked in at generation time - see async_member_toggle_pills' docstring.
    assert "select.family_dashboard_ada_avatar" in ada_pill["custom_fields"]["pic"]
    bg_style = next(d["background-color"] for d in ada_pill["styles"]["card"] if "background-color" in d)
    assert "select.family_dashboard_ada_color" in bg_style

    template_card = next(
        c for c in kiosk_calendar_cards if c.get("type") == "custom:config-template-card"
    )
    assert template_card["entities"] == [
        "switch.family_dashboard_ada_shown",
        "switch.family_dashboard_grace_shown",
        "select.family_dashboard_ada_color",
        "select.family_dashboard_grace_color",
    ]
    week_planner = template_card["card"]
    assert week_planner["type"] == "custom:week-planner-card"
    # Fixed to week-planner-card's own full-month mode - no view-switcher control (removed
    # 2026-07-25), no leading/trailing days from adjacent months.
    assert week_planner["days"] == "month"
    assert week_planner["startingDay"] == "month"
    calendars = week_planner["calendars"]
    # Event color is also live-templated to the member's roster color, not a static hex
    # baked in at generation time - see async_kiosk_calendar_card's own inline comment.
    assert "select.family_dashboard_ada_color" in calendars[0]["color"]
    assert [c["entity"] for c in calendars] == [
        "calendar.family_dashboard_ada_calendar",
        "calendar.family_dashboard_grace_calendar",
    ]
    assert "switch.family_dashboard_ada_shown" in calendars[0]["filter"]
    assert "'.*'" in calendars[0]["filter"] and "'^$'" in calendars[0]["filter"]


async def test_linked_member_calendar_shows_own_plus_family_calendar_only(hass):
    """A linked member's own personal Calendar tab shows their own calendar plus the
    auto-detected shared Family calendar (any calendar.* entity whose own name is literally
    "Family") - NOT any other roster member's own calendar. Replaces the earlier design where
    one flagged roster member's own mapping doubled as the shared one - "Family" is now an
    independent entity, detected by name, not tied to Grace (or anyone)."""
    ada_account = await hass.auth.async_create_user(name="Ada Account")
    await hass.auth.async_create_user(name="Kiosk Account")

    # The household's shared calendar - auto-detected by name, independent of any roster
    # member's own mapping (see modules/calendar/dashboard.py's _family_calendar_entity).
    hass.states.async_set("calendar.family_shared", "off", {"friendly_name": "Family"})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", ha_user_id=ada_account.id, calendar_entity_id="calendar.ada_cal"),
                _member("Grace", "grace", calendar_entity_id="calendar.grace_cal"),
            ],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    ada_calendar_cards = _view_cards(_views_by_path(config)["calendar-ada"])

    # Wrapped in config-template-card so the Family overlay's own toggle switch can template
    # its filter here too, same as the Kiosk bucket's own card - unlike a per-member toggle
    # (nothing else here to filter - only ever one or two calendars shown in a personal
    # bucket).
    template_card = next(
        c for c in ada_calendar_cards if c.get("type") == "custom:config-template-card"
    )
    assert template_card["entities"] == ["switch.family_dashboard_family_calendar_shown"]
    week_planner = template_card["card"]
    assert week_planner["type"] == "custom:week-planner-card"
    # Fixed to week-planner-card's own full-month mode - no view-switcher control (removed
    # 2026-07-25), no leading/trailing days from adjacent months.
    assert week_planner["days"] == "month"
    assert week_planner["startingDay"] == "month"
    assert [c["entity"] for c in week_planner["calendars"]] == [
        "calendar.family_dashboard_ada_calendar",
        "calendar.family_shared",
    ]
    ada_entry, family_entry = week_planner["calendars"]
    assert "filter" not in ada_entry
    assert "filter" in family_entry  # Family is toggleable, unlike a personal calendar here

    # No view-selector pill in Ada's own controls row anymore - only Add Event + the
    # Family/Birthdays/Holidays toggle pills.
    controls_row = next(c for c in ada_calendar_cards if c.get("type") == "horizontal-stack")
    assert not any(
        c.get("tap_action", {}).get("perform_action") == "select.select_next"
        for c in controls_row["cards"]
    )


async def test_holidays_overlay_shows_every_country_toggleable_on_both_bucket_kinds(hass):
    """Two Holiday integration entries (US + Philippines) both show up automatically - no
    hardcoded single country - under one shared toggle, on BOTH the Kiosk bucket's and a
    linked member's own personal bucket's Calendar tab (a live-reported requirement: these
    overlays must always be visible everywhere, toggleable like any roster member's own
    calendar, not Kiosk-only fixed layers)."""
    from homeassistant.helpers import entity_registry as er

    ada_account = await hass.auth.async_create_user(name="Ada Account")
    await hass.auth.async_create_user(name="Kiosk Account")

    registry = er.async_get(hass)
    us_entry = MockConfigEntry(domain="holiday", data={"country": "US"}, title="United States")
    us_entry.add_to_hass(hass)
    registry.async_get_or_create("calendar", "holiday", "us_holidays", config_entry=us_entry)
    ph_entry = MockConfigEntry(domain="holiday", data={"country": "PH"}, title="Philippines")
    ph_entry.add_to_hass(hass)
    registry.async_get_or_create("calendar", "holiday", "ph_holidays", config_entry=ph_entry)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", ha_user_id=ada_account.id, calendar_entity_id="calendar.ada_cal"),
            ],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)

    def _has_holidays_pill(cards):
        return any(
            c.get("tap_action", {}).get("target", {}).get("entity_id")
            == "switch.family_dashboard_holidays_shown"
            for card in cards
            if card.get("type") == "horizontal-stack"
            for c in card["cards"]
        )

    kiosk_cards = _view_cards(_views_by_path(config)["calendar-kiosk"])
    ada_cards = _view_cards(_views_by_path(config)["calendar-ada"])
    assert _has_holidays_pill(kiosk_cards)
    assert _has_holidays_pill(ada_cards)

    ada_template_card = next(
        c for c in ada_cards if c.get("type") == "custom:config-template-card"
    )
    holiday_calendars = [
        c for c in ada_template_card["card"]["calendars"] if c["name"] in ("United States", "Philippines")
    ]
    assert len(holiday_calendars) == 2
    assert all("filter" in c for c in holiday_calendars)
    assert "switch.family_dashboard_holidays_shown" in ada_template_card["entities"]


async def test_calendar_controls_omitted_when_nobody_has_calendar_enabled(hass):
    """The Add Event/Birthdays-Holidays controls reference entities from Calendar's
    conditionally-forwarded platforms (select/switch/etc.) - those platforms never get
    forwarded at all if no roster member has "calendar" enabled, so the controls must not
    reference them either. Live-verified regression: an earlier version rendered these
    controls unconditionally and crashed with a real browser
    `ButtonCardJSTemplateError: Cannot read properties of undefined (reading 'state')` on
    exactly this roster shape.
    """
    ada_account = await hass.auth.async_create_user(name="Ada Account")
    await hass.auth.async_create_user(name="Kiosk Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", ha_user_id=ada_account.id),  # no calendar, no chores
                _member("Grace", "grace"),
            ],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    views = _views_by_path(config)

    for path in ("calendar-kiosk", "calendar-ada"):
        cards = _view_cards(views[path])
        assert not any(c.get("type") == "custom:config-template-card" for c in cards)
        assert not any("family_dashboard.add_event" in str(c) for c in cards)
        assert any(
            c.get("type") == "markdown" and "No calendars are mapped" in c.get("content", "")
            for c in cards
        )


async def test_lists_kiosk_grouped_by_header_personal_bucket_no_header(hass):
    ada_account = await hass.auth.async_create_user(name="Ada Account")
    await hass.auth.async_create_user(name="Kiosk Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", ha_user_id=ada_account.id, list_presets=["to_do", "shopping"]),
                _member("Grace", "grace"),
            ],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    views = _views_by_path(config)

    # The per-member header is a custom:button-card with a live avatar image (custom_fields.pic),
    # not a markdown card with a raw <img> tag - live-verified that HA's markdown card
    # sanitizes away the inline sizing style, rendering the seeded 640x640 avatar PNGs at
    # native size ("ridiculously large" per a live user report).
    # Every member's lists sit side by side in ONE horizontal-stack of per-member
    # vertical-stacks (matches Chores' own side-by-side column layout - a live-reported
    # layout gap this mirrors), not flat top-level cards.
    kiosk_lists = _view_cards(views["lists-kiosk"])
    # kiosk_lists[0] is the always-prepended four-tab nav-pill row (also a horizontal-stack) -
    # find the ONE whose children are vertical-stacks, not nav pills.
    columns_row = next(
        c
        for c in kiosk_lists
        if c.get("type") == "horizontal-stack"
        and any(card.get("type") == "vertical-stack" for card in c["cards"])
    )
    ada_column = next(
        c["cards"]
        for c in columns_row["cards"]
        if c.get("type") == "vertical-stack"
        and c["cards"][0].get("name") == "Ada's Lists"
    )
    header = ada_column[0]
    assert header["type"] == "custom:button-card"
    assert "select.family_dashboard_ada_avatar" in header["custom_fields"]["pic"]
    todo_cards = [c for c in ada_column if c.get("type") == "todo-list"]
    assert [c["entity"] for c in todo_cards] == [
        "todo.family_dashboard_ada_to_do",
        "todo.family_dashboard_ada_shopping",
    ]

    ada_lists = _view_cards(views["lists-ada"])
    assert not any(
        c.get("type") == "custom:button-card" and "Lists" in str(c.get("name", "")) for c in ada_lists
    )
    assert [c["entity"] for c in ada_lists if c.get("type") == "todo-list"] == [
        "todo.family_dashboard_ada_to_do",
        "todo.family_dashboard_ada_shopping",
    ]


async def test_lists_card_omitted_when_feature_disabled_despite_presets_set(hass):
    """Regression: `async_lists_cards_for_member` used to build a card per preset regardless
    of whether "lists" was still selected - only the ENTITY creation (modules/lists/todo.py)
    checked the feature. `list_presets` is deliberately left intact by a feature toggle-off
    (so re-enabling restores the same selection), so the dashboard card builder must check
    the feature flag itself, not just whether presets exist."""
    await hass.auth.async_create_user(name="Kiosk Account")

    member = {
        "member_id": "ada",
        "name": "Ada",
        "color": "Blue",
        "features": [],  # "lists" NOT selected, despite presets below
        "ha_user_id": None,
        "calendar_entity_id": None,
        "notify_entity_id": None,
        "list_presets": ["shopping", "to_do"],
    }
    entry = MockConfigEntry(
        domain=DOMAIN, data={"roster": [member]}
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    kiosk_lists = _view_cards(_views_by_path(config)["lists-kiosk"])
    assert not any(c.get("type") == "todo-list" for c in kiosk_lists)
    assert any(
        c.get("type") == "markdown" and "No lists are set up" in c.get("content", "")
        for c in kiosk_lists
    )


async def test_settings_features_and_mapping_kiosk_only(hass):
    """Feature toggles and Calendar/Notify mapping are explicit Kiosk/parent-only controls -
    unlike Name/Color/Avatar, they must never appear in a linked member's own personal
    Settings bucket."""
    kiosk_account = await hass.auth.async_create_user(name="Kiosk Account")
    ada_account = await hass.auth.async_create_user(name="Ada Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [_member("Ada", "ada", ha_user_id=ada_account.id, list_presets=["shopping"])],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    config = await async_build_dashboard_config(hass, entry)
    views = _views_by_path(config)

    kiosk_settings = _view_cards(views["settings-kiosk"])
    assert any(
        c.get("type") == "markdown" and "Features & Mapping" in c.get("content", "")
        for c in kiosk_settings
    )
    # The Features & Mapping grid holds one vertical-stack per member (same "grid of stacks"
    # shape as the Name/Color/Avatar grid, see `test_settings_view_is_a_grid_of_per_member_
    # name_color_avatar_stacks`) - it's the SECOND grid card, after the member-settings grid.
    grids = [c for c in kiosk_settings if c.get("type") == "grid"]
    assert len(grids) == 2
    feature_grid = grids[1]
    feature_switch_targets = {
        card.get("tap_action", {}).get("target", {}).get("entity_id")
        for stack in feature_grid["cards"]
        for row in stack["cards"]
        if row.get("type") == "horizontal-stack"
        for card in row["cards"]
    }
    assert "switch.family_dashboard_ada_lists_enabled" in feature_switch_targets

    ada_settings = _view_cards(views["settings-ada"])
    assert not any(
        c.get("type") == "markdown" and "Features & Mapping" in c.get("content", "")
        for c in ada_settings
    )
    assert "family_dashboard_ada_feature_" not in str(ada_settings)
    assert "calendar_map" not in str(ada_settings)
    assert "notify_map" not in str(ada_settings)

    assert kiosk_account.id  # sanity: real account, not a placeholder


async def test_kiosk_chores_has_toggle_pills_parent_lock_and_pin_popup(hass):
    await hass.auth.async_create_user(name="Kiosk Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [_member("Ada", "ada", chores=True)],
            "chores": [
                {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}
            ],
            "rewards": [],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    config = await async_build_dashboard_config(hass, entry)
    kiosk_chores = _view_cards(_views_by_path(config)["chores-kiosk"])

    def _pill_target(card):
        return card.get("tap_action", {}).get("target", {}).get("entity_id")

    # Chores' toggle pills reuse Calendar's own avatar+color pill builder
    # (`member_avatar_toggle_pill`) rather than a plain generic-icon `tile` card, so the row
    # is stylistically identical to the Calendar tab's pills - a live-reported inconsistency
    # ("old style button and not the new style") this covers.
    assert any(
        c.get("type") == "horizontal-stack"
        and any(_pill_target(card) == "switch.family_dashboard_ada_shown" for card in c["cards"])
        for c in kiosk_chores
    )
    toggle_row = next(
        c
        for c in kiosk_chores
        if c.get("type") == "horizontal-stack"
        and any(_pill_target(card) == "switch.family_dashboard_ada_shown" for card in c["cards"])
    )
    ada_pill = toggle_row["cards"][0]
    assert ada_pill["type"] == "custom:button-card"
    assert "select.family_dashboard_ada_avatar" in ada_pill["custom_fields"]["pic"]

    # Parent lock and the per-kid columns are each wrapped in their own horizontal-stack (a
    # bare top-level card stretches to the section grid's full row height, live-verified
    # mismatch against the toggle pills' identical `height: 52px` - the "Parent: Locked
    # should be one button in height" fix), so flatten one level to check their contents.
    nested_cards = [c for hs in kiosk_chores if hs.get("type") == "horizontal-stack" for c in hs["cards"]]

    # Parent lock comes immediately before the toggle-pill row (live-reported ordering fix) -
    # kiosk_chores[0] is the always-prepended four-tab nav-pill row, not part of this module's
    # own output, so index relative to toggle_row instead of a hardcoded absolute position.
    toggle_row_index = kiosk_chores.index(toggle_row)
    parent_lock_row = kiosk_chores[toggle_row_index - 1]
    assert parent_lock_row["type"] == "horizontal-stack"
    assert parent_lock_row["cards"][0]["type"] == "custom:button-card"
    assert "parent_mode" in str(parent_lock_row["cards"][0])

    assert any(c.get("type") == "custom:bubble-card" and c.get("hash") == "#parentpin" for c in kiosk_chores)
    assert any(
        c.get("type") == "conditional"
        and c["conditions"] == [{"entity": "switch.family_dashboard_ada_shown", "state": "on"}]
        for c in nested_cards
    )


async def test_kiosk_chores_shows_multiple_kids_side_by_side(hass):
    """A live-reported layout gap: each kid's chores content was a separate full-width card
    stacking vertically, one after another, instead of side-by-side columns matching
    `Chores - 1.png`'s mockup layout. Every chores-enabled kid's column must land in the SAME
    horizontal-stack, not separate top-level cards.
    """
    await hass.auth.async_create_user(name="Kiosk Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", chores=True),
                _member("Grace", "grace", chores=True),
            ],
            "chores": [
                {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"},
                {"chore_id": "dishes", "name": "Dishes", "points": 5, "frequency": "daily", "assigned_to": "grace"},
            ],
            "rewards": [],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    config = await async_build_dashboard_config(hass, entry)
    kiosk_chores = _view_cards(_views_by_path(config)["chores-kiosk"])

    columns_row = next(
        c
        for c in kiosk_chores
        if c.get("type") == "horizontal-stack"
        and sum(1 for card in c["cards"] if card.get("type") == "conditional") == 2
    )
    conditions = [card["conditions"][0]["entity"] for card in columns_row["cards"]]
    assert conditions == [
        "switch.family_dashboard_ada_shown",
        "switch.family_dashboard_grace_shown",
    ]


async def test_settings_view_is_a_grid_of_per_member_name_color_avatar_stacks(hass):
    """Matches `Better-Settings.png`'s compact card-grid layout, not the earlier full-width
    markdown-header-per-member list the user called "not pretty"."""
    await hass.auth.async_create_user(name="Kiosk Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", calendar_entity_id="calendar.ada_cal"),
                _member("Grace", "grace", calendar_entity_id="calendar.grace_cal"),
            ],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    config = await async_build_dashboard_config(hass, entry)
    settings_cards = _view_cards(_views_by_path(config)["settings-kiosk"])

    grid = next(c for c in settings_cards if c.get("type") == "grid")
    assert len(grid["cards"]) == 2  # one vertical-stack per member
    ada_stack = grid["cards"][0]
    assert ada_stack["type"] == "vertical-stack"
    inner_types = [c["type"] for c in ada_stack["cards"]]
    assert inner_types == [
        "custom:button-card",
        "custom:button-card",
        "custom:button-card",
        "custom:button-card",
    ]
    name_card, color_card, avatar_card, birthdate_card = ada_stack["cards"]
    assert "text.family_dashboard_ada_name" in name_card["name"]
    assert "select.family_dashboard_ada_color" in color_card["name"]
    assert avatar_card["tap_action"] == {"action": "navigate", "navigation_path": "#avatar-ada"}
    assert "date.family_dashboard_ada_birthdate" in birthdate_card["name"]


async def test_personal_settings_view_shows_only_own_member_not_everyone(hass):
    """Explicit user requirement: Kiosk can still see/adjust every family member's own
    Name/Color/Avatar settings, but a linked member's personal Settings view must only show
    THEIR OWN card - not another family member's, which the earlier "identical content for
    every bucket" design left visible to anyone who happened to look."""
    kiosk_account = await hass.auth.async_create_user(name="Kiosk Account")
    ada_account = await hass.auth.async_create_user(name="Ada Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                _member("Ada", "ada", ha_user_id=ada_account.id, calendar_entity_id="calendar.ada_cal"),
                _member("Grace", "grace", calendar_entity_id="calendar.grace_cal"),
            ],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    config = await async_build_dashboard_config(hass, entry)
    views = _views_by_path(config)

    kiosk_settings = _view_cards(views["settings-kiosk"])
    kiosk_grid = next(c for c in kiosk_settings if c.get("type") == "grid")
    assert len(kiosk_grid["cards"]) == 2  # Kiosk still sees both Ada and Grace

    ada_settings = _view_cards(views["settings-ada"])
    ada_grid = next(c for c in ada_settings if c.get("type") == "grid")
    assert len(ada_grid["cards"]) == 1  # Ada's own bucket sees only her own card
    name_card = ada_grid["cards"][0]["cards"][0]
    assert "text.family_dashboard_ada_name" in name_card["name"]
    assert "grace" not in str(ada_grid).lower()

    assert kiosk_account.id  # sanity: real account, not a placeholder


async def test_no_kiosk_bucket_when_every_active_user_is_linked(hass):
    """If literally every real HA user is linked to a roster member, there's nobody left for
    the Kiosk bucket - it's omitted entirely rather than generating an empty-visibility view.
    """
    ada_account = await hass.auth.async_create_user(name="Ada Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [_member("Ada", "ada", ha_user_id=ada_account.id)],
        },
    )
    entry.add_to_hass(hass)

    config = await async_build_dashboard_config(hass, entry)
    view_paths = {v["path"] for v in config["strategy"]["views"]}
    assert not any(path.endswith("-kiosk") for path in view_paths)
    assert "calendar-ada" in view_paths


async def test_register_dashboard_is_real_and_idempotent(hass):
    assert await async_setup_component(hass, "lovelace", {"lovelace": {}})
    await hass.async_block_till_done()

    entry = MockConfigEntry(domain=DOMAIN, data={"roster": []})
    entry.add_to_hass(hass)

    config1 = {
        "title": "Family Dashboard",
        "views": [{"title": "Calendar", "path": "calendar-kiosk", "cards": []}],
    }
    assert await async_register_dashboard(hass, entry, config1)

    dashboards = _dashboards_dict(hass)
    assert DASHBOARD_URL_PATH in dashboards
    saved = await dashboards[DASHBOARD_URL_PATH].async_load(False)
    assert saved == config1

    # Calling again (e.g. a second entry setup / HA restart) updates in place, doesn't error
    # or create a duplicate.
    config2 = {
        "title": "Family Dashboard",
        "views": [
            {
                "title": "Calendar",
                "path": "calendar-kiosk",
                "cards": [{"type": "markdown", "content": "updated"}],
            }
        ],
    }
    assert await async_register_dashboard(hass, entry, config2)
    saved2 = await dashboards[DASHBOARD_URL_PATH].async_load(False)
    assert saved2 == config2


async def test_chores_rewards_management_moved_behind_parent_pin(hass):
    """Add/edit/delete for Chores & Rewards no longer lives in Settings at all (live-reported
    gap: that location was Kiosk-only but had NO Parent PIN gate - any kid could add/
    reassign/repoint/delete chores and rewards freely). It moved to the Chores tab, wrapped in
    the SAME `binary_sensor.family_dashboard_parent_mode == "on"` conditional Parent Review
    already uses - and like Parent Review, it's Kiosk-only, never a linked member's own
    personal bucket."""
    kiosk_account = await hass.auth.async_create_user(name="Kiosk Account")
    ada_account = await hass.auth.async_create_user(name="Ada Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [_member("Ada", "ada", ha_user_id=ada_account.id, chores=True)],
            "chores": [
                {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"}
            ],
            "rewards": [],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    config = await async_build_dashboard_config(hass, entry)
    views = _views_by_path(config)

    # Gone from Settings entirely - not just re-gated in place.
    kiosk_settings = _view_cards(views["settings-kiosk"])
    assert not any(
        c.get("type") == "markdown" and "Chores & Rewards" in c.get("content", "")
        for c in kiosk_settings
    )
    assert "addchore" not in str(kiosk_settings)
    assert "addreward" not in str(kiosk_settings)

    # Present on the Kiosk Chores tab, wrapped in the Parent PIN conditional.
    kiosk_chores = _view_cards(views["chores-kiosk"])
    management_card = next(
        c
        for c in kiosk_chores
        if c.get("type") == "conditional"
        and c["conditions"] == [{"entity": "binary_sensor.family_dashboard_parent_mode", "state": "on"}]
        and "Manage Chores & Rewards" in str(c["card"])
    )
    assert "family_dashboard_trash_name" in str(management_card)
    assert any(
        cc.get("type") == "custom:bubble-card" and cc.get("hash") == "#addchore"
        for cc in management_card["card"]["cards"]
    )
    assert any(
        cc.get("type") == "custom:bubble-card" and cc.get("hash") == "#addreward"
        for cc in management_card["card"]["cards"]
    )

    # Never on a linked member's own personal Chores bucket, same as Parent Review.
    ada_chores = _view_cards(views["chores-ada"])
    assert not any("Manage Chores & Rewards" in str(c) for c in ada_chores)
    assert not any(c.get("hash") == "#addchore" for c in ada_chores)

    assert kiosk_account.id  # sanity: real account, not a placeholder


async def test_unassigned_chore_is_management_only_not_a_chores_tab_column(hass):
    """An unassigned chore/reward (explicit user request - no owner required) has entities
    but no member column to appear in - `_member_task_cards`'s per-member filtering never
    matches `None`. It's still editable/deletable, just from the PIN-gated Manage Chores &
    Rewards section (moved off Settings 2026-07-20), not from any per-kid column."""
    await hass.auth.async_create_user(name="Kiosk Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [_member("Ada", "ada", chores=True)],
            "chores": [
                {"chore_id": "trash", "name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "ada"},
                {"chore_id": "dishes", "name": "Dishes", "points": 5, "frequency": "daily", "assigned_to": None},
            ],
            "rewards": [],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Entities for the unassigned chore DO exist (editable/deletable from Manage Chores &
    # Rewards, once parent-unlocked).
    assert hass.states.get("sensor.family_dashboard_dishes") is not None

    config = await async_build_dashboard_config(hass, entry)
    kiosk_chores = _view_cards(_views_by_path(config)["chores-kiosk"])

    # Absent from every per-kid column (each its own conditional keyed on that member's own
    # `..._shown` switch, distinct from the management section's `parent_mode` conditional).
    # Per-kid columns are nested one level inside a horizontal-stack (same flattening
    # `test_kiosk_chores_has_toggle_pills_parent_lock_and_pin_popup` already needs), not
    # top-level cards.
    nested_cards = [c for hs in kiosk_chores if hs.get("type") == "horizontal-stack" for c in hs["cards"]]
    member_columns = [
        c
        for c in nested_cards
        if c.get("type") == "conditional"
        and c["conditions"][0]["entity"] == "switch.family_dashboard_ada_shown"
    ]
    assert member_columns  # Ada's own column exists (holds "trash")
    assert not any("dishes" in str(c).lower() for c in member_columns)
    assert any("trash" in str(c).lower() for c in member_columns)

    # Present in the PIN-gated management section instead - NOT Parent Review's own card,
    # which shares the identical `parent_mode` conditional and would otherwise match first.
    management_card = next(
        c
        for c in kiosk_chores
        if c.get("type") == "conditional"
        and c["conditions"] == [{"entity": "binary_sensor.family_dashboard_parent_mode", "state": "on"}]
        and "Manage Chores & Rewards" in str(c["card"])
    )
    assert "family_dashboard_dishes_name" in str(management_card)

    # Gone from Settings entirely.
    kiosk_settings = _view_cards(_views_by_path(config)["settings-kiosk"])
    assert "family_dashboard_dishes_name" not in str(kiosk_settings)
