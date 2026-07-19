"""Tests for the config flow:
user (roster, once) -> per roster member: colors -> avatars -> birthdates -> features ->
link_users -> [calendar or calendar_none_found, only if "calendar" selected] -> [lists, only
if "lists" selected] -> (next member, or once everyone's done) -> [add_chore/add_reward, only
if "chores" selected by anyone] -> confirm.

Every multi-field step is one screen per roster member (2026-07-18 wizard redesign) - so a
2-member roster submits `color_0`/`avatar_0`/etc. TWICE, once per member's own turn through
the loop, not once with `_0`/`_1` fields for both members in a single flat form.
"""
from homeassistant import config_entries, data_entry_flow
from homeassistant.components.calendar import CalendarEntity
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    setup_test_component_platform,
)

from custom_components.family_dashboard.const import DOMAIN


class _FakeCalendar(CalendarEntity):
    _attr_name = "Fake Calendar"
    _attr_unique_id = "fake_calendar"
    _attr_should_poll = False

    @property
    def event(self):
        return None


async def _register_fake_calendar(hass):
    setup_test_component_platform(hass, "calendar", [_FakeCalendar()])
    assert await async_setup_component(hass, "calendar", {"calendar": [{"platform": "test"}]})
    await hass.async_block_till_done()


async def test_full_flow_creates_entry(hass):
    # link_users offers real HA accounts (via hass.auth.async_get_users()) - there's no
    # generic "user" selector to submit an arbitrary id against, so create one for real.
    ada_account = await hass.auth.async_create_user(name="Ada Account")
    # The calendar step only shows real mapping fields if at least one calendar.* entity
    # exists anywhere - otherwise it's the calendar_none_found branch (tested separately).
    await _register_fake_calendar(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"roster": "Ada, Grace"}
    )
    assert result["step_id"] == "colors"

    # --- Ada's own turn through the per-member loop ---
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"color_0": "Blue"}
    )
    assert result["step_id"] == "avatars"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"avatar_0": "/local/family_dashboard/avatars/person-solid.png"},
    )
    assert result["step_id"] == "birthdates"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"birthdate_0": "21/06/2015"}
    )
    assert result["step_id"] == "features"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"features_0": ["calendar", "lists"]}
    )
    assert result["step_id"] == "link_users"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"ha_user_0": ada_account.id}
    )
    # Ada selected "calendar" - her own calendar screen shows next.
    assert result["step_id"] == "calendar"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"calendar_0": "calendar.fake_calendar"}
    )
    # Ada also selected "lists" - her own lists screen shows next.
    assert result["step_id"] == "lists"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"presets_0": ["shopping", "to_do"]}
    )
    # Ada's chain is done - loops back to Colors, now for Grace.
    assert result["step_id"] == "colors"

    # --- Grace's own turn through the per-member loop ---
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"color_0": "Green"}
    )
    assert result["step_id"] == "avatars"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"avatar_0": "/local/family_dashboard/avatars/people-group-solid.png"},
    )
    assert result["step_id"] == "birthdates"

    # Grace's birthdate field is omitted entirely (skipped - optional).
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "features"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"features_0": ["chores"]}
    )
    assert result["step_id"] == "link_users"

    # Grace's link-user field is omitted entirely (skipped).
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    # Grace selected neither "calendar" nor "lists" - both screens skipped for her. Every
    # member is done now, and Grace selected "chores" - straight to the shared chores loop.
    assert result["step_id"] == "add_chore"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Trash", "points": 10, "frequency": "daily", "assigned_to": "Grace"},
    )
    assert result["step_id"] == "add_chore"  # loops back, blank form

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": ""}
    )  # blank name ends the chores loop
    assert result["step_id"] == "add_reward"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Movie Night", "cost": 30, "assigned_to": "Grace"}
    )
    assert result["step_id"] == "add_reward"  # loops back, blank form

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": ""}
    )  # blank name ends the rewards loop
    assert result["step_id"] == "confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY

    data = result["data"]
    assert "modules" not in data
    assert "features" not in data

    roster = data["roster"]
    assert roster[0] == {
        "member_id": "ada",
        "name": "Ada",
        "color": "Blue",
        "avatar": "/local/family_dashboard/avatars/person-solid.png",
        "birthdate": "2015-06-21",
        "features": ["calendar", "lists"],
        "ha_user_id": ada_account.id,
        "calendar_entity_id": "calendar.fake_calendar",
        "notify_entity_id": None,
        "list_presets": ["shopping", "to_do"],
    }
    assert roster[1] == {
        "member_id": "grace",
        "name": "Grace",
        "color": "Green",
        "avatar": "/local/family_dashboard/avatars/people-group-solid.png",
        "birthdate": None,
        "features": ["chores"],
        "ha_user_id": None,
        "calendar_entity_id": None,
        "notify_entity_id": None,
        "list_presets": [],
    }

    assert data["chores"] == [
        {
            "chore_id": "trash",
            "name": "Trash",
            "points": 10,
            "frequency": "daily",
            "assigned_to": "grace",
        }
    ]
    assert data["rewards"] == [
        {"reward_id": "movie_night", "name": "Movie Night", "cost": 30, "assigned_to": "grace"}
    ]


