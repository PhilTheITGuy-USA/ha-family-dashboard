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
  hardcoded country) overlay layers - added to BOTH bucket kinds. Only Family has a
  toggle-filter pill (`switch.family_dashboard_family_calendar_shown`,
  `async_family_calendar_toggle_pill`); Birthdays/Holidays are ALWAYS shown with no button at
  all (2026-07-25, a live request - see `_overlay_entries`'s docstring for why Birthdays
  stayed the existing computed entity rather than becoming real events written into the
  Family calendar, the safer of two options presented). One combined Holidays overlay covers
  every detected country, not one per country; Family defaults on when toggleable.
- Both bucket kinds' cards are fixed to a full-month view (`days: "month"` sets
  week-planner-card's own `_numberOfDaysIsMonth`, sizing the grid to `startDate.daysInMonth`
  regardless of the specific month). `showNavigation: true`'s built-in prev/next arrows still
  work for browsing other months - with `_numberOfDaysIsMonth` true they advance by whole
  months (`_getStartDate`'s `t.plus({months: this._navigationOffset})`), not by a fixed day
  count. 2026-07-25: replaced the old Today/Tomorrow/Week/Biweek/Month cycle-pill and its
  backing `select.family_dashboard_calendar_view` entity entirely - a live request to drop
  the view switcher in favor of an always-current-month grid.
- `startingDay: "sunday"` (2026-07-26, Skylight-calendar-inspired redesign, superseding an
  earlier `startingDay: "month"` choice from the same day - see git history) - a live
  reference photo showed Skylight uses a genuine fixed Sun-Sat weekday-header ROW
  (`showWeekDayText: False` below), which only reads true if every column consistently holds
  the same real weekday every week; `startingDay: "month"` doesn't guarantee that (day 1
  lands in whatever column its own real weekday happens to be, e.g. every column reads
  "Wednesday" for a month starting on one). `startingDay: "sunday"` instead pads the grid to
  align day 1 to its real Sunday-starting week, live-verified via source to mark the
  leading/trailing padding days `isOutsideMonth` - which week-planner-card already renders as
  fully empty boxes (no number, no events - its own source's `_renderDays` special-cases
  isOutsideMonth days to a bare empty div) with zero extra styling needed. This is a
  deliberate, live-requested
  DEPARTURE from Skylight's own actual behavior (which shows real, muted adjacent-month day
  numbers in those padding cells, per the reference photo) - explicitly rejected in favor of
  genuinely blank placeholder cells.
