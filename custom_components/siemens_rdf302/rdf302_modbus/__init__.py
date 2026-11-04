"""Talk to a Siemens RDF302 room thermostat over Modbus.

Register data comes from the RDF302 Basic documentation, CE1P3079en, section 3.12.
Addresses in this package are the manual's. On the wire every register sits one
lower, as measured on a real RDF302; only the unit I/O below applies that.
This package has no Home Assistant dependency.
"""

from collections.abc import Mapping
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Final

from modbus_connection import ModbusExceptionError, ModbusUnit

ADDRESS_OFFSET: Final = 1
TEMP_SCALE: Final = 50
OUT_OF_SERVICE: Final = 0xFFFF
TEXT_REGISTERS: Final = 10

# Operating mode
REG_MODE_STATE: Final = 1001
REG_MODE_COMMAND: Final = 101

# Input registers (function 0x04)
REG_FAN_OUTPUT: Final = 1002
REG_ROOM_TEMP: Final = 1003
REG_CURRENT_SETPOINT: Final = 1004
REG_HEATING_OUTPUT: Final = 1005
REG_COOLING_OUTPUT: Final = 1006
REG_HEATER_OUTPUT: Final = 1007
REG_X1_TEMP: Final = 1008
REG_X2_TEMP: Final = 1009
REG_FAN_OPERATION: Final = 1010
REG_X1_DIGITAL: Final = 1011
REG_X2_DIGITAL: Final = 1012
REG_FAULT: Final = 1100

# Runtime holding registers
REG_FAN_COMMAND: Final = 102
REG_COMFORT_SETPOINT: Final = 103
REG_OUTSIDE_TEMP: Final = 104
REG_WINDOW: Final = 105
REG_HEATER_ENABLE: Final = 106
REG_CHANGEOVER: Final = 107
REG_KEY_LOCK: Final = 108
REG_PLANT_TYPE: Final = 109
REG_CLOCK: Final = 600

# Parameters. The address is the parameter number except for P38-P41 and P46.
REG_P01: Final = 1
REG_P02: Final = 2
REG_P05: Final = 5
REG_P07: Final = 7
CLOCK_DISPLAY_VALUES: Final = (3, 4)
REG_P09: Final = 9
REG_P10: Final = 10
REG_P11: Final = 11
REG_P12: Final = 12
REG_INPUT_FUNCTIONS: Final = 38
REG_P51: Final = 51
REG_P52: Final = 52
REG_P53: Final = 53
REG_P65: Final = 65
REG_P66: Final = 66

REG_FAULT_TEXT_1: Final = 200
REG_FAULT_TEXT_2: Final = 300
REG_FAULT_TEXT_3: Final = 400
REG_FAULT_TEXT_4: Final = 500

# Requests never span an access group or a gap, as the manual does not allow it.
_FAST_INPUT_REQUIRED: Final = (REG_MODE_STATE, 12)
_FAST_HOLDING: Final = (REG_MODE_COMMAND, 9)
_FAST_FAULT: Final = (REG_FAULT, TEXT_REGISTERS)
# Fast registers that move on their own, so they don't count as a change.
_MEASUREMENTS: Final = frozenset(
    {
        REG_FAN_OUTPUT,
        REG_ROOM_TEMP,
        REG_HEATING_OUTPUT,
        REG_COOLING_OUTPUT,
        REG_HEATER_OUTPUT,
        REG_X1_TEMP,
        REG_X2_TEMP,
    }
)
_SLOW_HOLDING: Final = (
    (REG_P01, 1),
    (REG_P02, 1),
    (4, 11),
    (30, 2),
    (33, 5),
    (REG_INPUT_FUNCTIONS, 1),
    (40, 2),
    (44, 1),
    (182, 1),
    (48, 15),
    (REG_P65, 1),
    (REG_P66, 1),
    (68, 4),
    (81, 1),
    (REG_FAULT_TEXT_1, TEXT_REGISTERS),
    (REG_FAULT_TEXT_2, TEXT_REGISTERS),
    (REG_FAULT_TEXT_3, TEXT_REGISTERS),
    (REG_FAULT_TEXT_4, TEXT_REGISTERS),
)

_NO_FAULT_TEXTS: Final = frozenset({"", "no fault", "---"})

MODE_COMFORT: Final = 1
MODE_ECONOMY: Final = 3
MODE_PROTECTION: Final = 4
VALID_MODES: Final = frozenset({MODE_COMFORT, MODE_ECONOMY, MODE_PROTECTION})

