# Design and hardware test notes

The original plan for this integration, kept up to date, with hardware test results in section 6.

Register data comes from *RDF302 Basic documentation*, CE1P3079en, edition 1.6, section 3.12 (p. 41-45).
The datasheet and the operating instructions add no registers.

## 1. Architecture

```
Home Assistant
  siemens_rdf302 (one config entry per thermostat)
    vendored rdf302_modbus library: registers, scaling, no HA imports
    fast coordinator (5 s)  +  slow coordinator (5 min, after any write, and when a fast poll sees a change)
        |  async_get_unit(hass, entry, ModbusTcpParams(host, port), unit_id)
  modbus (HA core): owns the shared connection and queues requests
        |  TCP
  RTU-to-TCP bridge  --RS485 (factory 19200 8E1)--  RDF302 unit 1..247
```

- **Domain:** `siemens_rdf302`, a custom integration installed through HACS.
- **Manifest:** `dependencies: ["modbus"]`. The integration never opens a socket itself.
- **HA version:** the shared-connection API first shipped in **2026.9.0**. 2026.8.0 only has pymodbus and no such API.
  The plan targets a minimum of **2026.10.0**, the release line I checked.
- **Superseded design:** the `modbus_connection` integration from the July 2026 blog post and PR is not in any of the release tags I checked (2026.8.0, 2026.9.0, 2026.10.4). The current API is `homeassistant.components.modbus.async_get_unit`, with `async_get_temporary_unit` for the config flow.
- **Reconnects:** the shared connection reopens on the next request, so the integration does not reload on disconnect. Entities go unavailable and then recover.

### Config flow

- **Fields:** host, port (502), unit ID (1), name, model (default `RDF302`; `RDF302/VB` and `RDF302.B` also offered).
- **Link:** Modbus TCP only; the bridge converts to RTU (EW11 Protocol = Modbus). RTU over TCP was removed on request.
- **Model must be chosen by hand:** no register identifies the model or a serial number.
- **Application fallback:** if 109 reads NONE, the flow asks for the application (2-pipe on/off, 2-pipe 3-position, 2-pipe with electric heater, 4-pipe) and uses it for the entity conditions. DIP-configured units may read NONE here.
- **Unique ID:** `host:port:unit`, because the device has no serial number. A reconfigure step handles address changes.
- **Probe:** read 1001-1012 and check that register 1001 is 1, 3 or 4.
- **Several thermostats on one bridge:** one entry each. They share the connection and their requests queue.

### Polling

The manual's "access group" column defines which registers may be read in one request. Reads never cross a group or a gap.

| Coordinator | Reads |
|---|---|
| Fast, 5 s | 1001-1012; 101-109; 1100-1109 (3 requests) |
| Slow, 5 min, after any write, and when the fast poll sees a change | P01; P02; 4-14; 30-31; 33-37; 38; 40-41; 44; 182; 48-62; 65; 66; 68-71; 81; fault texts 200, 300, 400, 500 (about 18 requests) |

A change means any fast register other than the measurements (room, X1 and X2 temperatures, outputs). Changes at the wall, such as the mode button in manual changeover, can come with parameter changes, so all settings are read again at once instead of after up to 5 minutes.

Every write is followed by an immediate refresh of both coordinators. Nothing is written at startup.

### Encoding

- **Temperatures:** raw = °C x 50 (21 °C = 1050). Setpoints are written in 0.5 °C steps.
- **Addresses:** every register is one below the manual on the wire (measured on hardware). The code uses manual addresses and subtracts one at the I/O layer.
- **0xFFFF** means out of service. X1 and X2 sensors are then unavailable, with a warning in the log.
- **OFF values:** register 1004: 4; P11 and P65: 4.5; P12 and P66: 40.5; P51: 9 (all in °C before scaling); P60: 90; P61: 360.
- **P46** is x10 and lives at address **182**.
- **P38 and P40 share register 38:** X1 in the high byte, X2 in the low byte. Writes are read-modify-write.
- **P39 is at address 40 and P41 at 41.** Address 40 is not P40.

## 2. Climate entity

One `climate` entity covers objects 2, 3, 4, 5, 6, 7, 8, 12, 15, 16, 17 and 21.

