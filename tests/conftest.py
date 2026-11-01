"""Fixtures for the Siemens RDF302 tests."""

from collections.abc import Generator
from contextlib import asynccontextmanager
from unittest.mock import patch

from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siemens_rdf302.const import (
    CONF_MODEL,
    CONF_UNIT_ID,
    DOMAIN,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant


class ManualAddressedUnit(MockModbusUnit):
    """A mock whose stores use the manual's addresses, one above the wire's."""

    async def read_holding_registers(self, address: int, count: int) -> list[int]:
        return await super().read_holding_registers(address + 1, count)

    async def read_input_registers(self, address: int, count: int) -> list[int]:
        return await super().read_input_registers(address + 1, count)

    async def write_register(self, address: int, value: int) -> None:
        await super().write_register(address + 1, value)

    async def write_registers(self, address: int, values: list[int]) -> None:
        await super().write_registers(address + 1, values)


def text_registers(text: str) -> list[int]:
    """Encode text the way the thermostat is assumed to store it."""
    data = text.encode().ljust(20, b"\0")
    return [int.from_bytes(data[i : i + 2]) for i in range(0, 20, 2)]


def factory_registers(unit: MockModbusUnit) -> None:
    """Load a 2-pipe thermostat with factory settings, in manual changeover."""
    unit.input.update(
        {
            1001: 1,  # Comfort
            1002: 33,
            1003: 22 * 50,
            1004: 21 * 50,
            1005: 100,
            1006: 0,
            1007: 0,
            1008: 25 * 50,
            1009: 0xFFFF,
            1010: 0,
            1011: 0,
            1012: 0,
            1100: text_registers("No fault"),
        }
    )
    unit.holding.update(
        {
            1: 2,  # P01 manual changeover
            2: 1,
            4: 0,
            5: 0,
            6: 0,
            7: 0,
            8: 21 * 50,
            9: 5 * 50,
            10: 35 * 50,
            11: 15 * 50,
            12: 30 * 50,
            13: 1,
            14: 0,
            38: (3 << 8) | 1,  # X1 mode contact, X2 external sensor
            40: 0,
            41: 0,
            51: 9 * 50,
            52: 1,
            53: 2,
            65: 8 * 50,
            66: int(40.5 * 50),
            68: 2,
            70: 1,
            81: 1,
            101: 1,
            102: 0,
            103: 21 * 50,
            104: 0,
            105: 0,
            106: 1,
            107: 1,
            108: 0,
            109: 1,  # 2-pipe
            200: text_registers("Condensation in room"),
            300: text_registers("Fault input 1"),
            400: text_registers("Fault input 2"),
            500: text_registers("Filter dirty"),
        }
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make the custom integration loadable."""


@pytest.fixture
def unit() -> MockModbusUnit:
    """Return a thermostat at factory settings."""
    mock_unit = ManualAddressedUnit(MockModbusConnection(), 1)
    factory_registers(mock_unit)
    return mock_unit


@pytest.fixture
def mock_link(unit: MockModbusUnit) -> Generator[None]:
    """Hand the mock unit out where the integration asks the modbus integration."""

    @asynccontextmanager
    async def temporary_unit(hass, params, unit_id):
        yield unit

    with (
        patch(
            "custom_components.siemens_rdf302.async_get_unit",
            return_value=unit,
        ),
        patch(
            "custom_components.siemens_rdf302.config_flow.async_get_temporary_unit",
            temporary_unit,
        ),
    ):
        yield


@pytest.fixture
def entry() -> MockConfigEntry:
    """Return a config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="RDF302",
        unique_id="192.0.2.1:502:1",
        data={
            CONF_HOST: "192.0.2.1",
            CONF_PORT: 502,
            CONF_UNIT_ID: 1,
            CONF_MODEL: "rdf302",
        },
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the config entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
