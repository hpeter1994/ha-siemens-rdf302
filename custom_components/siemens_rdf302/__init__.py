"""The Siemens RDF302 integration."""

from collections.abc import Mapping
from datetime import datetime
import logging
from typing import Any

from modbus_connection import ModbusError, ModbusTcpParams

from homeassistant.components.modbus import async_get_unit
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import (
    CONF_APPLICATION,
    CONF_MODEL,
    CONF_UNIT_ID,
    FAST_SCAN_INTERVAL,
    MESSAGE_SPACING,
    SLOW_SCAN_INTERVAL,
)
from .coordinator import Rdf302ConfigEntry, Rdf302Coordinator, Rdf302Runtime
from .rdf302_modbus import CLOCK_DISPLAY_VALUES, REG_P07, Application, Model, Rdf302

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]


def create_modbus_params(data: Mapping[str, Any]) -> ModbusTcpParams:
    """Build the link parameters from config entry data."""
    return ModbusTcpParams(host=data[CONF_HOST], port=data[CONF_PORT])


async def async_setup_entry(hass: HomeAssistant, entry: Rdf302ConfigEntry) -> bool:
    """Set up a thermostat from a config entry."""
    try:
        unit = async_get_unit(
            hass, entry, create_modbus_params(entry.data), entry.data[CONF_UNIT_ID]
        )
    except HomeAssistantError as err:
        raise ConfigEntryError(str(err)) from err
    unit.set_message_spacing(MESSAGE_SPACING)

    device = Rdf302(
        unit,
        Model(entry.data[CONF_MODEL]),
        Application(entry.data.get(CONF_APPLICATION, Application.NONE)),
    )
    fast = Rdf302Coordinator(
        hass, entry, "runtime", FAST_SCAN_INTERVAL, device.async_update_fast
    )
    slow = Rdf302Coordinator(
        hass, entry, "parameters", SLOW_SCAN_INTERVAL, device.async_update_slow
    )
    await fast.async_config_entry_first_refresh()
    await slow.async_config_entry_first_refresh()
    entry.runtime_data = Rdf302Runtime(device, fast, slow)

    structure = device.structure_key()

    @callback
    def _async_reload_on_structure_change() -> None:
        """Reload when a setting that decides which entities exist has changed."""
        if slow.last_update_success and device.structure_key() != structure:
            _LOGGER.debug("%s: configuration changed, reloading", entry.title)
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(slow.async_add_listener(_async_reload_on_structure_change))

    async def _async_sync_clock(now: datetime) -> None:
        """Keep the displayed time right, including across daylight saving."""
        if device.raw(REG_P07) not in CLOCK_DISPLAY_VALUES:
            return
        try:
            await device.async_set_clock(dt_util.now())
        except (ModbusError, OSError) as err:
            _LOGGER.debug("%s: clock sync failed: %s", entry.title, err)

    entry.async_on_unload(
        async_track_time_change(hass, _async_sync_clock, minute=0, second=5)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Rdf302ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