| Climate property | Read from | Written to |
|---|---|---|
| Current temperature | 1003 | - |
| Target temperature | 1004 (effective setpoint) | Comfort: 103. Eco: P11 or P12, see below. Protection: rejected |
| Target limits | P09, P10, see below | - |
| HVAC mode | 1001 and P01, plus 107 when P01 = 3 | 101 and 107 |
| Preset | 1001 (effective mode, not 101) | 101 |
| Fan mode | 1010, then 102 | 102 |
| HVAC action | 1005, 1006, 1007, 1002 | - |

**Presets:** `comfort` (1), `eco` (3). Protection (4) is shown as HVAC mode `off`, with no preset.

**HVAC modes depend on P01:**

| P01 | Meaning | Modes offered | Notes |
|---|---|---|---|
| 0 | Heating only | `heat`, `off` | |
| 1 | Cooling only | `cool`, `off` | |
| 2 | Manual changeover | `heat` or `cool` (whichever 107 shows), `off` | Only the wall button can change heating/cooling; 107 follows it and ignores bus writes |
| 3, no local changeover input | Changeover via Modbus | `heat`, `cool`, `off` | Writes 107 (0 = cool, 1 = heat) |
| 3, X1 or X2 = 2 | Changeover via sensor or switch | `auto`, `off` | The input decides |
| 4 | Heating and cooling | `heat_cool`, `off` | One setpoint in the middle of the dead zone (P33) |

- **Turning back on** restores the last preset, or Comfort if none is known.
- **HVAC action:** `heating` if 1005 or 1007 > 0; `cooling` if 1006 > 0; `fan` if only 1002 > 0; otherwise `idle`, or `off` in Protection.
- **Target limits:** if P09 < P10, both directions use P09..P10. Otherwise heating uses 5..P10 and cooling uses P09..40. Step 0.5.
- **Target writes in Economy:** written to the setpoint in use, which stays in Economy. P01 = 0 writes P11 and P01 = 1 writes P12. With changeover (P01 = 2 or 3), the one matching 1004 is written. If neither or both match, the write is rejected with an error pointing to the P11 and P12 numbers. These writes go to EEPROM, so frequent automations should not drive the target in Eco.
- **Target writes in Protection (`off`):** rejected with a clear error. P65 and P66 stay available as number entities.
- **Fan modes:** `auto` (0), `low` (33), `medium` (66), `high` (100). The feature is removed when P52 = 0. With P53 = 1 only `auto` and `low` are offered.

## 3. Other entities

Enabled by default unless marked *off*. "Condition" means the entity is created only in that configuration. Changing a parameter that affects conditions triggers a reload, which deletes entities that are no longer created. Home Assistant keeps their ID and customizations and restores them if they are created again.

### Sensors

| Entity | Reg | Type | Condition |
|---|---|---|---|
| Room temperature | 1003 | °C | |
| Effective setpoint | 1004 | °C | `unknown` when the setpoint in use is OFF, with attribute `setpoint: off` (otherwise `active`) |
| Operating mode | 1001 | enum: comfort, economy, protection | |
| Heating output | 1005 | % | Application has heating |
| Cooling output | 1006 | % | Application has cooling |
| Electric heater output | 1007 | % | 2-pipe with electric heater |
| Fan output | 1002 | enum: off, low, medium, high | P52 != 0 |
| Fan operation | 1010 | enum: auto, manual; diagnostic | P52 != 0 |
| Active fault | 1100-1109 | enum, raw text as attribute | |
| Application | 109 | enum, read-only; diagnostic | |

The Modbus address, baud rate and parity (81, 68, 70) are not entities: they only change at the wall, and a change cuts the link. They are in the device's diagnostics download, with every register as last read and the bridge host redacted.

### Binary sensors

| Entity | Source | Condition |
|---|---|---|
| Problem | Active fault is not "no fault" | |
| Input-dependent entity | see below | RDF302 and RDF302/VB only |

**Why only one fault binary sensor:** the bus reports only the highest-priority fault, so "filter dirty" would falsely read clear during a condensation alarm. Separate sensors per fault would mislead.

**Fault matching:** 1100 returns free text that can be edited through 200-509, and the manual's default strings disagree with each other ("Filter dirty" / "Dirty filter"). The enum is therefore found by comparing 1100 with the texts read from the thermostat.

### X1 and X2 inputs

Each input gets the entity matching its function in P38 or P40. The X1 registers are 1008 and 1011, the X2 registers 1009 and 1012. RDF302.B has none of these.

