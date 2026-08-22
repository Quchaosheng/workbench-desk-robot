# Traction childboard candidate schematic contract

**Status: ARCHITECTURE-ONLY / DO_NOT_ORDER**

This document is the controlled bridge from the functional architecture to a
future component-level KiCad schematic. It is deliberately a wiring contract,
not evidence that an orderable schematic exists. `net-topology.csv` and
`safety-gate-connectivity.csv` are the machine-readable sources of truth for
the candidate connections. Every MPN, package, land pattern, rating and value
remains pending in `bom.csv` and `component-approval-register.csv`.

## Power and return topology

1. `J_PWR.1/.2` receive the controller J2 12 V auxiliary pair. Both conductors
   enter `F1` before any protected copper expands. `Q1` is a candidate
   reverse-polarity/reverse-current blocker; its output is `VM_PROTECTED`.
2. `VM_PROTECTED` feeds the four `U1` VM pins, the local bulk bank, the
   candidate clamp/brake network and the candidate `U6` logic regulator. The
   source must never be used as a regenerative sink until the energy review
   closes `MTR-REGEN`.
3. `J_PWR.3/.4` are the high-current `GND_MOTOR` return. `PGND1..4`, motor
   commutation capacitors and the bulk-bank negative return to one low-
   impedance `STAR_GND_01` near the power entry. No motor-current return may
   use a logic or CAN-isolated trace.
4. `U6` is a functional candidate for the local regulated `VCC_LOGIC` rail.
   `U1.VCC`, the local MCU, both safety gates and the primary side of the CAN
   interface return to `GND_LOGIC`. `GND_LOGIC` joins `GND_MOTOR` exactly once
   at `STAR_GND_01`; an open star must remove logic permission rather than
   create a floating enable.
5. `U1.DVDD` is decoupled by `C3` as `DVDD_5V` and has no external load until
   the approved driver datasheet review confirms its voltage, current and
   startup behavior. Encoder supplies use a separately current-limited
   `VCC_LOGIC` branch; their voltage and short-circuit behavior remain
   candidate-only.
6. `U7` is a functional candidate for isolated CAN-side power. Its secondary
   `VCC_CAN_ISO/GND_CAN_ISO` island feeds only the isolated side of `U3`, CAN
   protection and `J_CAN.3`. There is no DC, shield, capacitor or test-point
   connection to `GND_MOTOR` or `GND_LOGIC` without an approved EMC/isolation
   design.

## Safety and fault topology

* `J_SAFE` is an **ECO endpoint** from the J10/K1/K2 dual-channel safety chain,
  not a claim that the current controller J11 is compatible.
  `SAFE_ENABLE_A/SAFE_RETURN_A` enter independent candidate gate
  `U4`; its only bridge-permission output is `NSLEEP_SAFE_A` to `U1.25`.
* `SAFE_ENABLE_B/SAFE_RETURN_B` enter independent candidate gate `U5`; its
  outputs separately gate all four `U1.ENx` pins (`U1.30..33`). There is no
  shared permissive net, MCU GPIO, CAN command or reset shortcut between the
  channels.
* `U1.nFAULT` (`U1.41`) is an open-drain diagnostic **and** a hardware inhibit
  source. It has two separately biased/guarded fan-outs: one into `U4` and one
  into `U5`. A low fault, missing driver supply, missing gate supply, broken
  return or undefined fan-out defaults both gate outputs low and latches until
  the upstream manual-reset sequence is complete. The MCU may observe the
  fault, but it cannot clear or recreate either safety permission.
  A pull-up-only diagnostic wire is insufficient: the selected interface must
  detect an open or shorted `nFAULT` conductor and map either condition to the
  same inhibit state (`open_or_short_inhibits` in the path table).
* `POWER_GOOD_LOCAL` is checked independently by both candidate safety gates;
  brownout therefore cannot leave a stale high `nSLEEP` or `ENx` condition.
  The exact gate silicon, pull-up/pull-down values, timing, diagnostic
  coverage and reset circuitry are release blockers, not inferred here.

## Detailed schematic entry criteria

Before `MTR-SCHEMATIC` can close, the owner must replace this candidate contract
with a KiCad component-level schematic that has:

* approved symbols and footprints for `U1`, `U2`, `U3`, `U4/U5`, `U6/U7`, all
  protection, bypass, current-sense and connector parts;
* explicit net labels matching both CSV files, including the single
  `STAR_GND_01` join and the isolated CAN barrier;
* independent A/B `nFAULT` inhibit paths shown through the selected safety
  gates, with default-state calculations and a manual-reset latch;
* power, creepage, return-current, thermal-pad and regenerative clamp notes;
* ERC/DRC/netlist evidence generated from the same revision.

Until those artifacts and external approvals exist, this package remains
`ORDER_RELEASE_BLOCKED`; passing the deterministic validator only proves that
the candidate contract is internally consistent.