async def test_calendar_none_found_branch(hass):
    """No calendar.* entities exist anywhere - the instructional branch, not the mapping
    form, and it never holds the flow open."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"roster": "Ada"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"color_0": "Blue"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})  # avatars, defaults
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})  # birthdates, skipped
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"features_0": ["calendar"]}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "calendar_none_found"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["roster"][0]["calendar_entity_id"] is None


async def test_calendar_and_lists_steps_skipped_when_not_selected(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"roster": "Ada"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"color_0": "Blue"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})  # avatars, defaults
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})  # birthdates, skipped
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"features_0": ["chores"]}
    )
    assert result["step_id"] == "link_users"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    # calendar and lists both skipped (neither selected) - straight to the chores loop,
    # since Ada did select "chores". Leave both loops blank to reach confirm.
    assert result["step_id"] == "add_chore"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": ""})
    assert result["step_id"] == "add_reward"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": ""})
    assert result["step_id"] == "confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["roster"][0]["calendar_entity_id"] is None
    assert result["data"]["roster"][0]["list_presets"] == []
    assert result["data"]["chores"] == []
    assert result["data"]["rewards"] == []


async def test_empty_roster_shows_error(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"roster": "   ,  "}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"]["base"] == "roster_empty"


async def test_invalid_birthdate_format_shows_error_and_recovers(hass):
    """The birthdate field is a plain typed DD/MM/YYYY text field, not HA's built-in `date`
    selector (which is popup-only with no year-jump - unusable for old birthdates). Garbage
    input re-shows the same step with an error instead of silently accepting it or crashing;
    correcting it afterward proceeds normally."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"roster": "Ada"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"color_0": "Blue"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})  # avatars
    assert result["step_id"] == "birthdates"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"birthdate_0": "not-a-date"}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "birthdates"
    assert result["errors"]["base"] == "invalid_birthdate"

    # An impossible calendar date (there's no 31st of February) is rejected too, not just
    # malformed text.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"birthdate_0": "31/02/2015"}
    )
    assert result["errors"]["base"] == "invalid_birthdate"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"birthdate_0": "21/06/2015"}
    )
    assert result["step_id"] == "features"


async def test_only_one_instance_allowed(hass):
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    first = await hass.config_entries.flow.async_configure(first["flow_id"], {"roster": "Ada"})
    first = await hass.config_entries.flow.async_configure(first["flow_id"], {"color_0": "Blue"})
    first = await hass.config_entries.flow.async_configure(first["flow_id"], {})  # avatars, defaults
    first = await hass.config_entries.flow.async_configure(first["flow_id"], {})  # birthdates, skipped
    first = await hass.config_entries.flow.async_configure(
        first["flow_id"], {"features_0": []}
    )
    first = await hass.config_entries.flow.async_configure(first["flow_id"], {})
    await hass.config_entries.flow.async_configure(first["flow_id"], {})

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    second = await hass.config_entries.flow.async_configure(
        second["flow_id"], {"roster": "Ada"}
    )
    assert second["type"] == data_entry_flow.FlowResultType.ABORT
    assert second["reason"] == "already_configured"