- The Add Event popup (`async_add_event_popup_card`/`async_add_event_button`) - a
  `custom:bubble-card` pop-up with the scratch fields from `text.py`/`switch.py`/`date.py`/
  `datetime.py`/`number.py`/`select.py`, submitting via the `family_dashboard.add_event`
  service (see `events.py`). Reminders are four independent weeks/days/hours/minutes-before
  `number` fields (`number.py`, replacing 2026-07-25's fixed 1-week/1-day/1-hour checkboxes -
  a live request for a configurable lead time instead of a static one). Start/End time-of-day
  is a single combined `datetime` field per side (2026-07-26, reverting 2026-07-25's
  decomposed Date+Hour(1-12)+Minute+AM/PM group - a live report called that "far too many
  clicks and opens sub windows" - back to v0.9.0-beta.4's compact layout; see
  `event_time.py`'s docstring for why no separate AM/PM control is needed - the native
  picker already resolves an unambiguous absolute time regardless of the viewer's 12-vs-24-
  hour account setting), and Start's own `datetime` auto-defaults End's to itself plus one
  hour on every set (`event_time.py`'s `async_recompute_end_datetime_from_start`). Recurring
  is a switch + conditional Recurrence-preset select, same shape as All Day Event
  (`switch.py`/`select.py`) - see `events.py` for how a preset becomes an RFC5545 `rrule`
  passed directly to the target calendar entity (bypassing the `calendar.create_event`
  SERVICE, which has no recurrence support at all).

card_mod styling adapted from the legacy file's proven week-planner-card block, with the
'Ovo' theme font reference dropped from THIS specific block (the theme now provides it
globally instead - see `themes/family_dashboard.yaml`/`assets.py`).

2026-08-02, kiosk-fit experiment (EXPERIMENTAL, not yet live-tuned - a live user request to
guarantee the whole dashboard, tabs/chips/calendar included, never overspills a 1920x1080
kiosk viewport, with bigger/more-legible title-only day cells): day cells now show ONLY the
event title (`showLocation`/`showDescription` off, `.time` CSS-hidden - see
`_WEEK_PLANNER_STATIC_OPTIONS`/`_CARD_MOD_STYLE`); everything else (time, location,
description) is reached via week-planner-card's own pre-existing tap-to-open event-details
dialog (`_handleEventClick` in the card's own source - not something this integration added,
just newly relied on now that the grid itself stopped showing it inline). The calendar card's
own box is now a hard `calc(100vh - 240px)` (both `height` and `max-height`, replacing the
previous grow-to-fit `min-height` clamp) with `overflow-y: auto` as a safety net, plus
`maxDayEvents: 3` capping how many events one day can render before falling back to a static
"+N more" label (not clickable) - both the `240px` reservation and the `3`-event cap are
guesses pending live verification against the real kiosk display's actual nav/controls-row
heights and typical event density, not measured values.
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
    "!important; box-shadow: none !important; "
    # 2026-08-02, kiosk-fit experiment (EXPERIMENTAL - needs live tuning, not a final value):
    # previously `height: auto` + a `min-height` clamp let the card grow to whatever the
    # current month's row count actually needed, specifically to avoid an earlier fixed-height
    # bug where overflowing content rendered its last row's background outside the card
    # entirely. That traded "never clips" for "can overspill the 1920x1080 kiosk viewport
    # below the nav/controls rows" - now doing the reverse: a hard `calc(100vh - Npx)` box
    # (both height and max-height, so it can't grow) with `overflow-y: auto` as the safety net
    # that reproduces the OLD fix's non-clipping property (a scrollbar instead of content
    # bleeding past the card's own rounded background) if content still doesn't fit. The `Npx`
    # reservation below is a rough guess at the fixed Kiosk hub-nav-row (52px) + controls-row
    # (52px) + inter-card/view gaps - it is NOT pixel-verified against the real kiosk display
    # yet and should be the first thing tuned once viewed live; see also `maxDayEvents` in
    # `_WEEK_PLANNER_STATIC_OPTIONS`, which caps events-per-day so a single busy day can't
    # blow out one row's height regardless of this container's own sizing.
    "height: calc(100vh - 240px) !important; max-height: calc(100vh - 240px) !important; "
    "min-height: 0 !important; overflow-y: auto !important; overflow-x: hidden !important; "
    # Live-measured via getComputedStyle (not eyeballed off a screenshot): `.event .inner`'s
    # padding reads `var(--event-padding)`, which week-planner-card's OWN CSS only shrinks
    # from its spacious 10px-all-sides default to a compact `2px 5px` inside a container query
    # keyed on ITS OWN rendered width - this card's actual width on a 1920px kiosk view never
    # crosses that threshold, so the spacious default was silently what applied, not a bug in
    # our own `.event`/`.title` rules (title itself measured exactly as expected). Overridden
    # directly as a custom property here instead of guessing the container-query threshold -
    # custom properties cascade through the shadow root the same as any inherited CSS value,
    # so this reaches `.event .inner` (and the "+N more"/"no events" labels, which read the
    # same variable) without needing card_mod to know their internal implementation at all.
    "--event-padding: 2px 6px !important; --event-spacing: 3px !important; "
    "color: #2b2b2b !important; "
    # Live-verified real gap (2026-07-25): week-planner-card's own internal CSS never
    # references any HA theme variable for its text, so the "Family Dashboard" theme's 'Ovo'
    # font was silently never actually rendering on the calendar grid AT ALL, on any install,
    # ever - confirmed by checking computed styles in a real browser: --primary-font-family
    # correctly resolved to 'Ovo', serif on the view once the (separate, also-fixed)
    # dashboard/view theme-drop bug was fixed, yet the day-number's own computed font-family
    # still showed the browser/HA default. Setting it explicitly here, once, on ha-card lets
    # it cascade normally to every descendant (.day/.event/.time/etc rules below only set
    # size/weight/color, not font-family, so they don't need their own copy of this).
    "font-family: var(--primary-font-family, inherit) !important; } "
    ".navigation, .navigation * { color: #2b2b2b !important; font-weight: 600 !important; } "
    # 2026-07-26, Skylight-calendar-inspired redesign (live reference photo, user request -
    # "days listed on top, numbers in the calendar, far more readable"): `showWeekDayText:
    # False` (see _WEEK_PLANNER_STATIC_OPTIONS) switches week-planner-card from its default
    # "Wednesday" inline-per-day-cell label into a genuine top header ROW of weekday names
    # instead (`.day.header` cells - live-verified via source: the card already supports
    # this, it just defaults the OTHER way and we'd simply never set the option before) -
    # this ALSO means regular day cells stop rendering their own `.date .text` span
    # entirely (the same CSS class the header row's OWN weekday-name text uses), so the two
    # rules below are effectively "the header row" now, not "every day's own label".
    ".day.header .date .text { display: block; font-size: 1.15em !important; "
    "font-weight: 600 !important; letter-spacing: .02em !important; text-align: center "
    "!important; color: #6b6b6b !important; } "
    ".day.header { border-bottom: 2px solid rgba(0,0,0,0.08) !important; padding-bottom: "
    "6px !important; margin-bottom: 4px !important; } "
    # 2026-07-26: shrunk once to a muted 1.1em/600-weight/#767676 right after adding the
    # Skylight-style header row above (this comment's own earlier revision), then explicitly
    # reverted bigger/bolder/darker than even the original 1.6em on direct live feedback - the
    # header row change didn't reduce how prominent the number itself should be, despite that
    # having been this file's own working assumption. `.today .number`'s own highlight below
    # is unaffected (its own color/background/padding still take precedence).
    ".day .date .number { font-weight: 700 !important; font-size: 1.8em !important; "
    "color: #1a1a1a !important; } "
    ".today .number { border-radius: 6px !important; background-color: #ff9800 !important; "
    "color: white !important; padding: 0 5px !important; } "
    # 2026-08-02, kiosk-fit experiment: live-caught real bug - `maxDayEvents` (see
    # `_WEEK_PLANNER_STATIC_OPTIONS`) only caps how many events RENDER, not how tall they make
    # the cell; a day with several title-only pills stacked (still ~2-3 lines each once
    # spacing/padding are counted) grew that day's `.events` box taller than every other day in
    # its row - and since day cells sit in a wrapping FLEX row (`.container .day` - no CSS
    # grid, no per-row fixed height), every day in that same calendar row stretches to match the
    # tallest one, pushing every row below it down and off the bottom of the fixed-height card
    # (confirmed live: the last row silently scrolled out of view). Capping `.events` itself to
    # a fixed height with its own internal scroll keeps EVERY day cell - hence every row, hence
    # the whole grid - a deterministic height regardless of any single day's event count; a busy
    # day scrolls internally instead of resizing its neighbors. Went through two wrong guesses
    # before landing on a live-MEASURED value (Playwright `getBoundingClientRect`, not
    # eyeballing a screenshot): 78px, then 84px, both still clipped something mid-element
    # because the real driver of pill height turned out to be `--event-padding` (see this
    # file's own `--event-padding` override above), not text wrapping or pill count as first
    # assumed. With that fixed, a title-only pill measures 33px and the "+N more" label 21px -
    # `96px` fits `maxDayEvents: 2` (see `_WEEK_PLANNER_STATIC_OPTIONS`) worth of whole pills
    # PLUS a fully-visible "more" label (33+33+21+2*3px gaps = 93px + a few px breathing room),
    # so a busy day never needs its own internal scroll in practice - the `overflow-y: auto`
    # below is now a pure safety net (e.g. a title too long to ellipsize into the pill's own
    # width some other way) rather than the primary mechanism.
    ".day .events { max-height: 96px !important; overflow-y: auto !important; "
    "overflow-x: hidden !important; } "
    ".event { color: #222 !important; background-color: var(--border-color) !important; "
    "border-radius: 8px !important; padding: 3px 6px !important; "
    "max-width: 100% !important; box-sizing: border-box !important; } "
    ".event.past { opacity: .35 !important; } "
    # 2026-08-02, kiosk-fit experiment: title-only events (`showLocation`/`showDescription`
    # both off in `_WEEK_PLANNER_STATIC_OPTIONS` now - tap-to-see-everything-else is
    # week-planner-card's own built-in event-click details dialog, unchanged, nothing new
    # needed for that part). `.time` has no card-option equivalent to turn off, only a CSS
    # hide - with it and location/description gone there's headroom to size the remaining
    # title text up for kiosk legibility.
    ".event .time { display: none !important; } "
    # `white-space`/`overflow`/`text-overflow` added after live-measuring the actual DOM
    # (Playwright `getBoundingClientRect`, not eyeballing a screenshot): an unconstrained
    # title wraps to 2 lines for anything longer than a few words, making a pill ~49px tall
    # instead of the ~32px a single line needs - which is what actually blew the `.day .events`
    # max-height budget below, not the pill count. Forcing a single ellipsized line makes
    # every pill's height predictable regardless of title length, which the fixed max-height
    # below depends on to fit a known number of whole pills.
    ".event .title { font-size: 1.3em !important; font-weight: 600 !important; "
    "line-height: 1.25 !important; white-space: nowrap !important; overflow: hidden "
    "!important; text-overflow: ellipsis !important; } "
    # Live-reported real bug: showLocation (this module's own choice, see
    # _WEEK_PLANNER_STATIC_OPTIONS) renders event.location as a plain, unconstrained
    # `.location` div with no override of its own in week-planner-card's own CSS - fine for
    # ordinary addresses (they wrap normally at spaces/commas), but a video-call URL has no
    # word-break opportunities at all, so the browser let it overflow horizontally straight
    # into the NEXT day's column instead of wrapping within its own cell. `overflow-wrap:
    # anywhere` (word-break: break-word as an older-browser fallback) forces a break inside
    # an unbreakable run of characters when nothing else fits, same as `max-width: 100%`
    # above on `.event` itself guarantees the whole pill can never grow past its own day
    # cell's width in the first place, regardless of what's inside it.
    ".location { overflow-wrap: anywhere !important; word-break: break-word !important; "
    "max-width: 100% !important; } "
    ".none { background-color: transparent !important; color: #9aa0a6 !important; "
    "box-shadow: none !important; border: none !important; }"
)

