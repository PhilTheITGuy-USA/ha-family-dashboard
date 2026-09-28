"""Tests for `dashboard/register.py`'s `async_repair_card_resources`: every required
third-party card ends up registered as a Lovelace resource when its HACS file is on disk, and
a beta-era bundled copy (`/local/family_dashboard/vendor/`) is removed only once another copy
of that card is registered - never leaving a card with nothing loading it (the v1.2.1 bug).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.family_dashboard.dashboard.register import (
    _resources_collection,
    async_repair_card_resources,
)

_HACS_FILES = {
    "button-card": "button-card/button-card.js",
    "bubble-card": "Bubble-Card/bubble-card.js",
    "card-mod": "lovelace-card-mod/card-mod.js",
    "config-template-card": "config-template-card/config-template-card.js",
    "week-planner-card": "week-planner-card/week-planner-card.js",
}


@pytest.fixture(autouse=True)
def _clean_card_dirs(hass: HomeAssistant):
    """The harness shares one config dir across tests - don't let card files leak."""
    www = Path(hass.config.config_dir) / "www"
    dirs = [www / "community", www / "family_dashboard" / "vendor"]
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
    yield
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


async def _collection(hass: HomeAssistant, urls=()):
    assert await async_setup_component(hass, "lovelace", {"lovelace": {}})
    await hass.async_block_till_done()
    collection = _resources_collection(hass)
    await collection.async_get_info()
    for url in urls:
        await collection.async_create_item({"res_type": "module", "url": url})
    return collection


def _urls(collection) -> list[str]:
    return sorted(item["url"] for item in collection.async_items())


def _hacs_file(hass: HomeAssistant, card: str) -> Path:
    path = Path(hass.config.config_dir) / "www" / "community" / _HACS_FILES[card]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("// card")
    return path


def _vendor_file(hass: HomeAssistant, card: str) -> Path:
    path = Path(hass.config.config_dir) / "www" / "family_dashboard" / "vendor" / f"{card}.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("// bundled copy")
    return path


async def test_registers_hacs_cards_that_have_no_resource(hass: HomeAssistant):
    """The live v1.2.1 breakage: HACS files present, only Bubble Card registered, the other
    four's only resources (the bundled ones) already gone - register the four from HACS."""
    for card in _HACS_FILES:
        _hacs_file(hass, card)
    collection = await _collection(hass, ["/hacsfiles/Bubble-Card/bubble-card.js?hacstag=1"])

    await async_repair_card_resources(hass)

    assert _urls(collection) == sorted(
        [
            "/hacsfiles/Bubble-Card/bubble-card.js?hacstag=1",
            "/hacsfiles/button-card/button-card.js",
            "/hacsfiles/lovelace-card-mod/card-mod.js",
            "/hacsfiles/config-template-card/config-template-card.js",
            "/hacsfiles/week-planner-card/week-planner-card.js",
        ]
    )


async def test_bundled_copy_removed_only_once_another_copy_is_registered(hass: HomeAssistant):
    _hacs_file(hass, "button-card")  # on disk, not registered yet
    bubble_vendor = _vendor_file(hass, "bubble-card")
    button_vendor = _vendor_file(hass, "button-card")
    mod_vendor = _vendor_file(hass, "card-mod")  # no other copy anywhere
    collection = await _collection(
        hass,
        [
            "/local/family_dashboard/vendor/bubble-card.js",
            "/local/family_dashboard/vendor/button-card.js",
            "/local/family_dashboard/vendor/card-mod.js",
            "/hacsfiles/Bubble-Card/bubble-card.js?hacstag=1",
        ],
    )

    await async_repair_card_resources(hass)

    assert _urls(collection) == sorted(
        [
            "/hacsfiles/Bubble-Card/bubble-card.js?hacstag=1",
            "/hacsfiles/button-card/button-card.js",
            "/local/family_dashboard/vendor/card-mod.js",
        ]
    )
    assert not bubble_vendor.exists()
    assert not button_vendor.exists()
    assert mod_vendor.is_file()


async def test_card_registered_at_another_path_counts(hass: HomeAssistant):
    """A manual install (e.g. /local/community/...) already loads the card - adding the HACS
    path too would load it twice."""
    _hacs_file(hass, "button-card")
    collection = await _collection(hass, ["/local/community/button-card/button-card.js"])

    await async_repair_card_resources(hass)

    assert _urls(collection) == ["/local/community/button-card/button-card.js"]


async def test_repair_is_idempotent_and_ignores_missing_cards(hass: HomeAssistant):
    _hacs_file(hass, "card-mod")
    collection = await _collection(hass)

    await async_repair_card_resources(hass)
    await async_repair_card_resources(hass)

    assert _urls(collection) == ["/hacsfiles/lovelace-card-mod/card-mod.js"]


async def test_empty_vendor_folder_is_removed(hass: HomeAssistant):
    _hacs_file(hass, "button-card")
    vendor_file = _vendor_file(hass, "button-card")
    await _collection(hass, ["/local/family_dashboard/vendor/button-card.js"])

    await async_repair_card_resources(hass)

    assert not vendor_file.parent.exists()
