# Register reference

An independent summary of the RDF302's Modbus registers, based on *RDF302 Basic documentation* (CE1P3079en, edition 1.6, section 3.12) and on measurements from a real RDF302.

## Addressing

**On the wire, every register is one lower than the manual's address.** The manual's register 1001 is requested as 1000, for example. This was measured on hardware, where address 80 returned the device's own address (`P81`).

The tables use the manual's addresses. The code does too, and subtracts one only where it talks to the device.

## Encoding

| Type | Encoding |
|---|---|
| Temperature | Raw value = °C × 50, so 21 °C = 1050 |
| No value | `0xFFFF` means out of service |
| Text | ASCII, big-endian, 2 characters per register, padded with spaces |
| `P46` | Raw value = A × 10 |

**Function codes:** 0x03 reads holding registers, 0x04 reads input registers, 0x06 writes one register and 0x10 writes several.

Don't read across gaps between registers, because the device refuses the whole request. Text and clock blocks must be read as a whole.

## Input registers (read only)

| Address | Object | Values |
|---|---|---|
| 1001 | Operating mode, effective | 1 Comfort, 3 Economy, 4 Protection |
| 1002 | Fan output | 0 off, 33 low, 66 medium, 100 high |
| 1003 | Room temperature | °C × 50 |
| 1004 | Effective setpoint | °C × 50; OFF markers below 5 °C or above 40 °C |
| 1005 | Heating output | 0–100 % |
| 1006 | Cooling output | 0–100 % |
| 1007 | Electric heater output | 0–100 % |
| 1008, 1009 | X1, X2 temperature | °C × 50 |
| 1010 | Fan operation | 0 auto, 1 manual |
| 1011, 1012 | X1, X2 digital | 0 off, 1 on |
| 1100–1109 | Fault text | Up to 20 characters |

## Runtime holding registers

| Address | Object | Values |
|---|---|---|
| 101 | Operating mode command | 1 Comfort, 3 Economy, 4 Protection |
| 102 | Fan command | 0 auto, 33 low, 66 medium, 100 high |
| 103 | Comfort setpoint | 5–40 °C |
| 104 | Outside temperature | 0–49 °C |
| 105 | Window state | 0 closed, 1 open (forces Economy) |
| 106 | Enable electric heater | 0 disabled, 1 enabled |
| 107 | Heating/cooling changeover | 0 cooling, 1 heating |
| 108 | Button lock | 0 unlocked, 1 plus and minus, 2 fan, 3 mode, 4 all |
| 109 | Plant type | 0 none, 1 2-pipe, 2 2-pipe 3-position, 3 2-pipe with heater, 4 4-pipe. **Writing reloads factory settings** |
| 200, 300, 400, 500 | Fault texts 1–4, 10 registers each | Condensation, input 1, input 2, dirty filter |
| 600–603 | System time | KNX DPT 19.001, 8 bytes |

## Parameters (holding registers)

The address equals the parameter number, except for the ones noted.