# A setpoint register below or above these holds an "OFF" marker, not a setpoint.
_SETPOINT_MIN_RAW: Final = 5 * TEMP_SCALE
_SETPOINT_MAX_RAW: Final = 40 * TEMP_SCALE


class Model(StrEnum):
    """Hardware variants. No register tells them apart."""

    RDF302 = "rdf302"
    RDF302_VB = "rdf302_vb"
    RDF302_B = "rdf302_b"


class Application(IntEnum):
    """Values of the plant type register."""

    NONE = 0
    TWO_PIPE = 1
    TWO_PIPE_3POS = 2
    TWO_PIPE_HEATER = 3
    FOUR_PIPE = 4


class InputFunction(IntEnum):
    """Functions of multifunctional inputs X1 and X2 (P38, P40)."""

    NOT_USED = 0
    EXTERNAL_SENSOR = 1
    CHANGEOVER = 2
    MODE_CONTACT = 3
    DEW_POINT = 4
    HEATER_ENABLE = 5
    FAULT = 6
    DIGITAL_MONITOR = 7
    TEMP_MONITOR = 8


# Changeover takes a sensor or a switch; the others below are switches only.
_SWITCH_INPUT_FUNCTIONS: Final = frozenset(
    {
        InputFunction.CHANGEOVER,
        InputFunction.MODE_CONTACT,
        InputFunction.DEW_POINT,
        InputFunction.HEATER_ENABLE,
        InputFunction.FAULT,
        InputFunction.DIGITAL_MONITOR,
    }
)


class Fault(StrEnum):
    """The fault the bus reports. Only the highest-priority one is visible."""

    NO_FAULT = "no_fault"
    CONDENSATION = "condensation"
    INPUT_1 = "fault_input_1"
    INPUT_2 = "fault_input_2"
    DIRTY_FILTER = "dirty_filter"
    OTHER = "other"


