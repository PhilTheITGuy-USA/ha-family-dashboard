"""Detects active, non-system HA user accounts that aren't linked to any roster member, and
raises one HA Repair Issue per unmapped user (Settings > Repairs) - the exact gap that let an
unlinked user silently fall into the shared Kiosk bucket and see everyone's calendars/lists/
chores instead of getting their own view (or a deliberate decision to leave them in the Kiosk
bucket, which "Ignore" now records).

Dismissing an issue in the Repairs UI ("Ignore") is a real, permanent per-user off-switch for
free - confirmed directly against the installed HA source
(`homeassistant.helpers.issue_registry.IssueRegistry.async_get_or_create`): when an issue with
the same issue_id already exists, re-creating it does `dataclasses.replace(issue, ...)`, which
never touches `dismissed_version` - so an ignored issue stays ignored across every future
reload that calls this same check again. No custom "never ask about this user again" list
needed in our own config-entry data.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CONF_HA_USER_ID, CONF_ROSTER, DOMAIN

_ISSUE_ID_PREFIX = "unmapped_user_"


def _issue_id(user_id: str) -> str:
    return f"{_ISSUE_ID_PREFIX}{user_id}"


async def async_check_unmapped_users(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Called on every entry setup/reload. Creates a Repair Issue for every active,
    non-system HA user not linked to any roster member, and clears any such issue for a user
    who's since been added to the roster (or is no longer active/gone entirely) - so a stale
    "add this person" prompt doesn't linger after they've already been handled. Same
    (active, non-system-generated) filter `dashboard/registry.py`'s Kiosk-bucket computation
    and `config_flow.py`'s `link_users` step already use for "real, linkable" HA users.
    """
    linked_ids = {
        member[CONF_HA_USER_ID]
        for member in entry.data[CONF_ROSTER]
        if member.get(CONF_HA_USER_ID)
    }
    users = await hass.auth.async_get_users()
    unmapped = [
        user for user in users
        if user.is_active and not user.system_generated and user.id not in linked_ids
    ]

    registry = ir.async_get(hass)
    existing_issue_ids = {
        issue.issue_id
        for issue in registry.issues.values()
        if issue.domain == DOMAIN and issue.issue_id.startswith(_ISSUE_ID_PREFIX)
    }
    wanted_issue_ids = {_issue_id(user.id) for user in unmapped}

    for issue_id in existing_issue_ids - wanted_issue_ids:
        ir.async_delete_issue(hass, DOMAIN, issue_id)

    for user in unmapped:
        ir.async_create_issue(
            hass,
            DOMAIN,
            _issue_id(user.id),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="unmapped_user",
            translation_placeholders={"name": user.name or user.id},
        )
