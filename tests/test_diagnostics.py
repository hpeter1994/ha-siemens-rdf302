"""Tests for diagnostics."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from homeassistant.core import HomeAssistant

from .conftest import setup_entry


@pytest.mark.usefixtures("mock_link")
async def test_diagnostics(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, entry: MockConfigEntry
) -> None:
    """Diagnostics show the serial settings and hide the bridge address."""
    await setup_entry(hass, entry)
    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert result["serial"] == {"modbus_address": 1, "baud_rate": 19200, "parity": "even"}
    assert result["entry"]["host"] == "**REDACTED**"
    assert result["registers"]["1004"] == 21 * 50
