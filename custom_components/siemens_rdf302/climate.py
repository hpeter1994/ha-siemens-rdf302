"""Climate entity for the Siemens RDF302 integration."""

from typing import Any

from homeassistant.components.climate import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    PRESET_COMFORT,
    PRESET_ECO,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import Rdf302ConfigEntry
from .entity import Rdf302Entity
from .rdf302_modbus import (
    MODE_COMFORT,
    MODE_ECONOMY,
    MODE_PROTECTION,
    REG_CHANGEOVER,
    REG_COMFORT_SETPOINT,
    REG_COOLING_OUTPUT,
    REG_FAN_COMMAND,
    REG_FAN_OPERATION,
    REG_FAN_OUTPUT,
    REG_HEATER_OUTPUT,
    REG_HEATING_OUTPUT,
    REG_MODE_COMMAND,
    REG_MODE_STATE,
    REG_P01,
    REG_P53,
    REG_ROOM_TEMP,
    TEMP_SCALE,
)

FAN_TO_RAW = {FAN_AUTO: 0, FAN_LOW: 33, FAN_MEDIUM: 66, FAN_HIGH: 100}
RAW_TO_MANUAL_FAN = {33: FAN_LOW, 66: FAN_MEDIUM, 100: FAN_HIGH}
PRESET_TO_MODE = {PRESET_COMFORT: MODE_COMFORT, PRESET_ECO: MODE_ECONOMY}
MODE_TO_PRESET = {mode: preset for preset, mode in PRESET_TO_MODE.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Rdf302ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the climate entity."""
    async_add_entities([Rdf302Climate(entry)])


class Rdf302Climate(Rdf302Entity, ClimateEntity):
    """The thermostat. Protection mode is its closest thing to off."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_precision = PRECISION_TENTHS
    _attr_preset_modes = list(PRESET_TO_MODE)
    _attr_translation_key = "thermostat"

    def __init__(self, entry: Rdf302ConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        self._attr_unique_id = entry.entry_id
        self._last_mode = MODE_COMFORT
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if self.device.has_fan:
            features |= ClimateEntityFeature.FAN_MODE
            self._attr_fan_modes = (
                [FAN_AUTO, FAN_LOW]
                if self.device.raw(REG_P53) == 1
                else list(FAN_TO_RAW)
            )
        self._attr_supported_features = features

    def _active_hvac_modes(self) -> list[HVACMode]:
        """Return the modes the control sequence (P01) allows besides off."""
        match self.device.raw(REG_P01):
            case 0:
                return [HVACMode.HEAT]
            case 1:
                return [HVACMode.COOL]
            case 2 if self.device.changeover is not None:
                # Only the wall button changes direction; show the one it chose.
                return [HVACMode.HEAT if self.device.changeover else HVACMode.COOL]
            case 3 if self.device.modbus_changeover:
                return [HVACMode.HEAT, HVACMode.COOL]
            case 4:
                return [HVACMode.HEAT_COOL]
        return [HVACMode.AUTO]

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the modes that can be selected."""
        return [*self._active_hvac_modes(), HVACMode.OFF]

    @property
    def _mode(self) -> int | None:
        """Return the effective operating mode."""
        return self.device.raw(REG_MODE_STATE)

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current mode."""
        if self._mode == MODE_PROTECTION:
            return HVACMode.OFF
        if self.device.modbus_changeover:
            if self.device.changeover == 1:
                return HVACMode.HEAT
            return HVACMode.COOL
        return self._active_hvac_modes()[0]

    @property
    def hvac_action(self) -> HVACAction:
        """Return what the outputs are doing."""
        if self.device.raw(REG_HEATING_OUTPUT) or self.device.raw(REG_HEATER_OUTPUT):
            return HVACAction.HEATING
        if self.device.raw(REG_COOLING_OUTPUT):
            return HVACAction.COOLING
        if self.device.raw(REG_FAN_OUTPUT):
            return HVACAction.FAN
        return HVACAction.OFF if self._mode == MODE_PROTECTION else HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        """Return the room temperature."""
        return self.device.temperature(REG_ROOM_TEMP)

    @property
    def target_temperature(self) -> float | None:
        """Return the effective setpoint."""
        return self.device.setpoint_active

    @property
    def min_temp(self) -> float:
        """Return the lowest setpoint; P09 only limits Comfort."""
        return self.device.comfort_limits()[0] if self._mode == MODE_COMFORT else 5.0

    @property
    def max_temp(self) -> float:
        """Return the highest setpoint; P10 only limits Comfort."""
        return self.device.comfort_limits()[1] if self._mode == MODE_COMFORT else 40.0

    @property
    def preset_mode(self) -> str | None:
        """Return the preset for Comfort and Economy."""
        return MODE_TO_PRESET.get(self._mode)

    @property
    def fan_mode(self) -> str | None:
        """Return the fan mode."""
        if self.device.raw(REG_FAN_OPERATION) == 0:
            return FAN_AUTO
        return RAW_TO_MANUAL_FAN.get(
            self.device.raw(REG_FAN_COMMAND)
        ) or RAW_TO_MANUAL_FAN.get(self.device.raw(REG_FAN_OUTPUT))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the setpoint belonging to the current operating mode."""
        if (hvac_mode := kwargs.get("hvac_mode")) is not None:
            await self.async_set_hvac_mode(hvac_mode)
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        if self._mode == MODE_COMFORT:
            address = REG_COMFORT_SETPOINT
        elif self._mode == MODE_ECONOMY:
            address = self.device.economy_setpoint_register()
            if address is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="economy_setpoint_unknown",
                )
            if not self.device.economy_setpoint_allowed(address, temperature):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="economy_setpoint_crossed",
                )
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="setpoint_in_protection",
            )
        await self.runtime.async_write(address, round(temperature * TEMP_SCALE))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the mode."""
        if hvac_mode == HVACMode.OFF:
            if self._mode in MODE_TO_PRESET:
                self._last_mode = self._mode
            await self.runtime.async_write(REG_MODE_COMMAND, MODE_PROTECTION)
            return
        if self.device.modbus_changeover:
            await self.runtime.async_write(
                REG_CHANGEOVER, 1 if hvac_mode == HVACMode.HEAT else 0
            )
        if self._mode == MODE_PROTECTION:
            await self.runtime.async_write(REG_MODE_COMMAND, self._last_mode)

    async def async_turn_on(self) -> None:
        """Leave Protection without changing the heating or cooling direction."""
        if self._mode == MODE_PROTECTION:
            await self.runtime.async_write(REG_MODE_COMMAND, self._last_mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set Comfort or Economy."""
        await self.runtime.async_write(REG_MODE_COMMAND, PRESET_TO_MODE[preset_mode])

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan mode."""
        await self.runtime.async_write(REG_FAN_COMMAND, FAN_TO_RAW[fan_mode])
