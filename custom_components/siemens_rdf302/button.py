"""Button for the Siemens RDF302 integration."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Rdf302ConfigEntry
from .entity import Rdf302Entity
from .rdf302_modbus import CLOCK_DISPLAY_VALUES, REG_P07


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Rdf302ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the clock sync button if the display shows the time."""
    if entry.runtime_data.device.raw(REG_P07) in CLOCK_DISPLAY_VALUES:
        async_add_entities([Rdf302SyncClock(entry)])


class Rdf302SyncClock(Rdf302Entity, ButtonEntity):
    """Set the thermostat's clock to the current time."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "sync_clock"

    def __init__(self, entry: Rdf302ConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_sync_clock"

    async def async_press(self) -> None:
        """Send the time."""
        await self.runtime.async_call(self.runtime.async_sync_clock())
