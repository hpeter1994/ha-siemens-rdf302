"""Polling for the Siemens RDF302 integration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
import logging

from modbus_connection import ModbusConnectionError, ModbusError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .rdf302_modbus import REG_CHANGEOVER, REG_KEY_LOCK, REG_MODE_COMMAND, Rdf302

_LOGGER = logging.getLogger(__name__)

_FIRST_RUNTIME_REGISTER = REG_MODE_COMMAND
_LAST_RUNTIME_REGISTER = max(REG_CHANGEOVER, REG_KEY_LOCK)


class Rdf302Coordinator(DataUpdateCoordinator[None]):
    """Poll one group of registers into the shared device object."""

    config_entry: "Rdf302ConfigEntry"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: "Rdf302ConfigEntry",
        name: str,
        interval: timedelta,
        update: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} {name}",
            update_interval=interval,
        )
        self._update = update

    async def _async_update_data(self) -> None:
        try:
            try:
                await self._update()
            except ModbusConnectionError:
                # The bridge sometimes closes the link; the next request reopens it.
                await self._update()
        except (ModbusError, OSError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err


@dataclass
class Rdf302Runtime:
    """The device and its coordinators."""

    device: Rdf302
    fast: Rdf302Coordinator
    slow: Rdf302Coordinator

    async def async_write(self, address: int, value: int) -> None:
        """Write a register and refresh what it can have changed."""
        await self.async_call(self.device.async_write(address, value))
        await self.async_refresh_after_write(address)

    async def async_call(self, call: Awaitable[None]) -> None:
        """Run a device call, reporting a failure to the user."""
        try:
            await call
        except (ModbusError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_refresh_after_write(self, address: int) -> None:
        """Refresh after a write; a parameter also needs the slow group."""
        if not _FIRST_RUNTIME_REGISTER <= address <= _LAST_RUNTIME_REGISTER:
            await self.slow.async_refresh()
        await self.fast.async_refresh()


type Rdf302ConfigEntry = ConfigEntry[Rdf302Runtime]

