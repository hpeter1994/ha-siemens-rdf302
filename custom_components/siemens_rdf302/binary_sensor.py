"""Binary sensors for the Siemens RDF302 integration."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Rdf302ConfigEntry
from .entity import Rdf302Entity
from .rdf302_modbus import REG_X1_DIGITAL, REG_X2_DIGITAL, Fault, InputFunction

DIGITAL_INPUTS: dict[InputFunction, tuple[str, BinarySensorDeviceClass | None]] = {
    InputFunction.MODE_CONTACT: ("contact", BinarySensorDeviceClass.OPENING),
    InputFunction.DEW_POINT: ("dew_point", BinarySensorDeviceClass.MOISTURE),
    InputFunction.HEATER_ENABLE: ("heater_enable", None),
    InputFunction.FAULT: ("fault", BinarySensorDeviceClass.PROBLEM),
    InputFunction.DIGITAL_MONITOR: ("monitor", None),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Rdf302ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    device = entry.runtime_data.device
    entities: list[BinarySensorEntity] = [Rdf302Problem(entry)]
    for number, address in ((1, REG_X1_DIGITAL), (2, REG_X2_DIGITAL)):
        if (digital := DIGITAL_INPUTS.get(device.input_function(number))) is not None:
            kind, device_class = digital
            entities.append(Rdf302Input(entry, number, kind, device_class, address))
    async_add_entities(entities)


class Rdf302Problem(Rdf302Entity, BinarySensorEntity):
    """On while the thermostat reports any fault.

    The bus only reports the highest-priority fault, so there is deliberately
    no sensor per fault: one would read clear while masked by another.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry: Rdf302ConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_problem"

    @property
    def is_on(self) -> bool | None:
        """Return whether there is a fault."""
        if (fault := self.device.fault) is None:
            return None
        return fault is not Fault.NO_FAULT


class Rdf302Input(Rdf302Entity, BinarySensorEntity):
    """A digital state on input X1 or X2."""

    def __init__(
        self,
        entry: Rdf302ConfigEntry,
        number: int,
        kind: str,
        device_class: BinarySensorDeviceClass | None,
        address: int,
    ) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._address = address
        self._attr_device_class = device_class
        self._attr_unique_id = f"{entry.entry_id}_x{number}_{kind}"
        self._attr_translation_key = f"input_{kind}"
        self._attr_translation_placeholders = {"input": f"X{number}"}

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        if (raw := self.device.raw(self._address)) is None:
            return None
        return raw == 1
