# Six-station production line

Issue 23 maps the existing fourteen routing operations into a six-station pilot
cell. The design target is first-pass yield (FPY) at or above 85% and total fixture
capital at or below USD 4,000. Neither target is a claim about unbuilt units.

| Station | Scope | Quality exit | Fixture allocation (USD) |
|---|---|---|---:|
| S1 receiving and kitting | lot ID, incoming inspection, serialized kit | QG-01/02 complete | 300 |
| S2 PCBA build and inspection | print, place, reflow, AOI/manual | QG-03/05 complete | 650 |
| S3 electrical and harness | rail/isolation test, harness continuity | QG-06/09 complete | 1,200 |
| S4 mechanical assembly | chassis, arms, battery, controller, covers | QG-07/10 complete | 650 |
| S5 safety and functional | E-stop, interlocks, interfaces, soak | QG-11/12 complete | 900 |
| S6 final inspection and pack | traveller, labels, cosmetics, pack | QG-13/14 complete | 300 |
| **Total** | | | **4,000** |

Fixture allocation is a planning cap excluding already-owned calibrated lab
equipment. Purchase requests need quotations and calibration/service costs.
Fixtures fail closed on unknown product revision, missing calibration, failed
self-test, duplicate serial, or unavailable evidence storage. Safety fixtures
use guarded energy, current limiting, emergency disconnect, and documented LOTO.

## Flow and takt

Material flows S1 to S6 with physically separate quarantine/MRB. No failed unit
moves forward on the normal route. The line balance uses observed station cycle
times from serialized travellers; planning times are not silently substituted.
The bottleneck, staffing, changeover, availability, and rework loop determine
capacity. Work instructions display revision at point of use and expired copies
are removed at shift start.

## FPY gate

FPY is `units passing every required gate without repair or repeat / units entering
the route * 100`. Re-test after operator error, fixture error, component replacement,
or adjustment counts as not first-pass. Report numerator, denominator, defect code,
station, shift, product revision, and confidence limits. Pilot release requires
FPY >= 85% and zero escaped critical safety defects. Yield exclusions require
Quality approval and remain visible in the raw data.

If FPY is below 85%, stop ramp, contain affected lots, Pareto defects, assign
corrective actions, verify the top causes, and repeat a controlled pilot. Averages
cannot hide a station, supplier lot, or shift below threshold. Final release also
requires fixture GR&R/measurement-system evidence where the result is quantitative.

## Workstation release

- S1: barcode/lot traceability, ESD control, and quarantine are operational.
- S2: process profile, stencil, inspection program, and workmanship criteria match revision.
- S3: guarded power, continuity, isolation, and raw data capture pass golden-unit checks.
- S4: calibrated torque tools, datum fixture, lift aids, and ergonomic review are complete.
- S5: restrained motion zone, safety test authority, and emergency response are approved.
- S6: label templates, pack drawing, accessories, traveller audit, and release authority match.

Status: `PILOT_EXECUTION_REQUIRED`. Release needs 20 serialized travellers,
measured FPY, defect closure, fixture acceptance, training records, and owner sign-off.