| Address | Parameter | Range | Factory |
|---|---|---|---|
| 1 | `P01` Control sequence | 0 heating, 1 cooling, 2 manual changeover, 3 auto changeover, 4 heating and cooling | 2-pipe: 1; 4-pipe: 4 |
| 2 | `P02` Mode button profile. **Writing forces Protection** | 1 Comfort-Protection, 2 Comfort-Economy-Protection | 1 |
| 4 | `P04` Display unit | 0 °C, 1 °F | 0 |
| 5 | `P05` Sensor calibration | -3…3 K | 0 |
| 6 | `P06` Standard display | 0 room, 1 setpoint, 2 bus temperature | 0 |
| 7 | `P07` Additional display | 0 none, 1 °C and °F, 2 outside, 3 time 12 h, 4 time 24 h | 0 |
| 8 | `P08` Comfort basic setpoint | 5–40 °C | 21 °C |
| 9, 10 | `P09`, `P10` Comfort limits | 5–40 °C | 5 °C, 35 °C |
| 11 | `P11` Economy heating | 4.5 = OFF, 5 °C up to `P12` | 15 °C |
| 12 | `P12` Economy cooling | `P11` up to 40 °C, 40.5 = OFF | 30 °C |
| 13 | `P13` Heater in cooling mode | 0, 1 | 1 |
| 14 | `P14` Local key lock | 0 off, 1 auto, 2 manual | 0 |
| 30, 31 | `P30`, `P31` Differential heating, cooling | 0.5–6 K | 2 K, 1 K |
| 33 | `P33` Dead zone | 0.5–5 K | 2 K |
| 34 | `P34` Setpoint differential | 0.5–5 K | 2 K |
| 35 | `P35` Integral time | 0–10 min | 5 min |
| 36, 37 | `P36`, `P37` Changeover points | 10–25 °C, 27–40 °C | 16 °C, 28 °C |
| 38 | `P38` (high byte), `P40` (low byte) Input functions | See below | X1 = 3, X2 = 1 |
| **40** | `P39` X1 action | 0 normally open, 1 normally closed | 0 |
| 41 | `P41` X2 action | 0 normally open, 1 normally closed | 0 |
| 44 | `P44` Actuator run time | 20–300 s | 150 s |
| **182** | `P46` Heater load current | 0–5 A | 0 |
| 48, 49 | `P48`, `P49` Minimum on, off time | 1–20 min | 1 min |
| 50 | `P50` Purge time | 0 off, 1–5 min | 0 |
| 51 | `P51` Floor temperature limit | 9 = OFF, 10–50 °C | OFF |
| 52 | `P52` Fan control | 0 disabled, 1 enabled, 2 heating only, 3 cooling only | 1 |
| 53 | `P53` Fan speeds | 1, 2 (3-speed) | 2 |
| 54 | `P54` Fan overrun | 0–360 s | 60 s |
| 55–57 | `P55`–`P57` Fan switching points | 80–100, 30–75, 1–15 % | 100, 65, 10 % |
| 58 | `P58` Fan start kick | 0, 1 | 1 |
| 59 | `P59` Fan minimum on time | 1–6 min | 2 min |
| 60 | `P60` Fan kick in Comfort | 0–89 min, 90 = OFF | 0 |
| 61 | `P61` Fan kick in Economy | 0–359 min, 360 = OFF | OFF |
| 62 | `P62` Filter service interval | 0 off, 100–9900 h | 0 |
| 65 | `P65` Protection heating | 4.5 = OFF, 5 °C up to `P66` | 8 °C |
| 66 | `P66` Protection cooling | `P65` up to 40 °C, 40.5 = OFF | OFF |
| 68 | `P68` Baud rate | 0 4800, 1 9600, 2 19200, 3 38400 | 2 |
| 69 | `P69` Temporary Comfort setpoint | 0, 1 | 0 |
| 70 | `P70` Parity | 0 odd, 1 even, 2 none | 1 |
| 71 | `P71` Restore factory settings | 0, 1 | 0 |
| 81 | `P81` Device address | 1–247 | 1 |

Address, baud rate and parity changes take effect after a power cycle.

## Input functions

| Value | Function |
|---|---|
| 0 | Not used |
| 1 | External room, return air or floor temperature sensor |
| 2 | Heating/cooling changeover sensor or switch |
| 3 | Operating mode contact |
| 4 | Dew point sensor |
| 5 | Enable electric heater |
| 6 | Fault input |
| 7 | Digital monitor |
| 8 | Temperature monitor |

Functions 1–5 may only be used on one input at a time.

## Undocumented addresses

A read-only scan on 2026-11-04 tried every address from 0 to 4999, and every 100th address up to 65500, with function codes 1 to 4 on one RDF302. Block-only areas were probed at every tenth address with 2, 4, 8 and 10 registers.

| Area | Result |
|---|---|
| Coils (1) and discrete inputs (2) | None answer |
| Holding registers (3) | Only the documented ones, plus 32 and 45 |
| Input registers (4) | The documented ones, plus 1013 and 1014 |
| Input registers 10001 and up | A read-only copy of holding register N at 10000 + N, for every holding register that answers singly |
| Blocks | Only the documented ones: fault texts 200–500, clock 600–603, fault 1100–1109 |

Values found, and what writing to them showed. Both holding registers are independent, stored settings: changing `P44` or the differentials didn't change them, and writing them changed no other register. The thermostat stayed in Protection, so their effect on the outputs wasn't observed.

| Address | Value | Accepted range | Probably |
|---|---|---|---|
| 32 (holding) | 100 | 25–300, the same as `P30` (0.5–6 K) | A hidden switching differential, 2 K |
| 45 (holding) | 150 | 20–300, the same as `P44` (s) | A second actuator run time, 150 s |
| 1013, 1014 (input) | 20 and 20 | Read only | A fixed value such as a version; the same on two thermostats with different serial settings |
