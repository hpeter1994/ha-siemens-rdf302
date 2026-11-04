"""Fault text entities for the Siemens RDF302 integration."""

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Rdf302ConfigEntry
from .entity import Rdf302Entity
from .rdf302_modbus import (
    REG_FAULT_TEXT_1,
    REG_FAULT_TEXT_2,
    REG_FAULT_TEXT_3,
    REG_FAULT_TEXT_4,
)

FAULT_TEXTS = {
    "condensation": REG_FAULT_TEXT_1,
    "fault_input_1": REG_FAULT_TEXT_2,
    "fault_input_2": REG_FAULT_TEXT_3,
    "dirty_filter": REG_FAULT_TEXT_4,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Rdf302ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the fault text entities."""
    async_add_entities(
        Rdf302FaultText(entry, key, address) for key, address in FAULT_TEXTS.items()
    )


class Rdf302FaultText(Rdf302Entity, TextEntity):
    """A fault text stored in the thermostat."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_native_max = 20
    _attr_pattern = r"^[\x20-\x7E]*$"

    def __init__(self, entry: Rdf302ConfigEntry, key: str, address: int) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._address = address
        self._attr_unique_id = f"{entry.entry_id}_text_{key}"
        self._attr_translation_key = f"text_{key}"

    @property
    def native_value(self) -> str | None:
        """Return the text."""
        return self.device.fault_template(self._address)

    async def async_set_value(self, value: str) -> None:
        """Write the text."""
        await self.runtime.async_call(self.device.async_write_text(self._address, value))
        await self.runtime.async_refresh_after_write()