_WEEK_PLANNER_STATIC_OPTIONS = {
    "showNavigation": True,
    # 2026-08-02, kiosk-fit experiment (EXPERIMENTAL): title-only day cells - full event
    # details (time/location/description) now only ever appear in week-planner-card's own
    # built-in tap-to-open details dialog (`_handleEventClick`/`_renderEventDetailsDialog` in
    # the card's own source - already there, unused by this grid until now since the grid
    # itself showed everything inline before). `showTitle` is the card's own default (True)
    # but set explicitly here since it's now the ONLY thing this grid shows.
    "showTitle": True,
    "showDescription": False,
    "showLocation": False,
    # Caps events rendered per day before falling back to a static "+N more" label (see the
    # card's own `_renderEvents` - the label isn't clickable, just an indicator) - without
    # this, one unusually busy day can still push its whole row taller than the fixed
    # `calc(100vh - ...)` box `_CARD_MOD_STYLE` now constrains the card to, regardless of that
    # container's own sizing. 2 (not the first guess of 3) to match `.day .events`'s own
    # `max-height` in `_CARD_MOD_STYLE`, sized to fit exactly 2 whole pills - live-caught
    # follow-up bug: 3 allowed pills into a box only sized for ~2, so the 3rd rendered pill got
    # sliced off mid-word instead of cleanly folding into "+N more". Still a guess pending
    # further live tuning, not a measured number.
    "maxDayEvents": 2,
    "combineSimilarEvents": True,
    "hidePastEvents": False,
    "compact": False,
    # False (not the card's own default of True) is what actually turns on its top
    # weekday-header-ROW layout instead of an inline label on every individual day cell -
    # see _CARD_MOD_STYLE's own comment on the Skylight-inspired redesign this is part of.
    "showWeekDayText": False,
}

