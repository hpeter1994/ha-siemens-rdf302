"""Tests for the config flow."""

from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siemens_rdf302.const import (
    CONF_APPLICATION,
    CONF_MODEL,
    CONF_UNIT_ID,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

USER_INPUT = {
    CONF_HOST: "192.0.2.1",
    CONF_PORT: 502,
    CONF_UNIT_ID: 1,
    CONF_MODEL: "rdf302",
    CONF_NAME: "Living room",
}

pytestmark = pytest.mark.usefixtures("mock_link")


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def test_creates_entry(hass: HomeAssistant) -> None:
    """A thermostat reporting its application needs one step."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living room"
    assert CONF_NAME not in result["data"]
    assert result["result"].unique_id == "192.0.2.1:502:1"


async def test_asks_application_if_not_reported(
    hass: HomeAssistant, unit: MockModbusUnit
) -> None:
    """A unit reading NONE gets asked for its application."""
    unit.holding[109] = 0
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "application"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_APPLICATION: "two_pipe"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_APPLICATION] == 1


async def test_cannot_connect_then_recovers(
    hass: HomeAssistant, unit: MockModbusUnit
) -> None:
    """A silent device shows an error and allows a retry."""
    unit.fail_requests(ModbusTimeoutError())
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["errors"] == {"base": "cannot_connect"}
    unit.fail_requests(None)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_not_a_thermostat(hass: HomeAssistant, unit: MockModbusUnit) -> None:
    """An impossible operating mode is rejected."""
    unit.input[1001] = 77
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["errors"] == {"base": "not_a_thermostat"}


async def test_already_configured(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The same address cannot be added twice."""
    entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The connection can be changed."""
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    new = {k: v for k, v in USER_INPUT.items() if k != CONF_NAME} | {CONF_PORT: 8899}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PORT] == 8899
    assert entry.unique_id == "192.0.2.1:8899:1"
    await hass.async_block_till_done()