| Function | Entity | Device class |
|---|---|---|
| 0 Not used | none | |
| 1 External sensor | Sensor, "External room temperature" ("Floor temperature" if P51 is not OFF) | temperature |
| 2 Changeover | Sensor, "Changeover temperature" (0 = closed, 100 = open if a switch is wired; the registers can't tell a switch from a sensor) | temperature |
| 3 Operating mode contact | Binary sensor | opening |
| 4 Dew point | Binary sensor | moisture |
| 5 Heater enable | Binary sensor, on = enabled | none |
| 6 Fault | Binary sensor | problem |
| 7 Digital monitor | Binary sensor | none |
| 8 Temperature monitor | Sensor | temperature |

### Controls

| Entity | Reg | Type | Condition or note |
|---|---|---|---|
| Window open | 105 | switch | Only if neither input is function 3. **Hidden at factory settings on RDF302 and RDF302/VB** because X1 = 3. Forces Economy and blocks local operation |
| Electric heater enable | 106 | switch | 2-pipe with electric heater, and neither input is function 5 |
| Comfort setpoint | 103 | number 5-40 °C | Writable in any mode |
| Outside temperature | 104 | number 0-49 °C | Shown when P07 = 2. **Cannot represent values below 0 °C**, so feed it from an automation and expect it to clamp |

### Setpoints and Comfort settings, enabled

These do not appear on the climate card, so they are enabled controls (no category). They write to EEPROM, so they should not be driven by frequent automations. The heating ones are left out when nothing can heat (P01 = cooling only, no heater) and the cooling ones when P01 = heating only. The Eco ones stay with P02 = Comfort-Protection, because Eco can still be entered over the bus, by the window state or by an input contact (checked on hardware).

| Entity | Reg | Range |
|---|---|---|
| Economy heating setpoint (P11) | 11 | 4.5 = OFF, 5 up to P12 |
| Economy cooling setpoint (P12) | 12 | P11 up to 40, 40.5 = OFF |
| Protection heating setpoint (P65) | 65 | 4.5 = OFF, 5 up to P66 |
| Protection cooling setpoint (P66) | 66 | P65 up to 40, 40.5 = OFF |
| Comfort basic setpoint (P08) | 8 | 5-40 °C. Resets the runtime Comfort setpoint |
| Temporary Comfort setpoint (P69) | 69 | switch |

### Configuration, enabled

| Entity | Reg | Type | Condition or note |
|---|---|---|---|
| Key lock | 108 | select: unlocked, plus/minus, fan, mode, all | Cannot be released at the wall once set over Modbus |
| Sync clock | 600-603 | button | Created when P07 = 3 or 4. Clock also syncs hourly, and after a failed poll recovers, in that case |
| Last clock sync | - | timestamp sensor, diagnostic | With the button. Every successful sync: button, hourly or after reconnect. Kept across restarts |

### Configuration parameters, *off* by default

All are category config. Conditional ones follow section 3.13 of the manual.

| Reg | Parameter | Entity | Range or options | Condition |
|---|---|---|---|---|
| 1 | P01 Control sequence | select | 2-pipe: 0-3; 4-pipe: 2-4 | |
| 2 | P02 Mode button profile | select | Comfort-Protection; Comfort-Eco-Protection | **Writing forces Protection** (see section 5) |
| 4 | P04 Display unit | select | °C, °F | |
| 5 | P05 Sensor calibration | number | -3..3 K | |
| 6 | P06 Standard display | select | room, setpoint, bus temperature | |
| 7 | P07 Additional info | select | none, °C/°F, outside, 12 h, 24 h | |
| 9, 10 | P09, P10 Setpoint limits | number | 5-40 °C | |
| 13 | P13 Heater in cooling mode | switch | | 2-pipe with electric heater |
| 14 | P14 Local key lock | select | off, auto, manual | |
| 30, 31 | P30, P31 Differential heat, cool | number | 0.5-6 K | Each only if the thermostat can heat or cool |
| 33 | P33 Dead zone | number | 0.5-5 K | |
| 34 | P34 Setpoint differential | number | 0.5-5 K | 2-pipe with electric heater |
| 35 | P35 Integral time | number | 0-10 min | 2-pipe 3-position |
| 36, 37 | P36, P37 Changeover points | number | 10-25 °C; 27-40 °C | An input is function 2 |
| 38 | P38, P40 Input functions | 2 selects | 0-8; functions 1-5 may not repeat | RDF302 and RDF302/VB |
| 40, 41 | P39, P41 Input action | 2 selects | NO, NC | Each only if its input is a switch (functions 2-7); not for unused, external sensor or temperature monitor |
| 44 | P44 Actuator run time | number | 20-300 s | 2-pipe 3-position |
| 182 | P46 Heater load current | number | 0-5 A | 2-pipe with electric heater |
| 48, 49 | P48, P49 Min on, off time | number | 1-20 min | |
| 50 | P50 Purge time | number | 0-5 min | An input is function 2 |
| 51 | P51 Floor temperature limit | number | 9 = OFF, 10-50 °C | Only if an input is an external sensor |
| 52 | P52 Fan control | select | disabled, enabled, heating only, cooling only | |
| 53 | P53 Fan speeds | select | 1-speed, 3-speed | Only if P52 enables the fan |
| 54 | P54 Fan overrun | number | 0-360 s | 2-pipe with electric heater, fan enabled |
| 55-57 | P55-P57 Fan switching points | number | 80-100; 30-75; 1-15 % | Only if P52 enables the fan |
| 58 | P58 Fan start kick | switch | | |
| 59 | P59 Fan min on time | number | 1-6 min | Only if P52 enables the fan |
| 60 | P60 Fan kick Comfort | number | 0-89 min, 90 = OFF | Only if P52 enables the fan |
| 61 | P61 Fan kick Economy | number | 0-359 min, 360 = OFF | Only if P52 enables the fan |
| 62 | P62 Filter service interval | number | 0, 100-9900 h, step 100 | |
| 200, 300, 400, 500 | Fault texts 1-4 | text | Up to 20 characters | |

### Deliberately not writable

| Reg | Object | Why |
|---|---|---|
| 109 | Plant type | Reloads factory settings for all control parameters |
| 71 | P71 Factory reset | Wipes configuration, and is easy to trigger by accident |
| 81, 68, 70 | Address, baud rate, parity | Takes effect after a power cycle and can cut the device off the bus. Change at the wall |

## 4. How the entities depend on each other

```
Plant type (109)   -> which outputs, P13, P34, P35, P44, P46, P54 and heater enable exist
P01                -> climate HVAC modes; whether 107 can be written;
                      heating or cooling outputs, Eco/Protection setpoints and differentials
P38, P40 (X1, X2)  -> which input entities exist
                   -> 3 hides Window open; 5 hides Heater enable; 2 shows the direction from 107
                      and exposes P36, P37, P50
                   -> 2-7 expose that input's action (P39, P41); 1 exposes P51
P51 + input 1      -> external sensor becomes floor sensor; room temperature uses built-in sensor
P52                -> fan features, fan sensors and fan settings (P53-P61) exist
P53                -> fan modes offered
P07                -> outside temperature number; clock sync button
P09, P10           -> climate min and max
P11<->P12, P65<->P66 -> each pair limits the other
```

Operating mode priority, highest first: commissioning at the wall, X1/X2 contact, Modbus window state (105), Modbus operating mode (101), mode button. This is why state is read from 1001 and not 101.

## 5. Device behaviour to be aware of

1. **Protection over Modbus disables all wall buttons** until Modbus commands Comfort or Economy. The manual suggests Comfort or Economy commands also block the mode button, but on site the buttons worked normally afterwards. There is no "release to local" value.
2. **`off` is not off.** Protection still holds frost protection (P65, 8 °C by default). If P65 = OFF nothing protects the room.
3. **Writing P02, or setting P01 to manual changeover, forces Protection mode.** Writing P08 also resets the runtime Comfort setpoint (103) to the new value.
4. **No heating/cooling state register exists.** Only the outputs and 107 are available, and the manual does not say whether 107 tracks changes from an input or the wall button.

## 6. Checks on real hardware

The manual is ambiguous on these, so each needs a test before or during implementation.

These were the questions going into hardware testing. See [hardware-testing.md](hardware-testing.md) for the answers.

## 7. Decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Bridge | Elfin EW11 with Protocol = Modbus. Modbus TCP only |
| 2 | Device | RDF302 in a 2-pipe configuration. All applications stay supported |
| 3 | Protection | Is HVAC `off`, with presets only for Comfort and Eco |
| 4 | Target temperature | Editable in Comfort (103) and Eco (P11 or P12), rejected in Protection |
| 5 | Outside temperature | Number entity plus the user's own automation |
| 6 | Clock sync | Automatic when P07 = 3 or 4, plus a button |
| 7 | Expert parameters | Exposed but disabled by default |
