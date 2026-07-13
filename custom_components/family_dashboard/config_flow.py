"""Config flow for Family Dashboard.

Four steps, in order:
  1. `user`    - roster names (comma-separated). Always-on: Settings/Roster is core, not a
                  toggleable module (see const.py).
  2. `colors`  - one color picker per roster name, built dynamically from step 1's answers.
  3. `modules` - which toggleable modules to enable (Calendar / Lists / Chores & Rewards),
                  multi-select, sensible defaults pre-checked.
  4. `confirm` - summary of what's about to be created; submitting creates the config entry.

NOT YET IMPLEMENTED, on purpose: Google Calendar guided mapping. The rebuild plan's
"Decided" section requires this be a real, checked wizard step (scan for `calendar.*`
entities, map one per roster member, loop with a retry if none exist) - it belongs here,
chained in after `modules` and before `confirm`, gated on "calendar" being in the selected
modules, once the Calendar module itself is built out (see modules/calendar/). Leaving it
out of this scaffold is deliberate, not an oversight - do not ship v2 without it, that
gap is exactly what made v1's wizard "pointless" per Phillip's own feedback.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import selector

from .const import (
    COLOR_OPTIONS,
    CONF_MODULES,
    CONF_ROSTER,
    DEFAULT_SELECTED_MODULES,
    DOMAIN,
    MODULES,
    ROSTER_MAX_MEMBERS,
)
from .util import slugify_unique


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


class FamilyDashboardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Family Dashboard wizard."""

    VERSION = 1

    def __init__(self) -> None:
        self._roster_names: list[str] = []
        self._roster_colors: dict[str, str] = {}
        self._selected_modules: list[str] = []

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return FamilyDashboardOptionsFlow(config_entry)

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
        if user_input is not None:
            self._roster_colors = {
                name: user_input[f"color_{idx}"]
                for idx, name in enumerate(self._roster_names)
            }
            return await self.async_step_modules()

        schema_dict: dict[Any, Any] = {}
        for idx, name in enumerate(self._roster_names):
            default_color = COLOR_OPTIONS[idx % len(COLOR_OPTIONS)]
            schema_dict[vol.Required(f"color_{idx}", default=default_color)] = selector(
                {"select": {"options": COLOR_OPTIONS}}
            )
        return self.async_show_form(
            step_id="colors",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"roster": ", ".join(self._roster_names)},
        )

    async def async_step_modules(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._selected_modules = user_input[CONF_MODULES]
            return await self.async_step_confirm()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODULES, default=DEFAULT_SELECTED_MODULES
                ): cv.multi_select({key: mod["name"] for key, mod in MODULES.items()})
            }
        )
        return self.async_show_form(step_id="modules", data_schema=schema)

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            existing_ids: set[str] = set()
            roster = [
                {
                    "member_id": slugify_unique(name, existing_ids),
                    "name": name,
                    "color": self._roster_colors[name],
                }
                for name in self._roster_names
            ]
            return self.async_create_entry(
                title="Family Dashboard",
                data={CONF_ROSTER: roster, CONF_MODULES: self._selected_modules},
            )

        roster_summary = ", ".join(
            f"{name} ({self._roster_colors[name]})" for name in self._roster_names
        )
        module_summary = (
            ", ".join(MODULES[key]["name"] for key in self._selected_modules) or "none"
        )
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "roster_summary": roster_summary,
                "module_summary": module_summary,
            },
        )


class FamilyDashboardOptionsFlow(config_entries.OptionsFlow):
    """Placeholder options flow.

    v1 has no reconfigure step - adding/removing roster members or toggling modules after
    initial setup isn't supported yet (mirrors the same v1 limitation the old
    ha-family-hub-setup had). This class exists so `async_get_options_flow` has something
    real to return; it just shows a single informational step.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data={})
        return self.async_show_form(step_id="init", data_schema=vol.Schema({}))
