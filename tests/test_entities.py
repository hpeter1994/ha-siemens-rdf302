"""Tests for the entities."""

from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.climate import HVACMode
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import setup_entry

CLIMATE = "climate.rdf302"

pytestmark = pytest.mark.usefixtures("mock_link")


async def _climate(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(
        "climate", service, {"entity_id": CLIMATE, **data}, blocking=True
    )


@pytest.mark.parametrize(
    ("p01", "input_function", "modes"),
    [
        (0, 3, {HVACMode.HEAT, HVACMode.OFF}),
        (1, 3, {HVACMode.COOL, HVACMode.OFF}),
        (2, 3, {HVACMode.AUTO, HVACMode.OFF}),
        (3, 3, {HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF}),
        (3, 2, {HVACMode.AUTO, HVACMode.OFF}),
        (4, 3, {HVACMode.HEAT_COOL, HVACMode.OFF}),
    ],
)
async def test_hvac_modes_follow_p01(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    unit: MockModbusUnit,
    p01: int,
    input_function: int,
    modes: set[HVACMode],
) -> None:
    """The control sequence decides the modes on offer."""
    unit.holding[1] = p01
    unit.holding[38] = (input_function << 8) | 1
    await setup_entry(hass, entry)
    assert set(hass.states.get(CLIMATE).attributes["hvac_modes"]) == modes


async def test_climate_state(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Values are decoded from the registers."""
    await setup_entry(hass, entry)
    state = hass.states.get(CLIMATE)
    assert state.state == HVACMode.AUTO
    assert state.attributes["current_temperature"] == 22
    assert state.attributes["temperature"] == 21
    assert state.attributes["preset_mode"] == "comfort"
    assert state.attributes["fan_mode"] == "auto"
    assert state.attributes["hvac_action"] == "heating"
    assert state.attributes["min_temp"] == 5
    assert state.attributes["max_temp"] == 35


async def test_preset_comes_from_effective_state(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """A window contact forcing Economy shows, though 101 still says Comfort."""
    unit.input[1001] = 3
    await setup_entry(hass, entry)
    assert hass.states.get(CLIMATE).attributes["preset_mode"] == "eco"


async def test_off_is_protection_and_on_restores(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """Off writes Protection; turning on returns to the previous mode."""
    unit.input[1001] = 3
    await setup_entry(hass, entry)
    await _climate(hass, "set_hvac_mode", hvac_mode="off")
    assert unit.holding[101] == 4

    unit.input[1001] = 4
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(CLIMATE).state == HVACMode.OFF
    assert hass.states.get(CLIMATE).attributes["preset_mode"] is None

    await _climate(hass, "set_hvac_mode", hvac_mode="auto")
    assert unit.holding[101] == 3


async def test_turn_on_keeps_direction(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """Turning on in cooling must not switch to heating."""
    unit.holding[1] = 3
    unit.holding[107] = 0
    unit.input[1001] = 3
    await setup_entry(hass, entry)
    await _climate(hass, "turn_off")
    assert unit.holding[101] == 4

    unit.input[1001] = 4
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()
    await _climate(hass, "turn_on")
    assert unit.holding[101] == 3
    assert unit.holding[107] == 0


async def test_changeover_written_over_bus(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """With bus changeover, heat and cool write 107."""
    unit.holding[1] = 3
    await setup_entry(hass, entry)
    assert hass.states.get(CLIMATE).state == HVACMode.HEAT
    await _climate(hass, "set_hvac_mode", hvac_mode="cool")
    assert unit.holding[107] == 0
    assert hass.states.get(CLIMATE).state == HVACMode.COOL


async def test_target_in_comfort(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """In Comfort the Comfort setpoint is written, scaled."""
    await setup_entry(hass, entry)
    await _climate(hass, "set_temperature", temperature=22.5)
    assert unit.holding[103] == 1125
    assert unit.holding[11] == 15 * 50


async def test_target_in_economy_writes_setpoint_in_use(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """In Economy the setpoint in use is written and the mode kept."""
    unit.input[1001] = 3
    unit.input[1004] = 15 * 50
    await setup_entry(hass, entry)
    await _climate(hass, "set_temperature", temperature=17)
    assert unit.holding[11] == 17 * 50
    assert unit.holding[12] == 30 * 50
    assert unit.holding[103] == 21 * 50
    assert unit.holding[101] == 1


async def test_target_in_economy_uses_cooling_setpoint(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """Cooling only writes the cooling setpoint."""
    unit.holding[1] = 1
    unit.input[1001] = 3
    unit.input[1004] = 30 * 50
    await setup_entry(hass, entry)
    await _climate(hass, "set_temperature", temperature=28)
    assert unit.holding[12] == 28 * 50


async def test_target_in_economy_unknown_is_rejected(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """If the setpoint in use cannot be told, nothing is written."""
    unit.input[1001] = 3
    unit.input[1004] = 20 * 50
    await setup_entry(hass, entry)
    with pytest.raises(ServiceValidationError):
        await _climate(hass, "set_temperature", temperature=17)
    assert unit.holding[11] == 15 * 50


async def test_target_in_economy_cannot_cross(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """The Economy heating setpoint stays below the cooling one."""
    unit.input[1001] = 3
    unit.input[1004] = 15 * 50
    await setup_entry(hass, entry)
    with pytest.raises(ServiceValidationError):
        await _climate(hass, "set_temperature", temperature=31)


async def test_target_in_protection_is_rejected(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """Protection has no target to set from the climate entity."""
    unit.input[1001] = 4
    await setup_entry(hass, entry)
    with pytest.raises(ServiceValidationError):
        await _climate(hass, "set_temperature", temperature=20)


async def test_off_marker_is_no_target(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """The OFF marker in 1004 does not show as a temperature."""
    unit.input[1004] = 4 * 50
    await setup_entry(hass, entry)
    assert hass.states.get(CLIMATE).attributes["temperature"] is None


async def test_fan_modes(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """Fan modes write 102 and read back manual operation."""
    await setup_entry(hass, entry)
    await _climate(hass, "set_fan_mode", fan_mode="medium")
    assert unit.holding[102] == 66
    unit.input[1010] = 1
    await entry.runtime_data.fast.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(CLIMATE).attributes["fan_mode"] == "medium"


async def test_no_fan_feature_when_disabled(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """P52 = 0 removes the fan from the climate entity and the sensors."""
    unit.holding[52] = 0
    await setup_entry(hass, entry)
    assert "fan_modes" not in hass.states.get(CLIMATE).attributes
    assert hass.states.get("sensor.rdf302_fan_output") is None


async def test_one_speed_fan(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """A 1-speed fan offers auto and low."""
    unit.holding[53] = 1
    await setup_entry(hass, entry)
    assert hass.states.get(CLIMATE).attributes["fan_modes"] == ["auto", "low"]


async def test_write_failure_is_reported(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """A failed write reaches the user."""
    await setup_entry(hass, entry)
    unit.fail_write(103, ModbusTimeoutError())
    with pytest.raises(HomeAssistantError):
        await _climate(hass, "set_temperature", temperature=20)


async def test_factory_inputs(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """At factory settings X1 is a contact and X2 an external sensor."""
    await setup_entry(hass, entry)
    assert hass.states.get("binary_sensor.rdf302_x1_operating_mode_contact").state == STATE_OFF
    assert hass.states.get("sensor.rdf302_x2_external_room_temperature") is not None
    # X1 is the mode contact, so the bus must not drive the same function.
    assert hass.states.get("switch.rdf302_window_open") is None


async def test_window_switch_without_contact(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """The window switch appears when no input is the mode contact."""
    unit.holding[38] = 1
    await setup_entry(hass, entry)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.rdf302_window_open"}, blocking=True
    )
    assert unit.holding[105] == 1
    assert hass.states.get("switch.rdf302_window_open").state == STATE_ON


async def test_floor_sensor(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """P51 turns the external sensor into a floor sensor."""
    unit.holding[51] = 28 * 50
    await setup_entry(hass, entry)
    assert hass.states.get("sensor.rdf302_x2_floor_temperature") is not None


async def test_rdf302b_has_no_input_entities(
    hass: HomeAssistant, unit: MockModbusUnit
) -> None:
    """The .B variant has no input entities, whatever the register says."""
    b_entry = MockConfigEntry(
        domain="siemens_rdf302",
        title="RDF302",
        unique_id="b",
        data={
            "host": "192.0.2.1",
            "port": 502,
            "unit_id": 1,
            "model": "rdf302_b",
        },
    )
    await setup_entry(hass, b_entry)
    assert hass.states.get("binary_sensor.rdf302_x1_operating_mode_contact") is None
    assert hass.states.get("switch.rdf302_window_open") is not None


async def test_heater_entities_only_with_heater(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """Heater entities depend on the application."""
    await setup_entry(hass, entry)
    assert hass.states.get("switch.rdf302_electric_heater_enable") is None
    assert hass.states.get("sensor.rdf302_electric_heater_output") is None


async def test_fault_entities(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """A dirty filter shows on the fault sensor and the problem sensor."""
    from .conftest import text_registers

    unit.input[1100] = text_registers("Filter dirty")
    await setup_entry(hass, entry)
    fault = hass.states.get("sensor.rdf302_active_fault")
    assert fault.state == "dirty_filter"
    assert fault.attributes["text"] == "Filter dirty"
    assert hass.states.get("binary_sensor.rdf302_problem").state == STATE_ON


async def test_economy_number_is_limited_by_partner(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """A setpoint cannot pass its partner; OFF stays reachable."""
    await setup_entry(hass, entry)
    number = "number.rdf302_economy_heating_setpoint_4_5_off"
    state = hass.states.get(number)
    assert state.attributes["max"] == 30
    assert state.attributes["min"] == 4.5
    await hass.services.async_call(
        "number", "set_value", {"entity_id": number, "value": 4.5}, blocking=True
    )
    assert unit.holding[11] == 225


async def test_key_lock(
    hass: HomeAssistant, entry: MockConfigEntry, unit: MockModbusUnit
) -> None:
    """The key lock maps options to register values."""
    await setup_entry(hass, entry)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.rdf302_key_lock", "option": "all"},
        blocking=True,
    )
    assert unit.holding[108] == 4


async def test_expert_entities_disabled_and_dangerous_absent(
    hass: HomeAssistant, entry: MockConfigEntry, entity_registry: er.EntityRegistry
) -> None:
    """Expert parameters start disabled; no entity can write the risky registers."""
    await setup_entry(hass, entry)
    entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    by_key = {e.unique_id.removeprefix(f"{entry.entry_id}_"): e for e in entries}
    assert by_key["dead_zone"].disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert by_key["economy_heating_setpoint"].disabled_by is None
    assert by_key["modbus_address"].domain == "sensor"
    assert by_key["baud_rate"].domain == "sensor"
    assert by_key["parity"].domain == "sensor"
    assert by_key["application"].domain == "sensor"
    assert not {"factory_reset", "plant_type"} & set(by_key)