# Our OWN computed entity (modules/calendar/birthdays.py) - not an external "Birthdays"
# integration (HA has no built-in one, confirmed against the installed source).
BIRTHDAYS_ENTITY_ID = "calendar.family_dashboard_birthdays"

# HA's built-in "Holiday" integration (`homeassistant.components.holiday`) - auto-provisioned
# for US + Philippines by `holidays_setup.py`, but detected generically here (any Holiday
# config entry's own calendar entity, not one hardcoded country) so a user-added additional
# country shows up too, with no code change needed.
_HOLIDAY_INTEGRATION_DOMAIN = "holiday"

_FAMILY_CALENDAR_SHOWN_ENTITY_ID = "switch.family_dashboard_family_calendar_shown"

# Name family members use for their household's shared calendar (e.g. a Google Calendar
# literally named "Family", shared to everyone). Matched case-insensitively against every
# calendar.* entity's own name - not tied to any roster member's own mapping (see this
# module's docstring's "Family calendar" bullet - replaces the earlier
# CONF_FAMILY_CALENDAR_MEMBER_ID member-flagging design, which forced giving up a member's
# own personal calendar slot to host it).
_FAMILY_CALENDAR_NAME = "family"

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


def _overlay_entries(hass: HomeAssistant) -> list[dict]:
    """Family/Birthdays/Holidays calendar entries, only for ones that actually exist on this
    HA instance - Birthdays is our own always-created entity (see `modules/calendar/
    birthdays.py`), Holidays is however many Holiday integration entries currently exist.

    2026-07-25: Birthdays and Holidays are now ALWAYS shown, no toggle pill, no `filter` key
    at all (a live request - "always display Holidays/Birthdays as we currently do, but
    remove the button completely"; Birthdays stays the existing computed entity, not events
    written into the Family calendar - the safer of two options presented, since writing real
    events into an external calendar would need its own create/update/delete sync logic
    against that calendar whenever a birthdate changes or a member is removed). Family
    calendar's own toggle is UNCHANGED - only Birthdays/Holidays lost their buttons.

    IMPORTANT - `filter` is an EXCLUSION regex, not an inclusion one: live-verified directly
    against the installed `week-planner-card.js` source (`_isFilterEvent`/its one call site in
    `_updateEvents`), an event whose summary MATCHES `calendars[i].filter` is SKIPPED (hidden),
    not shown. So a toggleable "shown" (switch on) must use `'^$'` (matches nothing real ->
    nothing excluded -> everything shown) - omitting `filter` entirely (as Birthdays/Holidays
    now do) has the same "nothing excluded" effect, permanently. A live user report
    ("Birthdays only shows when the pill is gray/off") caught the inverted-regex version of
    this bug originally - pytest alone couldn't, since it only ever asserted the generated
    STRING content, never how the third-party card actually interprets it."""
    entries = []
    family_calendar = _family_calendar_entity(hass)
    if family_calendar is not None:
        entity_id, name = family_calendar
        entries.append({
            "entity": entity_id,
            "name": name,
            "color": "#6366F1",
            "filter": (
                f"${{ states['{_FAMILY_CALENDAR_SHOWN_ENTITY_ID}']?.state === 'on' "
                "? '^$' : '.*' }"
            ),
        })

    if hass.states.get(BIRTHDAYS_ENTITY_ID) is not None:
        entries.append({"entity": BIRTHDAYS_ENTITY_ID, "name": "Birthdays", "color": "#33a02c"})

    for entity_id, name in _holiday_calendar_entities(hass):
        entries.append({"entity": entity_id, "name": name, "color": "#ff7f00"})
    return entries