async def test_options_flow_add_member_appends_to_existing_roster(hass):
    """Add Family Member - the first real Options Flow capability (v1's placeholder just
    showed one informational step). Walks the lists-only path (features step doesn't select
    "calendar", so the calendar step is skipped entirely - same conditional chaining as the
    main wizard) and confirms: the new member is appended to the EXISTING entry's roster
    without touching Ada's own data, and the entry actually reloads with the new member's
    entities live - not just data mutated in memory.
    """
    ada_account = await hass.auth.async_create_user(name="Ada Account")
    gerald_account = await hass.auth.async_create_user(name="Gerald Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                {
                    "member_id": "ada",
                    "name": "Ada",
                    "color": "Blue",
                    "features": ["lists"],
                    "ha_user_id": ada_account.id,
                    "calendar_entity_id": None,
                    "notify_entity_id": None,
                    "list_presets": ["to_do"],
                }
            ],
            "chores": [],
            "rewards": [],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.MENU
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_member"}
    )
    assert result["step_id"] == "add_member"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Gerald"}
    )
    assert result["step_id"] == "add_color"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"color_0": "Red"}
    )
    assert result["step_id"] == "add_avatar"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"avatar_0": "/local/family_dashboard/avatars/person-solid.png"}
    )
    assert result["step_id"] == "add_birthdate"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"birthdate_0": "14/03/2010"}
    )
    assert result["step_id"] == "add_features"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"features_0": ["lists"]}
    )
    assert result["step_id"] == "add_link_user"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"ha_user_0": gerald_account.id}
    )
    # Only "lists" was selected - the calendar step (and calendar_none_found) must be skipped
    # entirely, straight to lists, same conditional chaining as the main wizard.
    assert result["step_id"] == "add_lists"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"presets_0": ["shopping"]}
    )
    assert result["step_id"] == "add_confirm"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY

    roster = entry.data["roster"]
    assert len(roster) == 2
    assert roster[0]["member_id"] == "ada"  # untouched
    assert roster[1] == {
        "member_id": "gerald",
        "name": "Gerald",
        "color": "Red",
        "avatar": "/local/family_dashboard/avatars/person-solid.png",
        "birthdate": "2010-03-14",
        "features": ["lists"],
        "ha_user_id": gerald_account.id,
        "calendar_entity_id": None,
        "notify_entity_id": None,
        "list_presets": ["shopping"],
    }

    # Reloaded for real - Gerald's entities actually exist now, not just his roster dict.
    await hass.async_block_till_done()
    assert hass.states.get("select.family_dashboard_gerald_color") is not None


