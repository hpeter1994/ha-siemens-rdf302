"""Polling for the Siemens RDF302 integration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from modbus_connection import ModbusConnectionError, ModbusError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .rdf302_modbus import Rdf302

_LOGGER = logging.getLogger(__name__)


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
    _runtime_state: tuple[int | None, ...] | None = field(default=None, init=False)
    _writing: bool = field(default=False, init=False)
    unique_ids: set[str] = field(default_factory=set, init=False)
    last_clock_sync: datetime | None = field(default=None, init=False)

    async def async_write(self, address: int, value: int) -> None:
        """Write a register and refresh what it can have changed."""
        await self.async_call(self.device.async_write(address, value))
        await self.async_refresh_after_write()

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

    async def async_sync_clock(self) -> None:
        """Send the current time and note when, for the last sync sensor."""
        now = dt_util.now()
        await self.device.async_set_clock(now)
        self.last_clock_sync = now
        self.fast.async_update_listeners()

    async def async_refresh_after_write(self) -> None:
        """Refresh everything after a write; the device may change related settings."""
        self._writing = True
        try:
            await self.slow.async_refresh()
            await self.fast.async_refresh()
        finally:
            self._writing = False

    def runtime_changed(self) -> bool:
        """Return whether something other than our own write changed the state.

        Changes made at the wall can come with parameter changes, so the
        caller then refreshes the parameters too.
        """
        state = self.device.runtime_state()
        changed = self._runtime_state is not None and state != self._runtime_state
        self._runtime_state = state
        return changed and not self._writing


type Rdf302ConfigEntry = ConfigEntry[Rdf302Runtime]