def async_kiosk_calendar_card(hass: HomeAssistant, members: list[dict]) -> dict | None:
    """The Kiosk bucket's calendar card - every given member's calendar always listed, each
    one's visibility toggled by its own `switch.family_dashboard_<id>_shown` state, plus
    Family (toggleable)/Birthdays/Holidays (always shown, no toggle - see `_overlay_entries`'s
    docstring) if they exist. `days`/`startingDay` are fixed to week-planner-card's own
    `"month"` mode (see this module's docstring). Returns None if none of the given members
    have a mapped calendar AND neither overlay exists - the caller omits the card entirely
    rather than showing an empty grid.
    """
    calendar_members = [m for m in members if _member_has_calendar(m)]
    overlays = _overlay_entries(hass)
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

    return {
        "type": "custom:config-template-card",
        "entities": toggle_entities,
        "card": {
            "type": "custom:week-planner-card",
            "calendars": calendars,
            "days": "month",
            "startingDay": "sunday",
            **_WEEK_PLANNER_STATIC_OPTIONS,
            "card_mod": {"style": _CARD_MOD_STYLE},
        },
    }


async def async_calendar_view_card(
    hass: HomeAssistant, entry: ConfigEntry, members: list[dict]
) -> dict | None:
    """One week-planner-card listing every given member's mapped calendar proxy entity,
    color-coded to their roster color, plus Family (toggleable)/Birthdays/Holidays (always
    shown, no toggle) - used for a personal bucket's Calendar tab. Returns None if there's
    nothing at all to show.

    Family's toggle uses the SAME shared switch the Kiosk bucket's card uses
    (`dashboard/registry.py`'s `_personal_calendar_cards` wires in the matching toggle pill) -
    unlike per-member calendars, which still have no per-member toggle in a personal bucket
    (nothing to filter, there's only ever one or two calendars shown here).

    `days`/`startingDay` are fixed to week-planner-card's own `"month"` mode, same as the
    Kiosk bucket's own card (see this module's docstring) - a single, config-entry-wide
    setting, not per-viewer.
    """
    calendars = [
        {
            "entity": f"calendar.family_dashboard_{member['member_id']}_calendar",
            "name": member["name"],
            "color": _member_color_hex(member),
        }
        for member in members
        if _member_has_calendar(member)
    ] + _overlay_entries(hass)
    if not calendars:
        return None

    toggle_entities = []
    if _family_calendar_entity(hass) is not None:
        toggle_entities.append(_FAMILY_CALENDAR_SHOWN_ENTITY_ID)

    return {
        "type": "custom:config-template-card",
        "entities": toggle_entities,
        "card": {
            "type": "custom:week-planner-card",
            "calendars": calendars,
            "days": "month",
            "startingDay": "sunday",
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
                # 13px -> 16px (2026-07-20 kiosk legibility pass) - see registry.py's
                # `_pill_styles` for why every "52px pill, tiny name text" spot got the same
                # bump for a 1920x1080 15" kiosk panel.
                {"font-size": "16px"},
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
    `async_member_toggle_pills` and `async_family_calendar_toggle_pill` build on this one
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
            # 14px -> 16px (2026-07-20 kiosk legibility pass) - see registry.py's
            # `_pill_styles` for why.
            {"font-size": "16px"},
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


def async_family_calendar_toggle_pill(hass: HomeAssistant) -> list[dict]:
    """Toggle-filter pill for the Family calendar overlay - used on BOTH the Kiosk bucket's
    and every personal bucket's Calendar tab (see `dashboard/registry.py`'s
    `_kiosk_calendar_cards`/`_personal_calendar_cards`), same shared pill styling as member
    toggles (`_toggle_pill_base_styles`/`_fixed_toggle_pill`). Returns an empty list if no
    Family calendar is currently detected.

    2026-07-25: renamed from `async_birthdays_holidays_toggle_pills` and dropped the
    Birthdays/Holidays pills entirely - a live request ("always display Holidays/Birthdays as
    we currently do, but remove the button completely"). Those two overlays are still added
    to the calendar grid itself (`_overlay_entries`), just permanently shown with nothing to
    toggle - only Family kept its button, hence the rename (the old name was actively
    misleading once it stopped producing any Birthdays/Holidays pill at all)."""
    if _family_calendar_entity(hass) is None:
        return []
    return [
        _fixed_toggle_pill(_FAMILY_CALENDAR_SHOWN_ENTITY_ID, "Family", "mdi:home-heart", "#6366F1")
    ]


def async_add_event_popup_card() -> dict:
    """The Add Event pop-up - ports `dashboards/family-hub.yaml` lines ~503-563's proven
    structure (plain entities card + all-day/timed conditional cards + submit button) onto
    this integration's own owned scratch entities instead of `input_*` helpers.

    2026-07-26: Start/End is back to v0.9.0-beta.4's layout - a single combined `datetime`
    row per side (native HA date+time more-info picker, one tap sets both), conditional on
    All Day being off; Start/End Date is its own separate conditional block (all-day only)
    rather than a row shared between both branches. This reverts the 2026-07-25 decomposed
    Date+Hour+Minute+AM-PM redesign - a live report called that "far too many clicks and
    opens sub windows to enter hour, days, etc". A same-day intermediate version added a
    separate explicit AM/PM select per side to "correct" the native picker's stored value -
    removed a few hours later once live-verified (against HA's own frontend source) that the
    native picker already resolves to a correct, unambiguous absolute time regardless of the
    viewer's 12-vs-24-hour account setting, making that select pure redundant duplication; see
    `event_time.py`'s docstring for the full reasoning. Recurring follows the exact same
    "switch + conditional card" shape as All Day Event (a live request), revealing the
    Recurrence preset picker only when on.
    """
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
                    {"entity": "switch.family_dashboard_event_recurring", "name": "Recurring?"},
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
                "type": "conditional",
                "conditions": [{"entity": "switch.family_dashboard_event_recurring", "state": "on"}],
                "card": {
                    "type": "entities",
                    "entities": [
                        {"entity": "select.family_dashboard_event_recurrence", "name": "Repeats"},
                    ],
                },
            },
            {
                "type": "entities",
                "title": "Remind me",
                "entities": [
                    {
                        "entity": "number.family_dashboard_event_remind_weeks_before",
                        "name": "Weeks Before",
                    },
                    {
                        "entity": "number.family_dashboard_event_remind_days_before",
                        "name": "Days Before",
                    },
                    {
                        "entity": "number.family_dashboard_event_remind_hours_before",
                        "name": "Hours Before",
                    },
                    {
                        "entity": "number.family_dashboard_event_remind_minutes_before",
                        "name": "Minutes Before",
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
