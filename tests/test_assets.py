"""Tests for assets.py's seed-on-setup behavior: default avatars, background image, and theme
YAML land in /config/ after entry setup, and user-added/customized files are never clobbered.
"""
from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_dashboard.const import DOMAIN


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Family Dashboard",
        data={"roster": []},
        source="user",
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_default_avatars_background_and_theme_are_seeded(hass: HomeAssistant):
    await _setup_entry(hass)

    config_dir = Path(hass.config.config_dir)
    avatars = config_dir / "www" / "family_dashboard" / "avatars"
    assert (avatars / "person-solid.png").is_file()
    assert (avatars / "people-group-solid.png").is_file()
    assert (config_dir / "www" / "family_dashboard" / "background.png").is_file()

    theme_file = config_dir / "themes" / "family_dashboard.yaml"
    assert theme_file.is_file()
    assert "Family Dashboard:" in theme_file.read_text()


async def test_seeding_never_overwrites_an_existing_avatar(hass: HomeAssistant):
    config_dir = Path(hass.config.config_dir)
    avatars = config_dir / "www" / "family_dashboard" / "avatars"
    avatars.mkdir(parents=True, exist_ok=True)
    custom_avatar = avatars / "person-solid.png"
    custom_avatar.write_bytes(b"a real photo, not the shipped placeholder")

    await _setup_entry(hass)

    assert custom_avatar.read_bytes() == b"a real photo, not the shipped placeholder"
