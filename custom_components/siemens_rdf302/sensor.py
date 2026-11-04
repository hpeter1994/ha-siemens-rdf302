"""Sensors for the Siemens RDF302 integration."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Rdf302ConfigEntry
from .entity import Rdf302Entity
from .rdf302_modbus import (
    CLOCK_DISPLAY_VALUES,
    MODE_COMFORT,
    MODE_ECONOMY,
    MODE_PROTECTION,
    REG_COOLING_OUTPUT,
    REG_FAN_OPERATION,
    REG_FAN_OUTPUT,
    REG_HEATER_OUTPUT,
    REG_HEATING_OUTPUT,
    REG_MODE_STATE,
    REG_P07,
    REG_P51,
    REG_ROOM_TEMP,
    REG_X1_TEMP,
    REG_X2_TEMP,
    TEMP_SCALE,
    Application,
    Fault,
    InputFunction,
    Rdf302,
)

MODE_OPTIONS = {
    MODE_COMFORT: "comfort",
    MODE_ECONOMY: "economy",
    MODE_PROTECTION: "protection",
}
FAN_OUTPUT_OPTIONS = {0: "off", 33: "low", 66: "medium", 100: "high"}
FAN_OPERATION_OPTIONS = {0: "auto", 1: "manual"}
APPLICATION_OPTIONS = {
    Application.NONE: "none",
    Application.TWO_PIPE: "two_pipe",
    Application.TWO_PIPE_3POS: "two_pipe_3pos",
    Application.TWO_PIPE_HEATER: "two_pipe_heater",
    Application.FOUR_PIPE: "four_pipe",
}

_LOGGER = logging.getLogger(__name__)

TEMPERATURE_INPUT_KEYS = {
    InputFunction.EXTERNAL_SENSOR: "external",
    InputFunction.CHANGEOVER: "changeover",
    InputFunction.TEMP_MONITOR: "monitor",
}


@dataclass(frozen=True, kw_only=True)
class Rdf302SensorDescription(SensorEntityDescription):
    """Describe a sensor."""

    value_fn: Callable[[Rdf302], Any]
    attributes_fn: Callable[[Rdf302], dict[str, Any]] | None = None
    exists_fn: Callable[[Rdf302], bool] = lambda _: True


def _temperature(address: int) -> dict[str, Any]:
    return {
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "value_fn": lambda device: device.temperature(address),
    }


def _percent(address: int) -> dict[str, Any]:
    return {
        "state_class": SensorStateClass.MEASUREMENT,
        "native_unit_of_measurement": PERCENTAGE,
        "value_fn": lambda device: device.raw(address),
    }


def _enum(address: int, options: dict[int, str]) -> dict[str, Any]:
    return {
        "device_class": SensorDeviceClass.ENUM,
        "options": list(options.values()),
        "value_fn": lambda device: options.get(device.raw(address)),
    }


def _setpoint_state(device: Rdf302) -> str | None:
    """Tell an OFF setpoint apart from an unknown one, since both have no number."""
    if (off := device.setpoint_off) is None:
        return None
    return "off" if off else "active"


SENSORS: tuple[Rdf302SensorDescription, ...] = (
    Rdf302SensorDescription(
        key="room_temperature", translation_key="room_temperature", **_temperature(REG_ROOM_TEMP)
    ),
    Rdf302SensorDescription(
        key="effective_setpoint",
        translation_key="effective_setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda device: device.setpoint_active,
        attributes_fn=lambda device: {"setpoint": _setpoint_state(device)},
    ),
    Rdf302SensorDescription(
        key="operating_mode",
        translation_key="operating_mode",
        **_enum(REG_MODE_STATE, MODE_OPTIONS),
    ),
    Rdf302SensorDescription(
        key="heating_output",
        translation_key="heating_output",
        exists_fn=lambda device: device.can_heat,
        **_percent(REG_HEATING_OUTPUT),
    ),
    Rdf302SensorDescription(
        key="cooling_output",
        translation_key="cooling_output",
        exists_fn=lambda device: device.can_cool,
        **_percent(REG_COOLING_OUTPUT),
    ),
    Rdf302SensorDescription(
        key="heater_output",
        translation_key="heater_output",
        exists_fn=lambda device: device.has_heater,
        **_percent(REG_HEATER_OUTPUT),
    ),
    Rdf302SensorDescription(
        key="fan_output",
        translation_key="fan_output",
        exists_fn=lambda device: device.has_fan,
        **_enum(REG_FAN_OUTPUT, FAN_OUTPUT_OPTIONS),
    ),
    Rdf302SensorDescription(
        key="fan_operation",
        translation_key="fan_operation",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda device: device.has_fan,
        **_enum(REG_FAN_OPERATION, FAN_OPERATION_OPTIONS),
    ),
    Rdf302SensorDescription(
        key="application",
        translation_key="application",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=list(APPLICATION_OPTIONS.values()),
        value_fn=lambda device: APPLICATION_OPTIONS[device.application],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Rdf302ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    device = entry.runtime_data.device
    entities: list[SensorEntity] = [
        Rdf302Sensor(entry, description)
        for description in SENSORS
        if description.exists_fn(device)
    ]
    entities.append(Rdf302FaultSensor(entry))
    if device.raw(REG_P07) in CLOCK_DISPLAY_VALUES:
        entities.append(Rdf302LastClockSync(entry))
    for number, address in ((1, REG_X1_TEMP), (2, REG_X2_TEMP)):
        function = device.input_function(number)
        if (kind := TEMPERATURE_INPUT_KEYS.get(function)) is None:
            continue
        if function is InputFunction.EXTERNAL_SENSOR and _floor_limit_active(device):
            kind = "floor"
        entities.append(Rdf302InputSensor(entry, number, kind, address))
    async_add_entities(entities)


def _floor_limit_active(device: Rdf302) -> bool:
    """Return whether P51 turns the external sensor into a floor sensor."""
    raw = device.raw(REG_P51)
    return raw is not None and raw >= 10 * TEMP_SCALE


class Rdf302Sensor(Rdf302Entity, SensorEntity):
    """A sensor reading one value from the device."""

    entity_description: Rdf302SensorDescription

    @property
    def native_value(self) -> Any:
        """Return the value."""
        return self.entity_description.value_fn(self.device)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra details, if the sensor has any."""
        if (attributes_fn := self.entity_description.attributes_fn) is None:
            return None
        return attributes_fn(self.device)


