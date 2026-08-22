# Hardware wiring

This is the EVT wiring view for baseline `WB1-HW-ICD-REV-A`. The controlled
pin-level source is `hardware/pcb/connector-pinout.csv`; unresolved rows in that
file must be approved before a harness or populated PCB is ordered.

```text
36-60 V bench supply / battery
        |
       J1  (keyed input, two positive + two return contacts)
        |
   F1 -> U1 hot-swap/protection -> U2 isolated 12 V
                                      |-- J2 motor auxiliary 12 V
                                      |-- U3 -> J3 Jetson dev-kit 12 V
                                      `-- U4 -> 3V3_LOGIC

Jetson dev kit <-- J4 3.3 V control backplane --> U5 MCU
                                                   |
                         U7 isolated supply -> U6 CAN FD -> J5/J6

Dual-channel E-stop -> J10 -> K1/K2 safety chain -> J11 MOTOR_ENABLE_SAFE
                                      ^
                       MOTOR_ENABLE_REQ from U5 is a request only
```

## Connector map

| Connector | Pins | Connection | Mandatory check before power |
|---|---:|---|---|
| J1 | 1-2 `VBAT_RAW`; 3-4 `GND_PWR` | 36-60 V input, 10 A fused envelope | keying, polarity, wire gauge, fuse interrupt rating |
| J2 | 1-2 `12V_ISO`; 3-4 `GND` | motor auxiliary, 120 W aggregate / 10 A controlled envelope; 16 A is contact capability only | driver inrush/regeneration approval and external branch fuse |
| J3 | 1-2 `JETSON_12V`; 3-4 `GND` | Jetson developer-kit DC input | purchased dev-kit revision and polarity |
| J4 | 1/3 `3V3`; 2/4 GND; 5-20 control; pin 8 `JETSON_ENABLE_REQ` | Jetson-to-MCU SPI/I2C/UART, Jetson enable, six CS, reset and safety status | pin mux and direction against the detailed schematic |
| J5/J6 | 1 `CANH`; 2 `CANL`; 3 `GND_CAN_ISO`; 4 NC | isolated CAN-FD daisy chain | termination, shield policy, no logic-ground short |
| J10 | A out/return, B out/return | dual-channel E-stop loop | channels independent; discrepancy must disable |
| J11 | safe enable, E-stop sense, GND, 3V3 | motor-driver safety interface | safe enable is not tied to software request |

Do not connect J5/J6 pin 3 to logic ground. Do not bridge
`MOTOR_ENABLE_REQ` to `MOTOR_ENABLE_SAFE`; `JETSON_ENABLE_REQ` is a separate
compute-power request. J7-J9 are downstream interface
definitions and are not populated on this board revision.

## Bench connection order

1. Keep the supply off and current limit at 0.25 A. Leave J2/J3 disconnected.
2. Verify J1 polarity, more than 10 kOhm VBAT-to-ground resistance, chassis
   bonding, E-stop channel independence, and connector keying.
3. Connect scope/DMM probes to TP1-TP5 before applying 36 V.
4. Power J1, prove the protected and isolated rails, then remove power.
5. Connect the Jetson at J3; connect motor auxiliary loads at J2 only after the
   unloaded and Jetson stages pass.
6. Connect J5/J6 with exactly two 120 Ohm terminations at the bus ends.
7. Enable J11 only after the J10 truth-table test proves both channels and the
   discrepancy case.

Acceptance values and required captures are controlled by
`hardware/pcb/fabrication/bringup-test-plan.csv` and
`hardware/pcb/testpoint-coverage.csv`.
