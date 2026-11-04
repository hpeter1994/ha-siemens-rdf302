"""Tests for the device library."""

from datetime import UTC, datetime, timedelta, tzinfo

from modbus_connection import IllegalDataAddressError, ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest

from custom_components.siemens_rdf302.rdf302_modbus import (
    REG_P11,
    REG_P12,
    Application,
    Fault,
    InputFunction,
    Model,
    Rdf302,
    decode_text,
    encode_clock,
    encode_text,
)

from .conftest import text_registers


async def _device(unit: MockModbusUnit, **kwargs) -> Rdf302:
    device = Rdf302(unit, **kwargs)
    await device.async_update_fast()
    await device.async_update_slow()
    return device


async def test_reads_stay_inside_access_groups(unit: MockModbusUnit) -> None:
    """No request crosses an address the manual leaves undefined."""
    await _device(unit)
    undefined = {3, 32, 39, 42, 43, 45, 46, 47, 63, 64, 67, 72}
    for event in unit.read_events:
        if event.register_type == "holding":
            span = set(range(event.address, event.address + event.count))
            assert not span & undefined, event


async def test_temperature_scaling_and_out_of_service(unit: MockModbusUnit) -> None:
    """Temperatures are x50, and 0xFFFF means no value."""
    device = await _device(unit)
    assert device.temperature(1003) == 22
    assert device.temperature(1009) is None


async def test_refused_optional_block_is_forgotten(unit: MockModbusUnit) -> None:
    """A refused parameter block does not fail the update."""
    device = await _device(unit)
    unit.fail_read(44, IllegalDataAddressError())
    unit.holding[44] = 150
    await device.async_update_slow()
    assert device.raw(44) is None
    assert device.raw(1) == 2


async def test_dead_link_is_raised(unit: MockModbusUnit) -> None:
    """Timeouts reach the caller even for optional blocks."""
    device = await _device(unit)
    unit.fail_requests(ModbusTimeoutError())
    with pytest.raises(ModbusTimeoutError):
        await device.async_update_slow()


async def test_input_functions_share_a_register(unit: MockModbusUnit) -> None:
    """X1 is the high byte and X2 the low byte."""
    device = await _device(unit)
    assert device.input_function(1) is InputFunction.MODE_CONTACT
    assert device.input_function(2) is InputFunction.EXTERNAL_SENSOR
    await device.async_write_input_function(2, InputFunction.FAULT)
    assert unit.holding[38] == (3 << 8) | 6
    await device.async_write_input_function(1, InputFunction.NOT_USED)
    assert unit.holding[38] == 6


async def test_rdf302b_has_no_inputs(unit: MockModbusUnit) -> None:
    """The .B variant ignores the input registers."""
    device = await _device(unit, model=Model.RDF302_B)
    assert device.input_function(1) is InputFunction.NOT_USED


async def test_application_fallback(unit: MockModbusUnit) -> None:
    """The fallback only applies if the device reports none."""
    device = await _device(unit, application=Application.FOUR_PIPE)
    assert device.application is Application.TWO_PIPE
    unit.holding[109] = 0
    await device.async_update_fast()
    assert device.application is Application.FOUR_PIPE


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("No fault", Fault.NO_FAULT),
        ("", Fault.NO_FAULT),
        ("Filter dirty", Fault.DIRTY_FILTER),
        ("filter DIRTY", Fault.DIRTY_FILTER),
        ("Condensation in room", Fault.CONDENSATION),
        ("Something else", Fault.OTHER),
    ],
)
async def test_fault_matches_stored_text(
    unit: MockModbusUnit, text: str, expected: Fault
) -> None:
    """Faults are recognized from the texts stored in the device."""
    unit.input[1100] = text_registers(text)
    device = await _device(unit)
    assert device.fault is expected


async def test_fault_follows_edited_text(unit: MockModbusUnit) -> None:
    """An edited text still maps to its fault."""
    unit.holding[500] = text_registers("Szuro")
    unit.input[1100] = text_registers("Szuro")
    device = await _device(unit)
    assert device.fault is Fault.DIRTY_FILTER


def test_text_round_trip() -> None:
    """Text survives encoding, and always fills ten registers."""
    values = encode_text("Filter dirty")
    assert len(values) == 10
    assert decode_text(values) == "Filter dirty"


@pytest.mark.parametrize(
    ("p01", "expected"), [(0, REG_P11), (1, REG_P12)]
)
async def test_economy_register_from_fixed_sequence(
    unit: MockModbusUnit, p01: int, expected: int
) -> None:
    """A fixed sequence decides the Economy setpoint."""
    unit.holding[1] = p01
    device = await _device(unit)
    assert device.economy_setpoint_register() == expected


@pytest.mark.parametrize(
    ("effective", "expected"),
    [(15 * 50, REG_P11), (30 * 50, REG_P12), (20 * 50, None)],
)
async def test_economy_register_from_effective_setpoint(
    unit: MockModbusUnit, effective: int, expected: int | None
) -> None:
    """With changeover, the effective setpoint tells which one is in use."""
    unit.input[1004] = effective
    device = await _device(unit)
    assert device.economy_setpoint_register() == expected


async def test_economy_register_ambiguous(unit: MockModbusUnit) -> None:
    """Equal Economy setpoints cannot be told apart."""
    unit.holding[11] = unit.holding[12] = 20 * 50
    unit.input[1004] = 20 * 50
    device = await _device(unit)
    assert device.economy_setpoint_register() is None


@pytest.mark.parametrize(
    ("p09", "p10", "p01", "expected"),
    [
        (18, 25, 2, (18, 25)),
        (25, 21, 0, (5, 21)),
        (25, 21, 1, (25, 40)),
        (25, 21, 2, (5, 21)),
        (25, 21, 4, (5, 40)),
    ],
)
async def test_comfort_limits(
    unit: MockModbusUnit, p09: int, p10: int, p01: int, expected: tuple[int, int]
) -> None:
    """P09 and P10 limit by direction when P09 >= P10."""
    unit.holding |= {9: p09 * 50, 10: p10 * 50, 1: p01}
    device = await _device(unit)
    assert device.comfort_limits() == expected


def test_clock_encoding() -> None:
    """The clock is 8 bytes in KNX DPT 19.001 layout."""
    # 2026-11-01 is a Sunday.
    now = datetime(2026, 11, 1, 13, 45, 30, tzinfo=UTC)
    assert encode_clock(now) == [
        (126 << 8) | 11,
        (1 << 8) | (7 << 5) | 13,
        (45 << 8) | 30,
        0b0010_0000 << 8,
    ]


def test_clock_marks_summer_time() -> None:
    """Summer time sets the SUTI bit."""

    class Summer(tzinfo):
        def utcoffset(self, dt):
            return timedelta(hours=2)

        def dst(self, dt):
            return timedelta(hours=1)

    now = datetime(2026, 7, 1, tzinfo=Summer())
    assert encode_clock(now)[3] == 0b0010_0001 << 8


async def test_negative_value_is_twos_complement(unit: MockModbusUnit) -> None:
    """A negative calibration is stored as 16-bit two's complement."""
    device = await _device(unit)
    await device.async_write(5, -50)
    assert unit.holding[5] == 0xFFCE
    assert device.signed(5) == -50