class Rdf302:
    """One thermostat, holding the registers read from it most recently."""

    def __init__(
        self,
        unit: ModbusUnit,
        model: Model = Model.RDF302,
        application: Application = Application.NONE,
    ) -> None:
        """Initialize, with the application to assume if the device reports none."""
        self._unit = unit
        self.model = model
        self._application_fallback = application
        self.registers: dict[int, int] = {}

    async def async_update_fast(self) -> None:
        """Read the runtime registers."""
        address, count = _FAST_INPUT_REQUIRED
        self._store(address, await self._read_input(address, count))
        address, count = _FAST_HOLDING
        await self._read_optional(self._read_holding, address, count)
        address, count = _FAST_FAULT
        await self._read_optional(self._read_input, address, count)

    async def async_update_slow(self) -> None:
        """Read the parameters and fault texts."""
        for address, count in _SLOW_HOLDING:
            await self._read_optional(self._read_holding, address, count)

    async def _read_input(self, address: int, count: int) -> list[int]:
        return await self._unit.read_input_registers(address - ADDRESS_OFFSET, count)

    async def _read_holding(self, address: int, count: int) -> list[int]:
        return await self._unit.read_holding_registers(address - ADDRESS_OFFSET, count)

    async def _read_optional(self, read, address: int, count: int) -> None:
        """Read a block, forgetting it if the device refuses to serve it.

        A dead link raises other errors, which reach the caller.
        """
        try:
            values = await read(address, count)
        except ModbusExceptionError:
            for offset in range(count):
                self.registers.pop(address + offset, None)
        else:
            self._store(address, values)

    def _store(self, address: int, values: list[int]) -> None:
        for offset, value in enumerate(values):
            self.registers[address + offset] = value

    async def async_write(self, address: int, value: int) -> None:
        """Write one register; negative values are stored as two's complement."""
        raw = value & 0xFFFF
        await self._unit.write_register(address - ADDRESS_OFFSET, raw)
        self.registers[address] = raw

    async def async_write_text(self, address: int, text: str) -> None:
        """Write a fault text."""
        values = encode_text(text)
        await self._unit.write_registers(address - ADDRESS_OFFSET, values)
        self._store(address, values)

    async def async_write_input_function(
        self, number: int, function: InputFunction
    ) -> None:
        """Set one of the two input functions sharing a register."""
        current = await self._read_holding(REG_INPUT_FUNCTIONS, 1)
        if number == 1:
            raw = (current[0] & 0x00FF) | (int(function) << 8)
        else:
            raw = (current[0] & 0xFF00) | int(function)
        await self.async_write(REG_INPUT_FUNCTIONS, raw)

    async def async_set_clock(self, now: datetime) -> None:
        """Set the time of day shown on the display."""
        await self._unit.write_registers(
            REG_CLOCK - ADDRESS_OFFSET, encode_clock(now)
        )

    def runtime_state(self) -> tuple[int | None, ...]:
        """Return the fast registers set by someone, leaving out measurements."""
        return tuple(
            self.raw(address + offset)
            for address, count in (_FAST_INPUT_REQUIRED, _FAST_HOLDING, _FAST_FAULT)
            for offset in range(count)
            if address + offset not in _MEASUREMENTS
        )

    def raw(self, address: int) -> int | None:
        """Return a register as read, or None if it is not known."""
        return self.registers.get(address)

    def signed(self, address: int) -> int | None:
        """Return a register read as a signed 16-bit value."""
        if (raw := self.raw(address)) is None:
            return None
        return raw - 0x10000 if raw >= 0x8000 else raw

    def temperature(self, address: int) -> float | None:
        """Return a temperature register in °C, or None if out of service."""
        raw = self.raw(address)
        if raw is None or raw == OUT_OF_SERVICE:
            return None
        return raw / TEMP_SCALE

    @property
    def application(self) -> Application:
        """Return the application, preferring what the device reports."""
        raw = self.raw(REG_PLANT_TYPE)
        if raw in Application._value2member_map_ and raw != Application.NONE:
            return Application(raw)
        return self._application_fallback

    @property
    def has_heater(self) -> bool:
        """Return whether an electric heater is part of the application."""
        return self.application is Application.TWO_PIPE_HEATER

    @property
    def is_three_position(self) -> bool:
        """Return whether the outputs drive a 3-position actuator."""
        return self.application is Application.TWO_PIPE_3POS

    @property
    def has_inputs(self) -> bool:
        """Return whether this model has inputs X1 and X2."""
        return self.model is not Model.RDF302_B

    def input_function(self, number: int) -> InputFunction:
        """Return the function of input 1 or 2."""
        raw = self.raw(REG_INPUT_FUNCTIONS)
        if raw is None or not self.has_inputs:
            return InputFunction.NOT_USED
        value = raw >> 8 if number == 1 else raw & 0xFF
        if value in InputFunction._value2member_map_:
            return InputFunction(value)
        return InputFunction.NOT_USED

    def input_has_action(self, number: int) -> bool:
        """Return whether NO/NC (P39, P41) applies, which it only does to switches."""
        return self.input_function(number) in _SWITCH_INPUT_FUNCTIONS

    def has_input_function(self, function: InputFunction) -> bool:
        """Return whether either input has this function."""
        return function in (self.input_function(1), self.input_function(2))

    @property
    def has_fan(self) -> bool:
        """Return whether the fan is enabled (P52)."""
        return self.raw(REG_P52) != 0

    @property
    def can_heat(self) -> bool:
        """Return whether anything can heat: P01 not cooling only, or a heater."""
        return self.raw(REG_P01) != 1 or self.has_heater

    @property
    def can_cool(self) -> bool:
        """Return whether P01 allows cooling."""
        return self.raw(REG_P01) != 0

    @property
    def modbus_changeover(self) -> bool:
        """Return whether heating/cooling can be changed over the bus."""
        return self.raw(REG_P01) == 3 and not self.has_input_function(
            InputFunction.CHANGEOVER
        )

    @property
    def changeover(self) -> int | None:
        """Return the heating/cooling direction (107), where it is known.

        It follows the bus with Modbus changeover and the wall button with
        manual changeover, which ignores bus writes.
        """
        if self.modbus_changeover or self.raw(REG_P01) == 2:
            return self.raw(REG_CHANGEOVER)
        return None

    @property
    def fault_text(self) -> str | None:
        """Return the fault text as reported."""
        return self._text(REG_FAULT)

    @property
    def fault(self) -> Fault | None:
        """Return the active fault.

        The reported text is user-editable, so it is compared with the texts
        stored in the device instead of known defaults.
        """
        if (text := self.fault_text) is None:
            return None
        normalized = text.casefold()
        if normalized in _NO_FAULT_TEXTS:
            return Fault.NO_FAULT
        for address, fault in (
            (REG_FAULT_TEXT_1, Fault.CONDENSATION),
            (REG_FAULT_TEXT_2, Fault.INPUT_1),
            (REG_FAULT_TEXT_3, Fault.INPUT_2),
            (REG_FAULT_TEXT_4, Fault.DIRTY_FILTER),
        ):
            stored = self._text(address)
            if stored and stored.casefold() == normalized:
                return fault
        return Fault.OTHER

    def fault_template(self, address: int) -> str | None:
        """Return a stored fault text."""
        return self._text(address)

    def _text(self, address: int) -> str | None:
        values = [self.raw(address + offset) for offset in range(TEXT_REGISTERS)]
        if None in values:
            return None
        return decode_text(values)

    @property
    def setpoint_active(self) -> float | None:
        """Return the effective setpoint, or None if control is off."""
        return _setpoint(self.raw(REG_CURRENT_SETPOINT))

    @property
    def setpoint_off(self) -> bool | None:
        """Return whether the setpoint in use is set to OFF, or None if unknown."""
        if (raw := self.raw(REG_CURRENT_SETPOINT)) is None:
            return None
        return _setpoint(raw) is None

    def out_of_service(self, address: int) -> bool:
        """Return whether a temperature register reports its sensor out of service."""
        return self.raw(address) == OUT_OF_SERVICE

    def economy_setpoint_register(self) -> int | None:
        """Return which Economy setpoint is in use, or None if it cannot be told.

        No register states the direction when changeover is in use, so the
        effective setpoint is matched against both Economy setpoints.
        """
        match self.raw(REG_P01):
            case 0:
                return REG_P11
            case 1:
                return REG_P12
        current = self.raw(REG_CURRENT_SETPOINT)
        if current is None:
            return None
        matches = [
            address
            for address in (REG_P11, REG_P12)
            if self.raw(address) == current
        ]
        return matches[0] if len(matches) == 1 else None

    def economy_setpoint_allowed(self, address: int, value: float) -> bool:
        """Return whether a value keeps heating at or below cooling (Economy)."""
        raw = round(value * TEMP_SCALE)
        other = self.raw(REG_P12 if address == REG_P11 else REG_P11)
        if _setpoint(other) is None:
            return True
        return raw <= other if address == REG_P11 else raw >= other

    def comfort_limits(self) -> tuple[float, float]:
        """Return the Comfort setpoint range (P09, P10) for the current direction."""
        lower = self.temperature(REG_P09)
        upper = self.temperature(REG_P10)
        if lower is None or upper is None:
            return 5.0, 40.0
        if lower < upper:
            return lower, upper
        p01 = self.raw(REG_P01)
        changeover = self.changeover
        if p01 == 0 or changeover == 1:
            return 5.0, upper
        if p01 == 1 or changeover == 0:
            return lower, 40.0
        return 5.0, 40.0

    def structure_key(self) -> tuple[object, ...]:
        """Return the settings deciding which entities and features exist."""
        return (
            self.application,
            *(
                self.raw(address)
                for address in (
                    REG_P01,
                    REG_INPUT_FUNCTIONS,
                    REG_P07,
                    REG_P51,
                    REG_P52,
                    REG_P53,
                )
            ),
        )


