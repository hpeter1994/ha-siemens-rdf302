"""Switches for the Siemens RDF302 integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Rdf302ConfigEntry
from .entity import Rdf302Entity
from .rdf302_modbus import REG_HEATER_ENABLE, REG_WINDOW, InputFunction, Rdf302


@dataclass(frozen=True, kw_only=True)
class Rdf302SwitchDescription(SwitchEntityDescription):
    """Describe a switch backed by one register."""

    address: int
    exists_fn: Callable[[Rdf302], bool] = lambda _: True


SWITCHES: tuple[Rdf302SwitchDescription, ...] = (
    Rdf302SwitchDescription(
        key="window_open",
        translation_key="window_open",
        address=REG_WINDOW,
        # Only one source may drive this: the local contact or the bus.
        exists_fn=lambda device: not device.has_input_function(
            InputFunction.MODE_CONTACT
        ),
    ),
    Rdf302SwitchDescription(
        key="heater_enable",
        translation_key="heater_enable",
        address=REG_HEATER_ENABLE,
        exists_fn=lambda device: device.has_heater
        and not device.has_input_function(InputFunction.HEATER_ENABLE),
    ),
    Rdf302SwitchDescription(
        key="heater_in_cooling",
        translation_key="heater_in_cooling",
        address=13,
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        exists_fn=lambda device: device.has_heater,
    ),
    Rdf302SwitchDescription(
        key="fan_start_kick",
        translation_key="fan_start_kick",
        address=58,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    Rdf302SwitchDescription(
        key="temporary_comfort_setpoint",
        translation_key="temporary_comfort_setpoint",
        address=69,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Rdf302ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switches."""
    device = entry.runtime_data.device
    async_add_entities(
        Rdf302Switch(entry, description)
        for description in SWITCHES
        if description.exists_fn(device)
    )


class Rdf302Switch(Rdf302Entity, SwitchEntity):
    """A switch backed by one register."""

    entity_description: Rdf302SwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        if (raw := self.device.raw(self.entity_description.address)) is None:
            return None
        return raw == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        await self.runtime.async_write(self.entity_description.address, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self.runtime.async_write(self.entity_description.address, 0)
