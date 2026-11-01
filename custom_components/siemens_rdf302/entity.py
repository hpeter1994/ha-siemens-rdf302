"""Base entity for the Siemens RDF302 integration."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import Rdf302ConfigEntry, Rdf302Coordinator
from .rdf302_modbus import Model

MODEL_NAMES = {
    Model.RDF302: "RDF302",
    Model.RDF302_VB: "RDF302/VB",
    Model.RDF302_B: "RDF302.B",
}


class Rdf302Entity(CoordinatorEntity[Rdf302Coordinator]):
    """An entity showing registers from both polling groups.

    Availability follows the fast group alone: it notices a dead link within
    seconds, and the slow group would stay failed for an hour after recovery.
    """

    _attr_has_entity_name = True

    def __init__(
        self, entry: Rdf302ConfigEntry, description: EntityDescription | None = None
    ) -> None:
        """Initialize the entity."""
        runtime = entry.runtime_data
        super().__init__(runtime.fast)
        self.runtime = runtime
        self.device = runtime.device
        if description is not None:
            self.entity_description = description
            self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=MODEL_NAMES[runtime.device.model],
            name=entry.title,
        )

    async def async_added_to_hass(self) -> None:
        """Also follow the slow group."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.runtime.slow.async_add_listener(self._handle_coordinator_update)
        )
