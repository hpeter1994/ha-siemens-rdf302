"""Selects for the Siemens RDF302 integration."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import Rdf302ConfigEntry
from .entity import Rdf302Entity
from .rdf302_modbus import (
    REG_INPUT_FUNCTIONS,
    REG_KEY_LOCK,
    REG_P01,
    REG_P02,
    REG_P07,
    REG_P52,
    REG_P53,
    Application,
    InputFunction,
    Rdf302,
)

INPUT_OPTIONS = {
    InputFunction.NOT_USED: "not_used",
    InputFunction.EXTERNAL_SENSOR: "external_sensor",
    InputFunction.CHANGEOVER: "changeover",
    InputFunction.MODE_CONTACT: "mode_contact",
    InputFunction.DEW_POINT: "dew_point",
    InputFunction.HEATER_ENABLE: "heater_enable",
    InputFunction.FAULT: "fault",
    InputFunction.DIGITAL_MONITOR: "digital_monitor",
    InputFunction.TEMP_MONITOR: "temperature_monitor",
}
# The manual allows functions 1-5 on one input only.
UNIQUE_INPUT_FUNCTIONS = frozenset(
    {
        InputFunction.EXTERNAL_SENSOR,
        InputFunction.CHANGEOVER,
        InputFunction.MODE_CONTACT,
        InputFunction.DEW_POINT,
        InputFunction.HEATER_ENABLE,
    }
)
ACTION_OPTIONS = {0: "normally_open", 1: "normally_closed"}
SEQUENCE_OPTIONS = {
    0: "heating_only",
    1: "cooling_only",
    2: "manual_changeover",
    3: "auto_changeover",
    4: "heating_and_cooling",
}


@dataclass(frozen=True, kw_only=True)
class Rdf302SelectDescription(SelectEntityDescription):
    """Describe a select backed by one register."""

    address: int
    values: dict[int, str]
    exists_fn: Callable[[Rdf302], bool] = lambda _: True


def _config(
    key: str, address: int, values: dict[int, str], **kwargs
) -> Rdf302SelectDescription:
    """Describe an expert parameter, disabled by default."""
    return Rdf302SelectDescription(
        key=key,
        translation_key=key,
        address=address,
        values=values,
        options=list(values.values()),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        **kwargs,
    )


def _has_inputs(device: Rdf302) -> bool:
    return device.has_inputs


SELECTS: tuple[Rdf302SelectDescription, ...] = (
    Rdf302SelectDescription(
        key="key_lock",
        translation_key="key_lock",
        address=REG_KEY_LOCK,
        values=(
            lock_values := {
                0: "unlocked",
                1: "plus_minus",
                2: "fan",
                3: "mode",
                4: "all",
            }
        ),
        options=list(lock_values.values()),
    ),
    _config("control_sequence", REG_P01, SEQUENCE_OPTIONS),
    _config(
        "mode_button_profile",
        REG_P02,
        {1: "comfort_protection", 2: "comfort_economy_protection"},
    ),
    _config("display_unit", 4, {0: "celsius", 1: "fahrenheit"}),
    _config(
        "standard_display", 6, {0: "room_temperature", 1: "setpoint", 2: "bus_temperature"}
    ),
    _config(
        "additional_display",
        REG_P07,
        {0: "none", 1: "celsius_fahrenheit", 2: "outside", 3: "time_12h", 4: "time_24h"},
    ),
    _config("local_key_lock", 14, {0: "disabled", 1: "auto", 2: "manual"}),
    _config("input_x1_action", 40, ACTION_OPTIONS, exists_fn=_has_inputs),
    _config("input_x2_action", 41, ACTION_OPTIONS, exists_fn=_has_inputs),
    _config(
        "fan_control",
        REG_P52,
        {0: "disabled", 1: "enabled", 2: "heating_only", 3: "cooling_only"},
    ),
    _config("fan_speeds", REG_P53, {1: "one_speed", 2: "three_speed"}),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Rdf302ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects."""
    device = entry.runtime_data.device
    entities: list[SelectEntity] = [
        Rdf302Select(entry, description)
        for description in SELECTS
        if description.exists_fn(device)
    ]
    if device.has_inputs:
        entities += [Rdf302InputFunction(entry, 1), Rdf302InputFunction(entry, 2)]
    async_add_entities(entities)


class Rdf302Select(Rdf302Entity, SelectEntity):
    """A select backed by one register."""

    entity_description: Rdf302SelectDescription

    @property
    def options(self) -> list[str]:
        """Return the options, narrowed for P01 by the application."""
        description = self.entity_description
        if description.address != REG_P01:
            return list(description.values.values())
        if self.device.application is Application.FOUR_PIPE:
            allowed = (2, 3, 4)
        elif self.device.application is Application.NONE:
            allowed = tuple(description.values)
        else:
            allowed = (0, 1, 2, 3)
        return [description.values[value] for value in allowed]

    @property
    def current_option(self) -> str | None:
        """Return the selected option."""
        description = self.entity_description
        return description.values.get(self.device.raw(description.address))

    async def async_select_option(self, option: str) -> None:
        """Write the selected option."""
        description = self.entity_description
        raw = next(key for key, name in description.values.items() if name == option)
        await self.runtime.async_write(description.address, raw)


class Rdf302InputFunction(Rdf302Entity, SelectEntity):
    """The function of input X1 or X2, which share a register."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_options = list(INPUT_OPTIONS.values())

    def __init__(self, entry: Rdf302ConfigEntry, number: int) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._number = number
        self._attr_unique_id = f"{entry.entry_id}_input_x{number}_function"
        self._attr_translation_key = f"input_x{number}_function"

    @property
    def current_option(self) -> str | None:
        """Return the selected function."""
        return INPUT_OPTIONS[self.device.input_function(self._number)]

    async def async_select_option(self, option: str) -> None:
        """Write the function, keeping the other input's."""
        function = next(key for key, name in INPUT_OPTIONS.items() if name == option)
        other = self.device.input_function(3 - self._number)
        if function in UNIQUE_INPUT_FUNCTIONS and function is other:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="input_function_in_use",
            )
        await self.runtime.async_call(
            self.device.async_write_input_function(self._number, function)
        )
        await self.runtime.async_refresh_after_write(REG_INPUT_FUNCTIONS)
