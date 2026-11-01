"""End-to-end tests over real sockets, through Home Assistant's modbus integration.

A simulated thermostat speaks real Modbus TCP frames, and answers exception 2 for
any address the manual leaves undefined.
"""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siemens_rdf302.const import (
    CONF_MODEL,
    CONF_UNIT_ID,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .conftest import text_registers


class FakeThermostat:
    """Answer Modbus requests the way the manual describes."""

    def __init__(self) -> None:
        self.input: dict[int, int] = {
            1001: 1, 1002: 0, 1003: 1100, 1004: 1050, 1005: 0, 1006: 0, 1007: 0,
            1008: 1250, 1009: 0xFFFF, 1010: 0, 1011: 0, 1012: 0,
        }  # fmt: skip
        for offset, value in enumerate(text_registers("No fault")):
            self.input[1100 + offset] = value
        self.holding: dict[int, int] = {
            1: 2, 2: 1, 38: (3 << 8) | 1, 40: 0, 41: 0, 44: 150, 65: 400, 66: 2025,
            81: 1, 182: 0, 101: 1, 102: 0, 103: 1050, 104: 0, 105: 0, 106: 1, 107: 1,
            108: 0, 109: 1,
        }  # fmt: skip
        self.holding |= {address: 0 for address in range(4, 15)}
        self.holding |= {9: 250, 10: 1750, 11: 750, 12: 1500}
        self.holding |= {address: 1 for address in (30, 31, 33, 34, 35, 36, 37)}
        self.holding |= {address: 1 for address in range(48, 63)}
        self.holding |= {51: 450, 52: 1, 53: 2}
        self.holding |= {address: 0 for address in range(68, 72)}
        for base, text in ((200, "Cond"), (300, "F1"), (400, "F2"), (500, "Filter")):
            for offset, value in enumerate(text_registers(text)):
                self.holding[base + offset] = value
        self.holding |= {address: 0 for address in range(600, 604)}
        self.function_codes: set[int] = set()

    def answer(self, pdu: bytes) -> bytes:
        """Return the response PDU for a request PDU."""
        function = pdu[0]
        self.function_codes.add(function)
        # The stores use the manual's addresses, one above the wire's.
        address = int.from_bytes(pdu[1:3]) + 1
        if function in (3, 4):
            count = int.from_bytes(pdu[3:5])
            store = self.holding if function == 3 else self.input
            if any(address + i not in store for i in range(count)):
                return bytes([function | 0x80, 2])
            data = b"".join(store[address + i].to_bytes(2) for i in range(count))
            return bytes([function, len(data)]) + data
        if function == 6:
            if address not in self.holding:
                return bytes([function | 0x80, 2])
            self.holding[address] = int.from_bytes(pdu[3:5])
            return pdu
        if function == 16:
            count = int.from_bytes(pdu[3:5])
            for i in range(count):
                self.holding[address + i] = int.from_bytes(pdu[6 + 2 * i : 8 + 2 * i])
            return pdu[:5]
        return bytes([function | 0x80, 1])

    async def serve_tcp(self, reader, writer) -> None:
        """Speak Modbus TCP."""
        try:
            while True:
                header = await reader.readexactly(7)
                pdu = await reader.readexactly(int.from_bytes(header[4:6]) - 1)
                reply = self.answer(pdu)
                writer.write(
                    header[:4]
                    + (len(reply) + 1).to_bytes(2)
                    + header[6:7]
                    + reply
                )
                await writer.drain()
        except asyncio.IncompleteReadError, ConnectionError:
            writer.close()


@pytest.fixture
def thermostat() -> FakeThermostat:
    """Return the simulated thermostat."""
    return FakeThermostat()


@pytest.fixture
async def port(
    thermostat: FakeThermostat, socket_enabled: None
) -> AsyncGenerator[int]:
    """Serve the thermostat."""
    tcp = await asyncio.start_server(thermostat.serve_tcp, "127.0.0.1", 0)
    yield tcp.sockets[0].getsockname()[1]
    tcp.close()


@pytest.mark.enable_socket
async def test_full_stack(
    hass: HomeAssistant, port: int, thermostat: FakeThermostat
) -> None:
    """Set up, read, write and unload over a real link."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="RDF302",
        unique_id=f"127.0.0.1:{port}:1",
        data={
            CONF_HOST: "127.0.0.1",
            CONF_PORT: port,
            CONF_UNIT_ID: 1,
            CONF_MODEL: "rdf302",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    state = hass.states.get("climate.rdf302")
    assert state.attributes["current_temperature"] == 22
    assert state.attributes["temperature"] == 21

    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.rdf302", "temperature": 23.5},
        blocking=True,
    )
    assert thermostat.holding[103] == 1175

    await entry.runtime_data.device.async_write_text(500, "Szuro")
    assert thermostat.holding[500] == int.from_bytes(b"Sz")

    assert thermostat.function_codes == {3, 4, 6, 16}

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
