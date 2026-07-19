"""Config flow for Family Dashboard.

Steps, in order:
  1. `user`          - roster names (comma-separated), collected once for the whole
                        household. Always-on: Settings/Roster is core, not a toggleable
                        feature (see const.py).
  2. Per-member loop  - `colors` -> `avatars` -> `birthdates` -> `features` -> `link_users`
                        -> (conditionally) `calendar` -> (conditionally) `lists`, ONE SCREEN
                        PER FIELD PER ROSTER MEMBER, repeated once per member in roster order
                        (`self._member_index` tracks which one), before moving on to the next
                        member. NOT one flat form covering the whole roster at once (that was
                        the original design - reverted 2026-07-18, live-reported as genuinely
                        confusing: nothing on a flat multi-member form said which row belonged
                        to which person, which is exactly how the old "Also use as the shared
                        Family calendar" checkbox went unnoticed. HA's config-flow API has no
                        per-field/per-section dynamic text, only a step's own
                        `description_placeholders` - so one-screen-per-member, naming that
                        member in the description, is the only real fix; it's the same
                        pattern `FamilyDashboardOptionsFlow`'s own "add a member" sub-flow
                        already used below, just looped over the whole initial roster instead
                        of a single new member). More screens for a larger family, but each
                        one is unambiguous.
       - `colors`       - one color picker for the current member.
       - `avatars`      - one avatar picker, options built from whatever's actually in
                           `/config/www/family_dashboard/avatars/` at the moment (seeded on
                           demand via `assets.async_seed_assets`, which needs only `hass` -
                           not a live config entry, so this works even during initial setup
                           before one exists). A plain dropdown, not the Settings dashboard's
                           picture-grid popup - config-flow forms can't render a custom
                           Lovelace-style picker (same platform limitation already accepted
                           for the `colors` step's own plain dropdown).
       - `birthdates`   - one optional date picker (skippable - not everyone has to provide
                           one). Powers the computed `calendar.family_dashboard_birthdays`
                           overlay (see `modules/calendar/birthdays.py`).
       - `features`     - which of Calendar / Lists / Chores & Rewards THIS member wants (see
                           const.py's FEATURES docstring) - drives whether `calendar`/`lists`
                           get shown at all for them, below.
       - `link_users`   - optionally link this member to an existing HA user account (a
                           `select` selector populated from `hass.auth.async_get_users()` -
                           HA core has no generic "user" selector type to build this on),
                           excluding any HA user an earlier member in this same wizard run
                           already linked to. Lets the dashboard tell "the person looking at
                           this right now" apart from everyone else. Skippable.
       - `calendar`     - ONLY shown if this member selected "calendar". If no `calendar.*`
                           entities exist anywhere yet, shows `calendar_none_found` instead
                           (instructions + continue, no fields, shown at MOST ONCE per wizard
                           run even with multiple calendar-opted members - never holds the
                           flow open waiting for external OAuth setup). Otherwise two optional
                           selectors (map an existing calendar entity, map a notify entity for
                           reminders). No "shared Family calendar" field here - that's
                           auto-detected by calendar name instead of member-flagged, see
                           `modules/calendar/dashboard.py`'s `_family_calendar_entity`.
       - `lists`        - ONLY shown if this member selected "lists". One preset multi-select
                           (see build_lists_schema).
  3. `add_chore`      - ONLY shown once every member's own loop above has finished, and only
                        if at least one roster member selected "chores". A repeat-until-done
                        loop: one "add a chore" form (name/points/frequency/assigned-to),
                        re-shown blank after each submission: leaving `name` blank ends the
                        loop (not a separate yes/no step - see the function's docstring).
                        Chains to `add_reward` when done. Household-scoped, not per-member -
                        unaffected by the per-member restructuring above.
  4. `add_reward`     - same repeat-until-done shape as `add_chore` (name/cost/assigned-to, no
                        frequency), also gated on any member's "chores" selection (Rewards
                        has no separate feature toggle).
  5. `confirm`        - summary of what's about to be created; submitting creates the config
                        entry.

The per-step schema-building/input-parsing logic (`build_*_schema`/`parse_*_input` below) is
written as plain module-level functions, not methods only `FamilyDashboardConfigFlow` can
call - `FamilyDashboardOptionsFlow` needs the exact same forms, pre-filled from an existing
config entry's data instead of blank, and calls these same functions rather than duplicating
them. They already accept a single-member `[name]` list (that's exactly how the Options
Flow's "add a member" sub-flow has always called them) - the initial wizard's move to
one-member-per-screen needed ZERO changes to these functions, only to how
`FamilyDashboardConfigFlow`'s own step handlers call them.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import selector

from .assets import async_seed_assets
from .const import (
    CHORE_FREQUENCIES,
    COLOR_OPTIONS,
    CONF_AVATAR,
    CONF_BIRTHDATE,
    CONF_CALENDAR_ENTITY_ID,
    CONF_CHORES,
    CONF_FEATURES,
    CONF_HA_USER_ID,
    CONF_LIST_PRESETS,
    CONF_NOTIFY_ENTITY_ID,
    CONF_REWARDS,
    CONF_ROSTER,
    DEFAULT_SELECTED_FEATURES,
    DOMAIN,
    FEATURES,
    LIST_PRESETS,
    ROSTER_MAX_MEMBERS,
)
from .modules.chores.crud import UNASSIGNED_OPTION
from .util import ddmmyyyy_to_iso, iso_to_ddmmyyyy, slugify_unique


def _split_roster(raw: str) -> list[str]:
    names = [n.strip() for n in raw.split(",") if n.strip()]
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(name)
    return deduped[:ROSTER_MAX_MEMBERS]


def _color_field(idx: int) -> str:
    return f"color_{idx}"


def _features_field(idx: int) -> str:
    return f"features_{idx}"


def _ha_user_field(idx: int) -> str:
    return f"ha_user_{idx}"


def _presets_field(idx: int) -> str:
    return f"presets_{idx}"


def _calendar_field(idx: int) -> str:
    return f"calendar_{idx}"


def _notify_field(idx: int) -> str:
    return f"notify_{idx}"


def build_colors_schema(
    roster_names: list[str], prior_colors: dict[str, str] | None = None
) -> vol.Schema:
    """One color picker per roster member, one screen. `prior_colors` (member name ->
    color), when given, pre-fills each row instead of using the rotating default - used by
    the future Options Flow to show current values instead of a blank form.
    """
    prior_colors = prior_colors or {}
    schema_dict: dict[Any, Any] = {}
    for idx, name in enumerate(roster_names):
        default = prior_colors.get(name, COLOR_OPTIONS[idx % len(COLOR_OPTIONS)])
        schema_dict[vol.Required(_color_field(idx), default=default)] = selector(
            {"select": {"options": COLOR_OPTIONS}}
        )
    return vol.Schema(schema_dict)


def parse_colors_input(user_input: dict[str, Any], roster_names: list[str]) -> dict[str, str]:
    return {name: user_input[_color_field(idx)] for idx, name in enumerate(roster_names)}


def _avatar_field(idx: int) -> str:
    return f"avatar_{idx}"


def _avatar_label(path: str) -> str:
    """A human-readable label for an avatar file path (e.g.
    "/local/family_dashboard/avatars/people-group-solid.png" -> "People Group") - the
    dropdown shows this, not the raw path; falls back gracefully for any custom filename
    someone drops into the avatars folder later, not just the two shipped defaults."""
    filename = path.rsplit("/", 1)[-1]
    stem = filename[:-4] if filename.lower().endswith(".png") else filename
    if stem.endswith("-solid"):
        stem = stem[: -len("-solid")]
    return stem.replace("-", " ").replace("_", " ").title() or path


def build_avatars_schema(
    roster_names: list[str],
    avatar_options: list[str],
    prior_avatars: dict[str, str] | None = None,
) -> vol.Schema:
    """One avatar picker per roster member, one screen - same rotating-default shape as
    `build_colors_schema` (each member defaults to a different avatar when more than one is
    available, rather than everyone defaulting to the same picture). `avatar_options` is the
    live list of `/local/family_dashboard/avatars/*.png` paths (see `assets.async_seed_assets`
    - called by the caller, not here, since seeding needs an `await`). `prior_avatars` (member
    name -> path), when given, pre-fills each row - used by the Options Flow's Add Member
    step, matching `build_colors_schema`'s own shape.
    """
    prior_avatars = prior_avatars or {}
    options = [{"value": path, "label": _avatar_label(path)} for path in avatar_options]
    schema_dict: dict[Any, Any] = {}
    for idx, name in enumerate(roster_names):
        default = prior_avatars.get(name) or (
            avatar_options[idx % len(avatar_options)] if avatar_options else None
        )
        key = (
            vol.Required(_avatar_field(idx), default=default)
            if default
            else vol.Required(_avatar_field(idx))
        )
        schema_dict[key] = selector({"select": {"options": options}})
    return vol.Schema(schema_dict)


def parse_avatars_input(user_input: dict[str, Any], roster_names: list[str]) -> dict[str, str]:
    return {name: user_input[_avatar_field(idx)] for idx, name in enumerate(roster_names)}


def _birthdate_field(idx: int) -> str:
    return f"birthdate_{idx}"


def build_birthdates_schema(
    roster_names: list[str], prior_birthdates: dict[str, str] | None = None
) -> vol.Schema:
    """One OPTIONAL DD/MM/YYYY text field per roster member, one screen - unlike colors,
    there's no rotating default; a member simply may not have a birthdate on file. Format
    validation happens in `parse_birthdates_input` (via `util.ddmmyyyy_to_iso`), not here:
    `voluptuous_serialize` - which HA's own `async_show_form` uses to hand the schema to the
    frontend - cannot serialize an arbitrary custom validator function at all (confirmed live:
    raises `Unable to convert schema` the moment the screen tries to RENDER, not merely on bad
    input, breaking the step every time it's shown). This field is therefore a bare `str` (HA's
    own `TYPES_MAP` handles that natively) with no format enforcement at the schema level.

    Live-reported gap this whole field replaces: HA's built-in `date` selector (used here
    originally) is popup-only with no way to type a date directly, and its calendar grid has
    no year-jump - confirmed by reading `DateSelectorConfig`'s source (zero configurable
    options) and live-testing the popup itself (the small icon next to the month header does
    NOT open a year list, contrary to typical Material date pickers). Going from 2026 back to
    a 1970s-80s birthdate was ~500 "previous month" clicks. `CONF_BIRTHDATE`'s storage
    contract (ISO date string) and every downstream consumer
    (`modules/calendar/birthdays.py`'s `date.fromisoformat`, the roster `date` entity, and the
    Settings tab's own birthdate-edit popup - see `modules/settings/date.py`) needed no
    changes - only entry into this one field changed. `prior_birthdates` (member name -> ISO
    date string), when given, pre-fills each row (converted to DD/MM/YYYY for display) - used
    by the Options Flow's Add Member step, matching `build_colors_schema`'s own shape.
    """
    prior_birthdates = prior_birthdates or {}
    schema_dict: dict[Any, Any] = {}
    for idx, name in enumerate(roster_names):
        default = prior_birthdates.get(name)
        key = (
            vol.Optional(_birthdate_field(idx), default=iso_to_ddmmyyyy(default))
            if default
            else vol.Optional(_birthdate_field(idx))
        )
        schema_dict[key] = str
    return vol.Schema(schema_dict)


def parse_birthdates_input(
    user_input: dict[str, Any], roster_names: list[str]
) -> dict[str, str | None]:
    """Raises `util.InvalidBirthdateText` if any member's typed text isn't a valid DD/MM/YYYY
    date - callers catch this and re-show the form with an error (same pattern
    `async_step_user`'s `roster_empty` check already uses)."""
    return {
        name: ddmmyyyy_to_iso(user_input.get(_birthdate_field(idx)))
        for idx, name in enumerate(roster_names)
    }


def build_features_schema(
    roster_names: list[str], prior_features: dict[str, list[str]] | None = None
) -> vol.Schema:
    """One features multi-select per roster member, one screen - mirrors `build_colors_schema`'s
    one-screen-many-fields pattern so wizard length doesn't scale with roster size.
    `prior_features` (member name -> selected feature keys), when given, pre-fills each row.
    """
    prior_features = prior_features or {}
    options = {key: feat["name"] for key, feat in FEATURES.items()}
    schema_dict: dict[Any, Any] = {}
    for idx, name in enumerate(roster_names):
        default = prior_features.get(name, DEFAULT_SELECTED_FEATURES)
        schema_dict[vol.Required(_features_field(idx), default=default)] = cv.multi_select(
            options
        )
    return vol.Schema(schema_dict)


def parse_features_input(
    user_input: dict[str, Any], roster_names: list[str]
) -> dict[str, list[str]]:
    return {name: user_input[_features_field(idx)] for idx, name in enumerate(roster_names)}


def build_link_users_schema(
    roster_names: list[str],
    user_options: list[dict[str, str]],
    prior_ha_user_ids: dict[str, str | None] | None = None,
) -> vol.Schema:
    """One optional HA-user picker per roster member, one screen. `user_options` is a list
    of `{"value": user_id, "label": user_name}` dicts for real HA user accounts - fetched by
    the caller via `hass.auth.async_get_users()` (see `async_step_link_users`), since HA core
    has NO reusable "user" selector type (checked against `homeassistant.helpers.selector`'s
    registered SELECTORS - it isn't there); a plain `select` selector populated with the
    real account list is the standard way integrations do this themselves.

    Each field is `vol.Optional` with NO `default=` - voluptuous then simply omits the key
    from `user_input` if the user leaves it blank, so `parse_link_users_input` can read it
    back with `.get(...)` and cleanly get `None` for "skipped." (Deliberately not
    `default=None`: HA's `default=` on a selector silently re-applies itself if a user tries
    to clear a previously-set value, which matters once the future Options Flow lets someone
    unlink a member - `description={"suggested_value": ...}` is the correct prefill
    mechanism for that case instead, used below when `prior_ha_user_ids` has a value.)
    """
    prior_ha_user_ids = prior_ha_user_ids or {}
    schema_dict: dict[Any, Any] = {}
    for idx, name in enumerate(roster_names):
        prior = prior_ha_user_ids.get(name)
        field = (
            vol.Optional(_ha_user_field(idx), description={"suggested_value": prior})
            if prior is not None
            else vol.Optional(_ha_user_field(idx))
        )
        schema_dict[field] = selector(
            {"select": {"options": user_options, "mode": "dropdown"}}
        )
    return vol.Schema(schema_dict)


def parse_link_users_input(
    user_input: dict[str, Any], roster_names: list[str]
) -> dict[str, str | None]:
    return {name: user_input.get(_ha_user_field(idx)) for idx, name in enumerate(roster_names)}


def build_calendar_schema(
    calendar_members: list[str],
    prior: dict[str, tuple[str | None, str | None]] | None = None,
) -> vol.Schema:
    """Two optional selectors per roster member who opted into "calendar" - a FILTERED subset
    of the full roster (like build_lists_schema), so field indices correspond to positions in
    `calendar_members`, not the full roster. Real `entity` selectors scoped by domain
    (confirmed present in HA's SELECTORS registry, unlike the nonexistent "user" one step 0
    had to work around) - map an existing calendar entity and, independently, a notify entity
    for reminders; either or both can be left blank. `prior` (member name ->
    (calendar_entity_id, notify_entity_id)) pre-fills rows for the Options Flow.

    No "shared Family calendar" field here anymore - that's auto-detected by calendar name
    (see `modules/calendar/dashboard.py`'s `_family_calendar_entity`), not member-flagged. The
    checkbox this used to have was a live-reported source of confusion (indistinguishable from
    which roster member's row it belonged to in a flat multi-member form) on top of forcing a
    user to give up one member's own personal calendar slot to host it.
    """
    prior = prior or {}
    schema_dict: dict[Any, Any] = {}
    for idx, name in enumerate(calendar_members):
        prior_cal, prior_notify = prior.get(name, (None, None))
        cal_field = (
            vol.Optional(_calendar_field(idx), description={"suggested_value": prior_cal})
            if prior_cal is not None
            else vol.Optional(_calendar_field(idx))
        )
        notify_field = (
            vol.Optional(_notify_field(idx), description={"suggested_value": prior_notify})
            if prior_notify is not None
            else vol.Optional(_notify_field(idx))
        )
        schema_dict[cal_field] = selector({"entity": {"domain": "calendar"}})
        schema_dict[notify_field] = selector({"entity": {"domain": "notify"}})
    return vol.Schema(schema_dict)


def parse_calendar_input(
    user_input: dict[str, Any], calendar_members: list[str]
) -> dict[str, tuple[str | None, str | None]]:
    """Per-member (calendar_entity_id, notify_entity_id) mapping."""
    return {
        name: (user_input.get(_calendar_field(idx)), user_input.get(_notify_field(idx)))
        for idx, name in enumerate(calendar_members)
    }


def build_lists_schema(
    list_members: list[str], prior_presets: dict[str, list[str]] | None = None
) -> vol.Schema:
    """One list-preset multi-select per roster member who opted into "lists" - a FILTERED
    subset of the full roster, not everyone (unlike colors/features/link_users), so its
    field indices (`presets_0`, `presets_1`, ...) correspond to positions in `list_members`,
    not the full roster. Defaults to an empty selection per row (unlike features, which
    defaults everything on) - which specific lists someone wants is an affirmative choice,
    not an on-by-default capability.
    """
    prior_presets = prior_presets or {}
    options = {key: preset["name"] for key, preset in LIST_PRESETS.items()}
    schema_dict: dict[Any, Any] = {}
    for idx, name in enumerate(list_members):
        default = prior_presets.get(name, [])
        schema_dict[vol.Required(_presets_field(idx), default=default)] = cv.multi_select(
            options
        )
    return vol.Schema(schema_dict)


def parse_lists_input(
    user_input: dict[str, Any], list_members: list[str]
) -> dict[str, list[str]]:
    return {name: user_input[_presets_field(idx)] for idx, name in enumerate(list_members)}


class FamilyDashboardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Family Dashboard wizard."""

    VERSION = 1

    def __init__(self) -> None:
        self._roster_names: list[str] = []
        self._roster_colors: dict[str, str] = {}
        self._roster_avatars: dict[str, str] = {}
        self._roster_birthdates: dict[str, str | None] = {}
        self._roster_features: dict[str, list[str]] = {}
        self._roster_ha_user_ids: dict[str, str | None] = {}
        self._roster_calendar: dict[str, tuple[str | None, str | None]] = {}
        self._roster_list_presets: dict[str, list[str]] = {}
        self._chores: list[dict] = []
        self._rewards: list[dict] = []
        # Which roster member Colors-through-Lists is currently walking through - every
        # multi-member step got converted from one flat all-at-once form to one screen per
        # member (2026-07-18, live-reported: a flat form gives no on-screen indication of
        # which row belongs to which person - HA's config-flow API has no per-field/per-
        # section dynamic text, only a step's own description, so one-screen-per-member,
        # already proven by the Options Flow's own "add a member" sub-flow below, is the only
        # real fix). More screens/clicks for a larger roster, but each one is unambiguous.
        self._member_index: int = 0
        # Shown at most once per wizard run, not once per calendar-opted member - see
        # `async_step_calendar_none_found`.
        self._calendar_none_found_shown: bool = False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        # Not forwarded to the constructor - `config_entry` is a read-only property on the
        # base `OptionsFlow` class now, wired up by the flow manager itself after
        # construction (see `FamilyDashboardOptionsFlow.__init__`'s docstring).
        return FamilyDashboardOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            roster = _split_roster(user_input[CONF_ROSTER])
            if not roster:
                errors["base"] = "roster_empty"
            else:
                # Only one Family Dashboard instance makes sense per HA install.
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                self._roster_names = roster
                return await self.async_step_colors()

        schema = vol.Schema({vol.Required(CONF_ROSTER, default="Personal, Family"): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_colors(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        name = self._roster_names[self._member_index]
        if user_input is not None:
            self._roster_colors[name] = parse_colors_input(user_input, [name])[name]
            return await self.async_step_avatars()

        return self.async_show_form(
            step_id="colors",
            data_schema=build_colors_schema([name]),
            description_placeholders={"name": name},
        )

    async def async_step_avatars(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        name = self._roster_names[self._member_index]
        if user_input is not None:
            self._roster_avatars[name] = parse_avatars_input(user_input, [name])[name]
            return await self.async_step_birthdates()

        # Needs only `hass`, not a live config entry - safe to call before one exists (see
        # this module's own docstring for the `avatars` step).
        avatar_options = await async_seed_assets(self.hass)
        return self.async_show_form(
            step_id="avatars",
            data_schema=build_avatars_schema([name], avatar_options),
            description_placeholders={"name": name},
        )

    async def async_step_birthdates(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        name = self._roster_names[self._member_index]
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._roster_birthdates[name] = parse_birthdates_input(user_input, [name])[
                    name
                ]
                return await self.async_step_features()
            except ValueError:
                errors["base"] = "invalid_birthdate"

        return self.async_show_form(
            step_id="birthdates",
            data_schema=build_birthdates_schema([name]),
            description_placeholders={"name": name},
            errors=errors,
        )

    async def async_step_features(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        name = self._roster_names[self._member_index]
        if user_input is not None:
            self._roster_features[name] = parse_features_input(user_input, [name])[name]
            return await self.async_step_link_users()

        return self.async_show_form(
            step_id="features",
            data_schema=build_features_schema([name]),
            description_placeholders={"name": name},
        )

    async def async_step_link_users(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        name = self._roster_names[self._member_index]
        if user_input is not None:
            self._roster_ha_user_ids[name] = parse_link_users_input(user_input, [name])[name]
            return await self._async_step_after_link_user()

        # Real, human-linkable accounts only - excludes system-generated users (e.g. the
        # internal HTTP/Supervisor accounts) the same way the frontend's own person-linking
        # UI does, since those aren't accounts a family member actually logs in as. Also
        # excludes any HA user an EARLIER member in this same wizard run already linked to -
        # falls out for free from walking members one at a time now, matching the exclusion
        # the Options Flow's own `async_step_add_link_user` already had (nothing stopped two
        # different rows from picking the same HA user in the old flat all-at-once form).
        already_linked = {uid for uid in self._roster_ha_user_ids.values() if uid}
        users = await self.hass.auth.async_get_users()
        user_options = [
            {"value": user.id, "label": user.name or user.id}
            for user in users
            if user.is_active and not user.system_generated and user.id not in already_linked
        ]
        return self.async_show_form(
            step_id="link_users",
            data_schema=build_link_users_schema([name], user_options),
            description_placeholders={"name": name},
        )

    async def _async_step_after_link_user(self) -> config_entries.FlowResult:
        """Chain to `calendar` (or `calendar_none_found`) only if the CURRENT member opted
        into "calendar" - straight to `_async_step_after_calendar` otherwise. Per-member
        version of the old roster-wide dispatcher, matching the Options Flow's own
        `_async_step_after_link_user`. Matches the rebuild plan's wizard-flow order per
        member: Link user -> Calendar -> Lists, then either the next member or (once
        everyone's done) the shared Chores -> Confirm steps.
        """
        name = self._roster_names[self._member_index]
        if "calendar" not in self._roster_features[name]:
            return await self._async_step_after_calendar()
        if not self.hass.states.async_all("calendar"):
            if self._calendar_none_found_shown:
                return await self._async_step_after_calendar()
            self._calendar_none_found_shown = True
            return await self.async_step_calendar_none_found()
        return await self.async_step_calendar()

    async def async_step_calendar_none_found(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """No `calendar.*` entities exist anywhere yet. Never holds the flow open waiting
        for external OAuth setup (e.g. Google Calendar) - show instructions and continue,
        leaving every calendar-opted member explicitly unmapped (not silently skipped -
        this step itself is the visible record of that). Shown at most once per wizard run
        (`_calendar_none_found_shown`, set by `_async_step_after_link_user`), not once per
        calendar-opted member - repeating "you have no calendars yet" for every kid would be
        pure noise once the wizard says it the first time.
        """
        if user_input is not None:
            return await self._async_step_after_calendar()
        return self.async_show_form(step_id="calendar_none_found", data_schema=vol.Schema({}))

    async def async_step_calendar(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        name = self._roster_names[self._member_index]
        if user_input is not None:
            self._roster_calendar[name] = parse_calendar_input(user_input, [name])[name]
            return await self._async_step_after_calendar()

        return self.async_show_form(
            step_id="calendar",
            data_schema=build_calendar_schema([name]),
            description_placeholders={"name": name},
        )

    async def _async_step_after_calendar(self) -> config_entries.FlowResult:
        """Chain to `lists` only if the CURRENT member opted into "lists" - straight to
        advancing past this member otherwise, same per-member dispatcher shape as
        `_async_step_after_link_user`.
        """
        name = self._roster_names[self._member_index]
        if "lists" in self._roster_features[name]:
            return await self.async_step_lists()
        return await self._advance_to_next_member()

    async def async_step_lists(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        name = self._roster_names[self._member_index]
        if user_input is not None:
            self._roster_list_presets[name] = parse_lists_input(user_input, [name])[name]
            return await self._advance_to_next_member()

        return self.async_show_form(
            step_id="lists",
            data_schema=build_lists_schema([name]),
            description_placeholders={"name": name},
        )

    async def _advance_to_next_member(self) -> config_entries.FlowResult:
        """Every per-member screen (Colors through Lists) funnels here once that member's own
        chain finishes. Loops back to Colors for the next roster member, or - once everyone's
        done - proceeds to the shared Chores & Rewards steps (household-scoped, not
        per-member, unchanged by this restructuring) and Confirm."""
        self._member_index += 1
        if self._member_index < len(self._roster_names):
            return await self.async_step_colors()
        return await self._async_step_after_all_members()

    async def _async_step_after_all_members(self) -> config_entries.FlowResult:
        """Chain to the chores/rewards repeat-add loop only if at least one roster member
        opted into "chores" - straight to confirm otherwise. Runs once, after every member's
        own per-member chain above has finished (not per-member itself - Chores & Rewards is
        household-scoped)."""
        if self._chores_members():
            return await self.async_step_add_chore()
        return await self.async_step_confirm()

    def _chores_members(self) -> list[str]:
        """Roster member names (in roster order) who selected "chores" in the features
        step. Also the assignable set for Rewards - there's no separate Rewards feature
        toggle, it's part of the combined "Chores & Rewards" feature."""
        return [
            name for name in self._roster_names if "chores" in self._roster_features[name]
        ]

    async def async_step_add_chore(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Repeat-until-done "add a chore" loop. Reused for both the first entry and every
        subsequent loop-back (not a separate yes/no step) - every field except `name` has a
        default, and submitting with `name` left blank ends the loop, chaining to the
        Rewards loop. This also means a family that doesn't want to add any chores yet can
        leave the very first form blank and move straight on - the brief's literal "show a
        form, then ask add another?" description would force at least one entry first.
        """
        chores_members = self._chores_members()

        if user_input is not None:
            name = user_input["name"].strip()
            if name:
                self._chores.append(
                    {
                        "name": name,
                        "points": user_input["points"],
                        "frequency": user_input["frequency"],
                        "assigned_to_name": user_input["assigned_to"],
                    }
                )
                return await self.async_step_add_chore()
            return await self.async_step_add_reward()

        schema = vol.Schema(
            {
                vol.Optional("name", default=""): str,
                vol.Optional("points", default=5): vol.Coerce(int),
                vol.Optional(
                    "frequency", default="daily"
                ): vol.In(CHORE_FREQUENCIES),
                # Assigning to nobody is a valid, explicit choice (matches the Settings
                # dashboard's own Add Chore popup - modules/chores/crud.py) - a chore doesn't
                # have to belong to a specific kid.
                vol.Optional("assigned_to", default=chores_members[0]): vol.In(
                    [*chores_members, UNASSIGNED_OPTION]
                ),
            }
        )
        return self.async_show_form(
            step_id="add_chore",
            data_schema=schema,
            description_placeholders={
                "count": str(len(self._chores)),
                "roster": ", ".join(chores_members),
            },
        )

    async def async_step_add_reward(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Same repeat-until-done shape as `async_step_add_chore` - see its docstring."""
        chores_members = self._chores_members()

        if user_input is not None:
            name = user_input["name"].strip()
            if name:
                self._rewards.append(
                    {
                        "name": name,
                        "cost": user_input["cost"],
                        "assigned_to_name": user_input["assigned_to"],
                    }
                )
                return await self.async_step_add_reward()
            return await self.async_step_confirm()

        schema = vol.Schema(
            {
                vol.Optional("name", default=""): str,
                vol.Optional("cost", default=50): vol.Coerce(int),
                # Same "no owner required" choice as add_chore above.
                vol.Optional("assigned_to", default=chores_members[0]): vol.In(
                    [*chores_members, UNASSIGNED_OPTION]
                ),
            }
        )
        return self.async_show_form(
            step_id="add_reward",
            data_schema=schema,
            description_placeholders={
                "count": str(len(self._rewards)),
                "roster": ", ".join(chores_members),
            },
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            existing_ids: set[str] = set()
            roster = []
            name_to_member_id: dict[str, str] = {}
            for name in self._roster_names:
                member_id = slugify_unique(name, existing_ids)
                name_to_member_id[name] = member_id
                cal_id, notify_id = self._roster_calendar.get(name, (None, None))
                roster.append(
                    {
                        "member_id": member_id,
                        "name": name,
                        "color": self._roster_colors[name],
                        CONF_AVATAR: self._roster_avatars.get(name),
                        CONF_BIRTHDATE: self._roster_birthdates.get(name),
                        CONF_FEATURES: self._roster_features[name],
                        CONF_HA_USER_ID: self._roster_ha_user_ids[name],
                        CONF_CALENDAR_ENTITY_ID: cal_id,
                        CONF_NOTIFY_ENTITY_ID: notify_id,
                        CONF_LIST_PRESETS: self._roster_list_presets.get(name, []),
                    }
                )

            # chore_id/reward_id are deduped in their own separate namespaces (not shared
            # with member_id or with each other) - same slugify_unique helper as member_id.
            # UNASSIGNED_OPTION resolves to None - a chore/reward with no owner, same
            # "Unassigned" concept as the Settings dashboard's own Add Chore/Add Reward popups
            # (modules/chores/crud.py).
            chore_ids: set[str] = set()
            chores = [
                {
                    "chore_id": slugify_unique(chore["name"], chore_ids),
                    "name": chore["name"],
                    "points": chore["points"],
                    "frequency": chore["frequency"],
                    "assigned_to": name_to_member_id.get(chore["assigned_to_name"]),
                }
                for chore in self._chores
            ]
            reward_ids: set[str] = set()
            rewards = [
                {
                    "reward_id": slugify_unique(reward["name"], reward_ids),
                    "name": reward["name"],
                    "cost": reward["cost"],
                    "assigned_to": name_to_member_id.get(reward["assigned_to_name"]),
                }
                for reward in self._rewards
            ]

            return self.async_create_entry(
                title="Family Dashboard",
                data={
                    CONF_ROSTER: roster,
                    CONF_CHORES: chores,
                    CONF_REWARDS: rewards,
                },
            )

        lines = []
        for name in self._roster_names:
            features_str = (
                ", ".join(FEATURES[key]["name"] for key in self._roster_features[name])
                or "none"
            )
            linked = " (linked to HA user)" if self._roster_ha_user_ids[name] else ""
            cal_id, notify_id = self._roster_calendar.get(name, (None, None))
            calendar_str = f", calendar: {cal_id}" if cal_id else ""
            notify_str = " +reminders" if cal_id and notify_id else ""
            presets = self._roster_list_presets.get(name, [])
            presets_str = (
                f", lists: {', '.join(LIST_PRESETS[key]['name'] for key in presets)}"
                if presets
                else ""
            )
            chores_count = sum(1 for c in self._chores if c["assigned_to_name"] == name)
            rewards_count = sum(1 for r in self._rewards if r["assigned_to_name"] == name)
            chores_str = f", {chores_count} chore(s)" if chores_count else ""
            rewards_str = f", {rewards_count} reward(s)" if rewards_count else ""
            lines.append(
                f"- {name}: {self._roster_colors[name]}, {features_str}{linked}"
                f"{calendar_str}{notify_str}{presets_str}{chores_str}{rewards_str}"
            )

        # Unassigned chores/rewards belong to no member's own line above - list them
        # separately so the review screen doesn't silently omit them.
        unassigned_chores = sum(1 for c in self._chores if c["assigned_to_name"] == UNASSIGNED_OPTION)
        unassigned_rewards = sum(1 for r in self._rewards if r["assigned_to_name"] == UNASSIGNED_OPTION)
        if unassigned_chores or unassigned_rewards:
            parts = []
            if unassigned_chores:
                parts.append(f"{unassigned_chores} chore(s)")
            if unassigned_rewards:
                parts.append(f"{unassigned_rewards} reward(s)")
            lines.append(f"- Unassigned: {', '.join(parts)}")

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"roster_summary": "\n".join(lines)},
        )


class FamilyDashboardOptionsFlow(config_entries.OptionsFlow):
    """Add Family Member - the first real reconfigure capability, replacing v1's
    single-informational-step placeholder. Reuses the main wizard's own
    `build_*_schema`/`parse_*_input` functions (already written as plain module-level
    functions for exactly this reason - see this module's own docstring), scoped to a
    "roster" of exactly the one new member being added, rather than duplicating those forms.

    On confirm, the new member is appended to the EXISTING config entry's roster (every other
    member's data is left untouched) and the entry is reloaded so the new member's entities
    forward-set-up and the dashboard regenerates with them included - matching what a fresh
    `async_setup_entry` run would produce if this member had been in the roster from the
    start.

    Chores/Rewards for the new member CAN be added inline here too (`async_step_add_chore`/
    `async_step_add_reward`, only shown if "chores" was selected in the features step) - same
    repeat-until-blank loop as the main wizard's own steps, scoped to just this new member (or
    Unassigned), appended to whatever chores/rewards already exist rather than replacing them.

    Deliberately out of scope for this pass (a real gap, not an oversight - a future request,
    not silently assumed done): editing/unlinking an EXISTING member. The calendar-mapping
    step DOES still ask for an existing `calendar.*` entity, same as the main wizard - actually
    getting a calendar connected to HA (Google Calendar, Local Calendar, etc.) remains a manual
    step outside this integration, exactly like it already is for every other member.
    """

    def __init__(self) -> None:
        # `config_entry` is a read-only property on the base `OptionsFlow` class in current
        # HA versions (computed from `self.handler`/`self.hass`, wired up by the flow manager
        # AFTER construction) - it is explicitly NOT available inside `__init__` and can no
        # longer be assigned by a subclass, live-verified via `AttributeError: property
        # 'config_entry' of 'FamilyDashboardOptionsFlow' object has no setter`. Every step
        # method below accesses `self.config_entry` directly (inherited), never stores its
        # own copy.
        self._name: str = ""
        self._color: str = ""
        self._avatar: str = ""
        self._birthdate: str | None = None
        self._features: list[str] = []
        self._ha_user_id: str | None = None
        self._calendar_entity_id: str | None = None
        self._notify_entity_id: str | None = None
        self._list_presets: list[str] = []
        self._chores: list[dict] = []
        self._rewards: list[dict] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        return self.async_show_menu(step_id="init", menu_options=["add_member"])

    async def async_step_add_member(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input["name"].strip()
            if not name:
                errors["name"] = "name_required"
            else:
                self._name = name
                return await self.async_step_add_color()
        return self.async_show_form(
            step_id="add_member",
            data_schema=vol.Schema({vol.Required("name"): str}),
            errors=errors,
        )

    async def async_step_add_color(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._color = parse_colors_input(user_input, [self._name])[self._name]
            return await self.async_step_add_avatar()
        return self.async_show_form(
            step_id="add_color",
            data_schema=build_colors_schema([self._name]),
            description_placeholders={"name": self._name},
        )

    async def async_step_add_avatar(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._avatar = parse_avatars_input(user_input, [self._name])[self._name]
            return await self.async_step_add_birthdate()
        avatar_options = await async_seed_assets(self.hass)
        return self.async_show_form(
            step_id="add_avatar",
            data_schema=build_avatars_schema([self._name], avatar_options),
            description_placeholders={"name": self._name},
        )

    async def async_step_add_birthdate(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._birthdate = parse_birthdates_input(user_input, [self._name])[self._name]
                return await self.async_step_add_features()
            except ValueError:
                errors["base"] = "invalid_birthdate"
        return self.async_show_form(
            step_id="add_birthdate",
            data_schema=build_birthdates_schema([self._name]),
            description_placeholders={"name": self._name},
            errors=errors,
        )

    async def async_step_add_features(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._features = parse_features_input(user_input, [self._name])[self._name]
            return await self.async_step_add_link_user()
        return self.async_show_form(
            step_id="add_features",
            data_schema=build_features_schema([self._name]),
            description_placeholders={"name": self._name},
        )

    async def async_step_add_link_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._ha_user_id = parse_link_users_input(user_input, [self._name])[self._name]
            return await self._async_step_after_link_user()

        # Excludes accounts already linked to an existing roster member (unlike the main
        # wizard's own initial-setup version of this step, which has no "existing roster" to
        # conflict with yet) - the whole point of adding a new member is a distinct linkable
        # identity, not double-linking one HA account to two roster entries.
        already_linked = {
            m[CONF_HA_USER_ID]
            for m in self.config_entry.data[CONF_ROSTER]
            if m.get(CONF_HA_USER_ID)
        }
        users = await self.hass.auth.async_get_users()
        user_options = [
            {"value": user.id, "label": user.name or user.id}
            for user in users
            if user.is_active and not user.system_generated and user.id not in already_linked
        ]
        return self.async_show_form(
            step_id="add_link_user",
            data_schema=build_link_users_schema([self._name], user_options),
            description_placeholders={"name": self._name},
        )

    async def _async_step_after_link_user(self) -> config_entries.FlowResult:
        if "calendar" in self._features:
            if not self.hass.states.async_all("calendar"):
                return await self.async_step_add_calendar_none_found()
            return await self.async_step_add_calendar()
        return await self._async_step_after_calendar()

    async def async_step_add_calendar_none_found(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return await self._async_step_after_calendar()
        return self.async_show_form(
            step_id="add_calendar_none_found",
            data_schema=vol.Schema({}),
            description_placeholders={"name": self._name},
        )

    async def async_step_add_calendar(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            calendar_map = parse_calendar_input(user_input, [self._name])
            self._calendar_entity_id, self._notify_entity_id = calendar_map[self._name]
            return await self._async_step_after_calendar()
        return self.async_show_form(
            step_id="add_calendar",
            data_schema=build_calendar_schema([self._name]),
            description_placeholders={"name": self._name},
        )

    async def _async_step_after_calendar(self) -> config_entries.FlowResult:
        if "lists" in self._features:
            return await self.async_step_add_lists()
        return await self._async_step_after_lists()

    async def async_step_add_lists(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._list_presets = parse_lists_input(user_input, [self._name])[self._name]
            return await self._async_step_after_lists()
        return self.async_show_form(
            step_id="add_lists",
            data_schema=build_lists_schema([self._name]),
            description_placeholders={"name": self._name},
        )

    async def _async_step_after_lists(self) -> config_entries.FlowResult:
        if "chores" in self._features:
            return await self.async_step_add_chore()
        return await self.async_step_add_confirm()

    async def async_step_add_chore(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Same repeat-until-done shape as the main wizard's `async_step_add_chore`, but
        scoped to just this new member (or Unassigned) - assigning a chore/reward to some
        OTHER existing roster member is out of scope here (that's what the Settings
        dashboard's own Add Chore popup, which can target anyone, is for); this step exists
        so a new member doesn't have to be onboarded chore-less and then edited separately."""
        if user_input is not None:
            name = user_input["name"].strip()
            if name:
                self._chores.append(
                    {
                        "name": name,
                        "points": user_input["points"],
                        "frequency": user_input["frequency"],
                        "assigned_to_name": user_input["assigned_to"],
                    }
                )
                return await self.async_step_add_chore()
            return await self.async_step_add_reward()

        schema = vol.Schema(
            {
                vol.Optional("name", default=""): str,
                vol.Optional("points", default=5): vol.Coerce(int),
                vol.Optional("frequency", default="daily"): vol.In(CHORE_FREQUENCIES),
                vol.Optional("assigned_to", default=self._name): vol.In(
                    [self._name, UNASSIGNED_OPTION]
                ),
            }
        )
        return self.async_show_form(
            step_id="add_chore",
            data_schema=schema,
            description_placeholders={"count": str(len(self._chores)), "name": self._name},
        )

    async def async_step_add_reward(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Same repeat-until-done shape as `async_step_add_chore` above."""
        if user_input is not None:
            name = user_input["name"].strip()
            if name:
                self._rewards.append(
                    {
                        "name": name,
                        "cost": user_input["cost"],
                        "assigned_to_name": user_input["assigned_to"],
                    }
                )
                return await self.async_step_add_reward()
            return await self.async_step_add_confirm()

        schema = vol.Schema(
            {
                vol.Optional("name", default=""): str,
                vol.Optional("cost", default=50): vol.Coerce(int),
                vol.Optional("assigned_to", default=self._name): vol.In(
                    [self._name, UNASSIGNED_OPTION]
                ),
            }
        )
        return self.async_show_form(
            step_id="add_reward",
            data_schema=schema,
            description_placeholders={"count": str(len(self._rewards)), "name": self._name},
        )

    async def async_step_add_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            roster = list(self.config_entry.data[CONF_ROSTER])
            existing_ids = {m["member_id"] for m in roster}
            member_id = slugify_unique(self._name, existing_ids)
            roster.append(
                {
                    "member_id": member_id,
                    "name": self._name,
                    "color": self._color,
                    CONF_AVATAR: self._avatar,
                    CONF_BIRTHDATE: self._birthdate,
                    CONF_FEATURES: self._features,
                    CONF_HA_USER_ID: self._ha_user_id,
                    CONF_CALENDAR_ENTITY_ID: self._calendar_entity_id,
                    CONF_NOTIFY_ENTITY_ID: self._notify_entity_id,
                    CONF_LIST_PRESETS: self._list_presets,
                }
            )

            # assigned_to_name resolves to this new member's own id, or None for
            # UNASSIGNED_OPTION - same chore_id/reward_id generation (deduped against every
            # EXISTING chore/reward, not just the ones added in this flow) as the main
            # wizard's own async_step_confirm.
            def _assigned_to(name: str) -> str | None:
                return member_id if name == self._name else None

            chore_ids = {c["chore_id"] for c in self.config_entry.data.get(CONF_CHORES, [])}
            new_chores = [
                {
                    "chore_id": slugify_unique(chore["name"], chore_ids),
                    "name": chore["name"],
                    "points": chore["points"],
                    "frequency": chore["frequency"],
                    "assigned_to": _assigned_to(chore["assigned_to_name"]),
                }
                for chore in self._chores
            ]
            reward_ids = {r["reward_id"] for r in self.config_entry.data.get(CONF_REWARDS, [])}
            new_rewards = [
                {
                    "reward_id": slugify_unique(reward["name"], reward_ids),
                    "name": reward["name"],
                    "cost": reward["cost"],
                    "assigned_to": _assigned_to(reward["assigned_to_name"]),
                }
                for reward in self._rewards
            ]

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_ROSTER: roster,
                    CONF_CHORES: [*self.config_entry.data.get(CONF_CHORES, []), *new_chores],
                    CONF_REWARDS: [*self.config_entry.data.get(CONF_REWARDS, []), *new_rewards],
                },
            )
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        features_str = (
            ", ".join(FEATURES[key]["name"] for key in self._features) or "none"
        )
        linked = " (linked to HA user)" if self._ha_user_id else ""
        calendar_str = f", calendar: {self._calendar_entity_id}" if self._calendar_entity_id else ""
        presets_str = (
            f", lists: {', '.join(LIST_PRESETS[key]['name'] for key in self._list_presets)}"
            if self._list_presets
            else ""
        )
        chores_str = f", {len(self._chores)} chore(s)" if self._chores else ""
        rewards_str = f", {len(self._rewards)} reward(s)" if self._rewards else ""
        summary = (
            f"- {self._name}: {self._color}, {features_str}{linked}{calendar_str}"
            f"{presets_str}{chores_str}{rewards_str}"
        )
        return self.async_show_form(
            step_id="add_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"member_summary": summary},
        )
