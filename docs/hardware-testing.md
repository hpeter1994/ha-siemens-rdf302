# Hardware test results

Tested remotely on 2026-11-01, on one RDF302 in a 2-pipe application at Modbus address 2, through an Elfin EW11 with Protocol = Modbus on port 502. Tests ran through the real integration and Home Assistant's `modbus` integration. All settings were restored and compared with a starting snapshot after each phase.

Nobody was at the thermostat, so only Modbus readback was checked. Nothing here confirms what the display showed or how the buttons behaved.

## Findings that differ from the manual

- **Addresses:** every register is one lower on the wire than the manual lists.
- **`P01`:** setting manual changeover forces Protection mode. The manual only says this about `P02`.
- **`P01` and heat/cool:** heating only sets register 107 to heating, and cooling only sets it back to cooling.

## Confirmed

| Area | Result |
|---|---|
| Setup form | Creates a working entry, with the application read from the device |
| Read blocks | All accepted; text must be read as whole blocks |
| Fault text | Big-endian ASCII padded with spaces; "No fault" when clear |
| Comfort, Eco, Protection | Commands work, and 1001 follows |
| Eco target | Writes `P12` when cooling and `P11` when heating, staying in Eco; 1004 follows the active one |
| Target in Protection | Rejected by the integration |
| Turning back on | Returns to the previous preset and keeps the heat/cool direction |
| Heat/cool changeover (107) | Works with `P01` = 3 and reads back; heating output reached 100 % within 4 s |
| Window state (105) | Forces Economy in 1001 while 101 is unchanged |
| Fan | Low, medium, high and auto work; 1002 and 1010 follow |
| Fan disabled, 1-speed | Climate fan modes follow `P52` and `P53` |
| `P05` | Signed 16-bit; -0.5 K reads 65511 and shifted the room reading immediately |
| `P04` = °F | Register values don't change |
| `P02` | Writing 1 forced Protection. Writing 2 was done while already in Protection, so that direction is unconfirmed. Comfort can be commanded straight after |
| `P08` | Writing also resets the Comfort setpoint (103) to the new value |
| Clock (600–603) | Write accepted and read back exactly; zeros are accepted too |
| Input functions (`P38`, `P40`) | All functions on both inputs, in the correct bytes, with a reload each time |
| Changeover on an unwired input | Reads 100 °C (open), selects heating and starts the heating output |
| Other parameters | `P06`, `P07`, `P09`, `P10`, `P14` (manual only), `P30`, `P31`, `P33`, `P39`, `P41`, `P48`, `P49`, `P51`, `P52`, `P53`, `P55`–`P62`, `P65`, `P66`, `P69` |
| Fault texts 1–4 | Written and restored |
| Key lock (108) | All levels write, read back and release over Modbus |
| Outside temperature (104) | Written and read back |

## Running Home Assistant instance

Also tested on a real Home Assistant 2026.10.4 instance, through its service calls:

- The setup form, reload and restart work, and entity IDs stay the same.
- All 56 entities can be enabled and report values.
- Presets, targets, fan modes and heat/cool work.
- Testing here found that `climate.turn_on` switched a cooling thermostat to heating. This is fixed, and turning on now keeps the direction.

## Connection drops

The connection closed briefly about three times during roughly 20 minutes of test traffic, reported as "connection is closed". The cause wasn't identified. The integration now retries a failed poll once when this happens. That retry has only been tested in simulation.

## Not tested

**Needs someone at the thermostat:**

- Whether Modbus mode commands block the wall's mode button, and whether key lock actually blocks the buttons
- Whether 102 follows the wall's fan button
- What the display shows for time, outside temperature and °F. The clock register doesn't advance when read back, so this is also the only way to see whether the clock runs
- What survives a power cycle, and whether writing 103 reaches EEPROM

**Needs wiring or a different setup:**

- X1 and X2 with real signals, including whether digital states reflect `P39` and `P41`
- Parameters whose entities don't exist in this application: `P13`, `P34`, `P35`, `P36`, `P37`, `P44`, `P46`, `P50`, `P54`, register 106
- `P14` auto lock, left out because it can engage by itself
- 4-pipe, 3-position and electric heater applications, the application prompt for units reading NONE, and the RDF302/VB and RDF302.B

**Not run:**

- Polling for several hours
- Address, baud rate, parity, factory reset and application type, which the integration never writes
