"""Tests for the four-step config flow: user (roster) -> colors -> modules -> confirm."""
from homeassistant import config_entries, data_entry_flow

from custom_components.family_dashboard.const import DOMAIN


async def test_full_flow_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"roster": "Ada, Grace"}
    )
    assert result["step_id"] == "colors"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"color_0": "Blue", "color_1": "Green"}
    )
    assert result["step_id"] == "modules"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"modules": ["calendar", "lists"]}
    )
    assert result["step_id"] == "confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["modules"] == ["calendar", "lists"]
    roster = result["data"]["roster"]
    assert roster[0]["name"] == "Ada"
    assert roster[0]["color"] == "Blue"
    assert roster[0]["member_id"] == "ada"
    assert roster[1]["name"] == "Grace"
    assert roster[1]["member_id"] == "grace"


async def test_empty_roster_shows_error(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"roster": "   ,  "}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"]["base"] == "roster_empty"


async def test_only_one_instance_allowed(hass):
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    first = await hass.config_entries.flow.async_configure(first["flow_id"], {"roster": "Ada"})
    first = await hass.config_entries.flow.async_configure(first["flow_id"], {"color_0": "Blue"})
    first = await hass.config_entries.flow.async_configure(first["flow_id"], {"modules": []})
    await hass.config_entries.flow.async_configure(first["flow_id"], {})

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    second = await hass.config_entries.flow.async_configure(
        second["flow_id"], {"roster": "Ada"}
    )
    assert second["type"] == data_entry_flow.FlowResultType.ABORT
    assert second["reason"] == "already_configured"