class Rdf302FaultSensor(Rdf302Entity, SensorEntity):
    """The fault the thermostat reports."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [fault.value for fault in Fault]
    _attr_translation_key = "active_fault"

    def __init__(self, entry: Rdf302ConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_active_fault"

    @property
    def native_value(self) -> str | None:
        """Return the fault."""
        return self.device.fault

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the text as the thermostat reports it."""
        return {"text": self.device.fault_text}


class Rdf302InputSensor(Rdf302Entity, SensorEntity):
    """A temperature on input X1 or X2.

    The thermostat reports a missing or broken sensor as out of service, so
    the entity is unavailable then rather than unknown.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self, entry: Rdf302ConfigEntry, number: int, kind: str, address: int
    ) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._address = address
        self._attr_unique_id = f"{entry.entry_id}_x{number}_{kind}"
        self._attr_translation_key = f"input_{kind}"
        self._attr_translation_placeholders = {"input": f"X{number}"}
        self._log_name = f"{entry.title} X{number}"
        self._out_of_service = False

    @property
    def available(self) -> bool:
        """Return False while the sensor on the input is out of service."""
        return super().available and not self.device.out_of_service(self._address)

    @property
    def native_value(self) -> float | None:
        """Return the temperature."""
        return self.device.temperature(self._address)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Log when the sensor goes out of service or comes back."""
        out_of_service = self.device.out_of_service(self._address)
        if out_of_service and not self._out_of_service:
            _LOGGER.warning("%s: sensor out of service, check its wiring", self._log_name)
        elif self._out_of_service and not out_of_service:
            _LOGGER.info("%s: sensor back in service", self._log_name)
        self._out_of_service = out_of_service
        super()._handle_coordinator_update()


class Rdf302LastClockSync(Rdf302Entity, RestoreSensor):
    """When the clock was last set, by the button, hourly or after a reconnect."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_clock_sync"

    def __init__(self, entry: Rdf302ConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_last_clock_sync"

    async def async_added_to_hass(self) -> None:
        """Keep the last sync across restarts and reloads."""
        await super().async_added_to_hass()
        if self.runtime.last_clock_sync is None and (
            data := await self.async_get_last_sensor_data()
        ):
            if isinstance(data.native_value, datetime):
                self.runtime.last_clock_sync = data.native_value

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the last successful sync."""
        return self.runtime.last_clock_sync
