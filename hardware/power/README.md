# 48 V power and BMS control package

This package defines the engineering baseline for issue 20. It is a design and
verification plan, not evidence that a battery pack is certified or safe to ship.
The system uses a nominal 48 V removable pack feeding a service disconnect,
branch protection, precharge/contactors, the traction bus, and isolated auxiliary
conversion. Pack limits must come from the selected cell and pack supplier.

## Topology

```text
48 V pack -> service fuse -> manual disconnect -> precharge/main contactors
          -> protected traction bus -> motor drives
          -> isolated 48-to-12 V converter -> compute, sensors, 3.3/5 V rails
BMS AFE -> cell taps + pack current + temperature -> safety MCU -> contactor drive
E-stop/safety chain ---------------------------------------> contactor inhibit
```

The service fuse is the last-resort energy interrupter and is not a control
device. The BMS owns charge/discharge limits and contactor permission. The robot
controller may request power but cannot override a BMS or safety-chain inhibit.
Precharge must reach the supplier-approved bus ratio before the main contactor
closes. Weld detection compares commanded state, auxiliary contact, and bus decay.

## Three protection levels

| Level | Mechanism | Typical triggers | Required response |
|---|---|---|---|
| L1 software | derate/request inhibit | warning temperature, low SOC, transient current | reduce limit, log, remain observable |
| L2 BMS hardware | contactor open | cell OV/UV, sustained OC, OT/UT, isolation fault | remove charge/discharge permission, latch fault |
| L3 independent | fuse/manual disconnect/E-stop chain | short circuit, welded path, responder action | interrupt energy without application software |

All thresholds are controlled configuration tied to pack revision. Missing,
stale, implausible, or contradictory measurements cause a transition to a
non-energized state. Automatic restart after a latched protection event is
forbidden. Reset requires removal of the trigger and an explicit local action.

## BMS states

| State | Entry | Allowed outputs | Exit criteria |
|---|---|---|---|
| OFF | pack absent or service disconnect open | contactors open | valid pack and wake request |
| SELF_TEST | wake accepted | contactors open, sensing on | configuration and sensors valid |
| STANDBY | self-test passed | contactors open | authorized charge or run request |
| PRECHARGE | run request and safety chain healthy | precharge contactor only | bus ratio and timeout pass |
| RUN | precharge passed | main contactor, bounded current | stop request or any trip |
| CHARGE | approved charger and temperature window | charge contactor, bounded current | full, unplug, or any trip |
| DERATE | warning threshold crossed | reduced current limit | hysteresis recovery or trip |
| FAULT_LATCHED | protection or invalid state | all contactors open | service diagnosis and local reset |
| SERVICE | authenticated maintenance mode | contactors open by default | exit service and repeat self-test |

## Verification gates

- Confirm pack voltage range, cell chemistry, fuse interrupt rating, contactor DC
  rating, precharge energy, creepage, connector touch safety, and service access.
- Inject every sensor open/short/stuck fault and confirm de-energized behavior.
- Measure precharge time, inrush, contactor opening time, bus discharge time,
  overcurrent response, temperature response, and welded-contactor detection.
- Record pack serial, revision, BMS configuration hash, operator, date,
  calibrated instruments, ambient conditions, and raw waveform references.
- Require supplier UN 38.3 test summary and applicable transport documentation
  before ordering production battery packs or arranging shipment.

Status: `DESIGN_BASELINE_ONLY`. Pack supplier data, hazard analysis, physical
fault injection, thermal testing, and certification evidence remain release blockers.
