# Hardware test standard

## General rules

- Every result identifies unit serial, firmware/config revision, instrument ID,
  calibration due date, operator, UTC start/end time, and raw evidence path.
- A safety or power-limit failure is an automatic lot hold. Do not average away
  a failed unit.
- A result is `PASS` only when the measured value and acceptance limit are both
  recorded. `NOT_EXECUTED` and `UNKNOWN` never count as pass.

## Release gates

| Gate | Scope | Minimum evidence |
|---|---|---|
| QG-01 | incoming identity and visual inspection | receiving record + photos |
| QG-02 | PCB solder, polarity, connector keying | AOI/X-ray/inspection record |
| QG-03 | rails, ripple, current limit, power-up sequence | scope captures + meter log |
| QG-04 | CAN isolation and communication | isolation test + CAN trace |
| QG-05 | emergency stop and safe enable | timed trip record on both channels |
| QG-06 | harness continuity and pull test | continuity file + pull-test result |
| QG-07 | actuator/sensor functional test | serialized functional log |
| QG-08 | thermal and vibration screening | chamber/shaker report |
| QG-09 | packaging and transport inspection | transport test report |
| QG-10 | final configuration and traceability | signed traveller |

The existing manufacturing `QG-01` through `QG-14` traveller remains the
execution record; this document defines the quality acceptance semantics around
it.
