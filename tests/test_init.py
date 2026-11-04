"""Tests for setup, link parameters and reloads."""

from unittest.mock import patch

from modbus_connection import (
    ModbusConnectionError,
    ModbusTcpParams,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.siemens_rdf302 import create_modbus_params
from custom_components.siemens_rdf302.const import FAST_SCAN_INTERVAL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import setup_entry


def test_tcp_params() -> None:
    """The link is plain Modbus TCP."""
    params = create_modbus_params({CONF_HOST: "ew11", CONF_PORT: 502})
    assert params == ModbusTcpParams(host="ew11", port=502)


@pytest.mark.usefixtures("mock_link")
async def test_setup_retries_while_silent(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """A silent thermostat retries setup."""
    unit.fail_requests(ModbusTimeoutError())
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("mock_link")
async def test_setup_writes_nothing(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """Starting up must not command the thermostat."""
    writes = []
    unit.on_write(writes.append)
    await setup_entry(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert writes == []


@pytest.mark.usefixtures("mock_link")
async def test_unavailable_and_recovers(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """Entities follow the link without a reload."""
    await setup_entry(hass, entry)
    entity_id = "climate.rdf302"
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE

    unit.fail_requests(ModbusTimeoutError())
    async_fire_time_changed(hass, dt_util.utcnow() + FAST_SCAN_INTERVAL)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    unit.fail_requests(None)
    async_fire_time_changed(hass, dt_util.utcnow() + 2 * FAST_SCAN_INTERVAL)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE


@pytest.mark.usefixtures("mock_link")
async def test_closed_link_is_retried_once(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """A link the bridge closed does not make the entities unavailable."""
    await setup_entry(hass, entry)
    fast = entry.runtime_data.fast
    update = fast._update
    calls = 0

    async def fails_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ModbusConnectionError("connection is closed")
        await update()

    fast._update = fails_once
    await fast.async_refresh()
    await hass.async_block_till_done()
    assert calls == 2
    assert fast.last_update_success
    assert hass.states.get("climate.rdf302").state != STATE_UNAVAILABLE


@pytest.mark.usefixtures("mock_link")
async def test_structure_change_reloads(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """A parameter deciding which entities exist reloads the entry."""
    await setup_entry(hass, entry)
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        unit.holding[1] = 0
        await entry.runtime_data.slow.async_refresh()
        await hass.async_block_till_done()
    reload.assert_called_once_with(entry.entry_id)


@pytest.mark.usefixtures("mock_link")
async def test_hourly_clock_sync_only_when_displayed(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """The clock is only written if the display shows it."""
    writes = []
    unit.on_write(writes.append)
    await setup_entry(hass, entry)
    top_of_hour = dt_util.utcnow().replace(minute=0, second=5, microsecond=0)
    async_fire_time_changed(hass, top_of_hour)
    await hass.async_block_till_done()
    assert not [w for w in writes if w.address == 600]

    # Showing the clock changes the entities, so the entry reloads.
    unit.holding[7] = 4
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, top_of_hour.replace(hour=(top_of_hour.hour + 1) % 24))
    await hass.async_block_till_done()
    assert [w for w in writes if w.address == 600]


@pytest.mark.usefixtures("mock_link")
async def test_clock_resynced_after_outage(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """A power cut clears the clock, so it is written once the link returns."""
    writes = []
    unit.on_write(writes.append)
    unit.holding[7] = 4
    await setup_entry(hass, entry)

    unit.fail_requests(ModbusTimeoutError())
    async_fire_time_changed(hass, dt_util.utcnow() + FAST_SCAN_INTERVAL)
    await hass.async_block_till_done()
    assert not [w for w in writes if w.address == 600]

    unit.fail_requests(None)
    async_fire_time_changed(hass, dt_util.utcnow() + 2 * FAST_SCAN_INTERVAL)
    await hass.async_block_till_done()
    assert len([w for w in writes if w.address == 600]) == 1


@pytest.mark.usefixtures("mock_link")
async def test_parameters_reread_when_state_changes(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """A change at the wall re-reads every setting without waiting for the slow poll."""
    await setup_entry(hass, entry)
    device = entry.runtime_data.device

    unit.holding[11] = 12 * 50
    unit.input[1003] = 23 * 50
    async_fire_time_changed(hass, dt_util.utcnow() + FAST_SCAN_INTERVAL)
    await hass.async_block_till_done()
    assert device.raw(1003) == 23 * 50
    assert device.raw(11) != 12 * 50

    unit.input[1001] = 3
    async_fire_time_changed(hass, dt_util.utcnow() + 2 * FAST_SCAN_INTERVAL)
    await hass.async_block_till_done()
    assert device.raw(11) == 12 * 50


@pytest.mark.usefixtures("mock_link")
async def test_parameters_reread_after_runtime_write(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """Commands can change settings too, so every write re-reads them."""
    await setup_entry(hass, entry)
    unit.holding[11] = 12 * 50
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.rdf302", "preset_mode": "eco"},
        blocking=True,
    )
    assert entry.runtime_data.device.raw(11) == 12 * 50
