"""Numbers for the Siemens RDF302 integration."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Rdf302ConfigEntry
from .entity import Rdf302Entity
from .rdf302_modbus import (
    REG_COMFORT_SETPOINT,
    REG_OUTSIDE_TEMP,
    REG_P05,
    REG_P07,
    REG_P09,
    REG_P10,
    REG_P11,
    REG_P12,
    REG_P51,
    REG_P65,
    REG_P66,
    TEMP_SCALE,
    InputFunction,
    Rdf302,
)


@dataclass(frozen=True, kw_only=True)
class Rdf302NumberDescription(NumberEntityDescription):
    """Describe a number backed by one register."""

    address: int
    scale: int = 1
    exists_fn: Callable[[Rdf302], bool] = lambda _: True
    max_fn: Callable[[Rdf302], float | None] | None = None
    min_fn: Callable[[Rdf302], float | None] | None = None


def _temp_kwargs() -> dict[str, object]:
    return {
        "device_class": NumberDeviceClass.TEMPERATURE,
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "scale": TEMP_SCALE,
        "native_step": 0.5,
    }


def _kelvin_kwargs() -> dict[str, object]:
    return {
        "native_unit_of_measurement": UnitOfTemperature.KELVIN,
        "scale": TEMP_SCALE,
        "native_step": 0.5,
    }


def _on_setpoint(address: int) -> Callable[[Rdf302], float | None]:
    """Read a paired setpoint, ignoring it while its OFF marker is set."""

    def value(device: Rdf302) -> float | None:
        temperature = device.temperature(address)
        if temperature is None or not 5 <= temperature <= 40:
            return None
        return temperature

    return value


def _config(key: str, address: int, **kwargs) -> Rdf302NumberDescription:
    """Describe an expert parameter, disabled by default."""
    return Rdf302NumberDescription(
        key=key,
        translation_key=key,
        address=address,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        **kwargs,
    )


def _setpoint_pair(
    key: str, address: int, off: float, low: bool, other: int
) -> Rdf302NumberDescription:
    """Describe a heating or cooling setpoint limited by its partner."""
    return Rdf302NumberDescription(
        key=key,
        translation_key=key,
        address=address,
        entity_category=EntityCategory.CONFIG,
        native_min_value=off if low else 5,
        native_max_value=40 if low else off,
        max_fn=_on_setpoint(other) if low else None,
        min_fn=None if low else _on_setpoint(other),
        **_temp_kwargs(),
    )


def _heater(device: Rdf302) -> bool:
    return device.has_heater


def _three_position(device: Rdf302) -> bool:
    return device.is_three_position


def _changeover_input(device: Rdf302) -> bool:
    return device.has_input_function(InputFunction.CHANGEOVER)


NUMBERS: tuple[Rdf302NumberDescription, ...] = (
    Rdf302NumberDescription(
        key="comfort_setpoint",
        translation_key="comfort_setpoint",
        address=REG_COMFORT_SETPOINT,
        native_min_value=5,
        native_max_value=40,
        **_temp_kwargs(),
    ),
    Rdf302NumberDescription(
        key="outside_temperature",
        translation_key="outside_temperature",
        address=REG_OUTSIDE_TEMP,
        native_min_value=0,
        native_max_value=49,
        exists_fn=lambda device: device.raw(REG_P07) == 2,
        **_temp_kwargs(),
    ),
    _setpoint_pair("economy_heating_setpoint", REG_P11, 4.5, True, REG_P12),
    _setpoint_pair("economy_cooling_setpoint", REG_P12, 40.5, False, REG_P11),
    _setpoint_pair("protection_heating_setpoint", REG_P65, 4.5, True, REG_P66),
    _setpoint_pair("protection_cooling_setpoint", REG_P66, 40.5, False, REG_P65),
    _config("sensor_calibration", REG_P05, native_min_value=-3, native_max_value=3, **_kelvin_kwargs()),
    _config("comfort_basic_setpoint", 8, native_min_value=5, native_max_value=40, **_temp_kwargs()),
    _config("setpoint_minimum", REG_P09, native_min_value=5, native_max_value=40, **_temp_kwargs()),
    _config("setpoint_maximum", REG_P10, native_min_value=5, native_max_value=40, **_temp_kwargs()),
    _config("differential_heating", 30, native_min_value=0.5, native_max_value=6, **_kelvin_kwargs()),
    _config("differential_cooling", 31, native_min_value=0.5, native_max_value=6, **_kelvin_kwargs()),
    _config("dead_zone", 33, native_min_value=0.5, native_max_value=5, **_kelvin_kwargs()),
    _config("setpoint_differential", 34, native_min_value=0.5, native_max_value=5, exists_fn=_heater, **_kelvin_kwargs()),
    _config("integral_time", 35, native_min_value=0, native_max_value=10, native_step=1, native_unit_of_measurement=UnitOfTime.MINUTES, exists_fn=_three_position),
    _config("changeover_cooling_point", 36, native_min_value=10, native_max_value=25, exists_fn=_changeover_input, **_temp_kwargs()),
    _config("changeover_heating_point", 37, native_min_value=27, native_max_value=40, exists_fn=_changeover_input, **_temp_kwargs()),
    _config("actuator_run_time", 44, native_min_value=20, native_max_value=300, native_step=1, native_unit_of_measurement=UnitOfTime.SECONDS, exists_fn=_three_position),
    _config("heater_load_current", 182, native_min_value=0, native_max_value=5, native_step=0.1, scale=10, native_unit_of_measurement=UnitOfElectricCurrent.AMPERE, device_class=NumberDeviceClass.CURRENT, exists_fn=_heater),
    _config("minimum_on_time", 48, native_min_value=1, native_max_value=20, native_step=1, native_unit_of_measurement=UnitOfTime.MINUTES),
    _config("minimum_off_time", 49, native_min_value=1, native_max_value=20, native_step=1, native_unit_of_measurement=UnitOfTime.MINUTES),
    _config("purge_time", 50, native_min_value=0, native_max_value=5, native_step=1, native_unit_of_measurement=UnitOfTime.MINUTES, exists_fn=_changeover_input),
    _config("floor_temperature_limit", REG_P51, native_min_value=9, native_max_value=50, native_step=1, device_class=NumberDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS, scale=TEMP_SCALE),
    _config("fan_overrun", 54, native_min_value=0, native_max_value=360, native_step=1, native_unit_of_measurement=UnitOfTime.SECONDS, exists_fn=_heater),
    _config("fan_point_high", 55, native_min_value=80, native_max_value=100, native_step=1, native_unit_of_measurement=PERCENTAGE),
    _config("fan_point_medium", 56, native_min_value=30, native_max_value=75, native_step=1, native_unit_of_measurement=PERCENTAGE),
    _config("fan_point_low", 57, native_min_value=1, native_max_value=15, native_step=1, native_unit_of_measurement=PERCENTAGE),
    _config("fan_minimum_on_time", 59, native_min_value=1, native_max_value=6, native_step=1, native_unit_of_measurement=UnitOfTime.MINUTES),
    _config("fan_kick_comfort", 60, native_min_value=0, native_max_value=90, native_step=1, native_unit_of_measurement=UnitOfTime.MINUTES),
    _config("fan_kick_economy", 61, native_min_value=0, native_max_value=360, native_step=1, native_unit_of_measurement=UnitOfTime.MINUTES),
    _config("filter_service_interval", 62, native_min_value=0, native_max_value=9900, native_step=100, native_unit_of_measurement=UnitOfTime.HOURS),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Rdf302ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the numbers."""
    device = entry.runtime_data.device
    async_add_entities(
        Rdf302Number(entry, description)
        for description in NUMBERS
        if description.exists_fn(device)
    )


class Rdf302Number(Rdf302Entity, NumberEntity):
    """A number backed by one register."""

    entity_description: Rdf302NumberDescription
    _attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        """Return the value."""
        description = self.entity_description
        raw = self.device.signed(description.address)
        if raw is None or raw == -1:
            return None
        return raw / description.scale

    @property
    def native_min_value(self) -> float:
        """Return the minimum, which a paired setpoint may raise."""
        description = self.entity_description
        limit = description.min_fn(self.device) if description.min_fn else None
        return limit if limit is not None else description.native_min_value

    @property
    def native_max_value(self) -> float:
        """Return the maximum, which a paired setpoint may lower."""
        description = self.entity_description
        limit = description.max_fn(self.device) if description.max_fn else None
        return limit if limit is not None else description.native_max_value

    async def async_set_native_value(self, value: float) -> None:
        """Write the value."""
        description = self.entity_description
        await self.runtime.async_write(
            description.address, round(value * description.scale)
        )
