"""Shared fixtures. `enable_custom_integrations` comes from
pytest-homeassistant-custom-component and is required for `hass` to load anything under
custom_components/ instead of only core integrations.
"""
import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