def _setpoint(raw: int | None) -> float | None:
    """Decode a setpoint register, treating its OFF markers as no setpoint."""
    if raw is None or not _SETPOINT_MIN_RAW <= raw <= _SETPOINT_MAX_RAW:
        return None
    return raw / TEMP_SCALE


def decode_text(values: list[int]) -> str:
    """Decode registers holding ASCII text, two characters per register."""
    data = b"".join(value.to_bytes(2) for value in values)
    return data.split(b"\0", 1)[0].decode("ascii", "replace").strip()


def encode_text(text: str) -> list[int]:
    """Encode text into fault text registers, padded with spaces like the device."""
    data = text.encode("ascii").ljust(TEXT_REGISTERS * 2)
    return [
        int.from_bytes(data[index : index + 2])
        for index in range(0, TEXT_REGISTERS * 2, 2)
    ]


def encode_clock(now: datetime) -> list[int]:
    """Encode a time as the 8 bytes of KNX DPT 19.001 the manual describes.

    Flags: day-type field marked not valid, summer time set when in effect.
    """
    flags = 0b0010_0000 | (1 if now.dst() else 0)
    return [
        ((now.year - 1900) << 8) | now.month,
        (now.day << 8) | (now.isoweekday() << 5) | now.hour,
        (now.minute << 8) | now.second,
        flags << 8,
    ]


def is_thermostat(registers: Mapping[int, int]) -> bool:
    """Return whether the operating mode register holds a value it can hold."""
    return registers.get(REG_MODE_STATE) in VALID_MODES