async def test_options_flow_add_member_can_add_chores_and_rewards_inline(hass):
    """Explicit feature request: adding a new member who selects "chores" should be able to
    add their chores/rewards right there, instead of being onboarded chore-less and edited
    separately afterward. Also proves the new chores/rewards are APPENDED to whatever already
    exists (Ada's pre-existing "Dishes" chore untouched, ids deduped against it), and that
    "Unassigned" is a valid choice here too, same as everywhere else in this integration.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                {
                    "member_id": "ada",
                    "name": "Ada",
                    "color": "Blue",
                    "features": ["chores"],
                    "ha_user_id": None,
                    "calendar_entity_id": None,
                    "notify_entity_id": None,
                    "list_presets": [],
                }
            ],
            "chores": [
                {"chore_id": "dishes", "name": "Dishes", "points": 5, "frequency": "daily", "assigned_to": "ada"}
            ],
            "rewards": [],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_member"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Gerald"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"color_0": "Red"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})  # avatar, default
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})  # birthdate, skipped
    assert result["step_id"] == "add_features"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"features_0": ["chores"]}
    )
    assert result["step_id"] == "add_link_user"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    # Neither "calendar" nor "lists" selected - straight to the chores loop.
    assert result["step_id"] == "add_chore"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Feed Fish", "points": 5, "frequency": "daily", "assigned_to": "Gerald"},
    )
    assert result["step_id"] == "add_chore"  # loops back, blank form

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"name": ""})
    assert result["step_id"] == "add_reward"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Extra Screen Time", "cost": 20, "assigned_to": "Unassigned"},
    )
    assert result["step_id"] == "add_reward"  # loops back, blank form

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"name": ""})
    assert result["step_id"] == "add_confirm"
    assert "1 chore(s)" in result["description_placeholders"]["member_summary"]
    assert "1 reward(s)" in result["description_placeholders"]["member_summary"]

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY

    gerald_id = next(m["member_id"] for m in entry.data["roster"] if m["name"] == "Gerald")
    chores = entry.data["chores"]
    assert {c["chore_id"] for c in chores} == {"dishes", "feed_fish"}
    assert next(c for c in chores if c["chore_id"] == "feed_fish")["assigned_to"] == gerald_id
    # Ada's pre-existing chore is untouched.
    assert next(c for c in chores if c["chore_id"] == "dishes")["assigned_to"] == "ada"

    rewards = entry.data["rewards"]
    assert len(rewards) == 1
    assert rewards[0]["assigned_to"] is None  # Unassigned resolves to None

    await hass.async_block_till_done()
    assert hass.states.get(f"sensor.family_dashboard_feed_fish") is not None


async def test_options_flow_add_member_excludes_already_linked_users(hass):
    """The whole point of adding a new member is a distinct linkable identity - an HA account
    already linked to an existing roster member must not be offered again."""
    ada_account = await hass.auth.async_create_user(name="Ada Account")
    gerald_account = await hass.auth.async_create_user(name="Gerald Account")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "roster": [
                {
                    "member_id": "ada",
                    "name": "Ada",
                    "color": "Blue",
                    "features": [],
                    "ha_user_id": ada_account.id,
                    "calendar_entity_id": None,
                    "notify_entity_id": None,
                    "list_presets": [],
                }
            ],
            "chores": [],
            "rewards": [],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_member"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Gerald"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"color_0": "Red"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})  # avatar, default
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})  # birthdate, skipped
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"features_0": []}
    )
    assert result["step_id"] == "add_link_user"

    options = list(result["data_schema"].schema.values())[0].config["options"]
    offered_ids = {opt["value"] for opt in options}
    assert ada_account.id not in offered_ids
    assert gerald_account.id in offered_ids


async def test_wizard_allows_unassigned_chores_and_rewards(hass):
    """Assigning a chore/reward to nobody is a valid, explicit choice in the wizard too - same
    "Unassigned" concept as the Settings dashboard's own Add Chore/Add Reward popups
    (modules/chores/crud.py)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"roster": "Grace"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"color_0": "Green"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})  # avatars, defaults
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})  # birthdates, skipped
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"features_0": ["chores"]}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "add_chore"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Water Plants", "points": 5, "frequency": "weekly", "assigned_to": "Unassigned"},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": ""})
    assert result["step_id"] == "add_reward"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Family Movie", "cost": 20, "assigned_to": "Unassigned"},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": ""})
    assert result["step_id"] == "confirm"
    assert "Unassigned: 1 chore(s), 1 reward(s)" in result["description_placeholders"]["roster_summary"]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY

    data = result["data"]
    assert data["chores"] == [
        {"chore_id": "water_plants", "name": "Water Plants", "points": 5, "frequency": "weekly", "assigned_to": None}
    ]
    assert data["rewards"] == [
        {"reward_id": "family_movie", "name": "Family Movie", "cost": 20, "assigned_to": None}
    ]
