"""Diagnostics for the Siemens RDF302 integration."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import Rdf302ConfigEntry

BAUD_RATES = {0: 4800, 1: 9600, 2: 19200, 3: 38400}
PARITIES = {0: "odd", 1: "even", 2: "none"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: Rdf302ConfigEntry
) -> dict[str, Any]:
    """Return the serial settings and every register as last read.

    The serial settings only change at the wall and cut the link when they
    do, so they live here rather than as entities.
    """
    device = entry.runtime_data.device
    return {
        "entry": async_redact_data(dict(entry.data), {CONF_HOST}),
        "serial": {
            "modbus_address": device.raw(81),
            "baud_rate": BAUD_RATES.get(device.raw(68)),
            "parity": PARITIES.get(device.raw(70)),
        },
        "registers": dict(sorted(device.registers.items())),
    }
