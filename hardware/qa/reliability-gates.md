# Quality and early-life reliability gates

Issue 24 supplements the existing test standard, inspection plan, and FMEA.
Physical results remain `NOT_EXECUTED` until linked to serialized units and raw data.

## Test specification

Every production unit receives identity/configuration audit, visual/workmanship
inspection, protective-bond and isolation checks as applicable, current-limited
power-up, rail checks, BMS/safety-chain test, E-stop fault injection, interface
exercise, dual-arm interlock test, thermal soak, final inspection, and traveller
closure. Acceptance limits come from controlled drawings and component ratings.
Test equipment ID, calibration expiry, software version, operator, timestamp,
ambient conditions, result, defect code, and raw evidence path are mandatory.

Sampling may reduce non-critical incoming or cosmetic checks only under the AQL
plan. Safety, identity, configuration, and protective-function checks are 100%.
Missing or corrupt evidence is a failure, not an assumed pass. Reworked units repeat
the affected gate and all downstream gates whose validity could have changed.

## FMEA action rule

RPN is severity times occurrence times detection. Any RPN above 100 requires a
named action, owner, due date, containment, and verification before release.
Severity 9 or 10 cannot be accepted solely because occurrence is estimated low;
the Safety/Quality owners must review the control independently. After action,
record revised factors with evidence rather than overwriting the original score.

The current FMEA intentionally contains open rows above 100. These are action
signals and release blockers, not proof that mitigations have been completed.
New pilot and field defects feed back into occurrence and detection ratings.

## Early failure rate

The early window is the first 30 calendar days or 100 operating hours after site
acceptance, whichever occurs first. Rate is `unique units with a confirmed product
failure / deployed units that completed the observation window * 100`. Report
right-censored units separately. Operator training, shipping damage, no-fault-found,
and supplier defects remain classified and visible; exclusions need Quality approval.

Release target is early failure rate <= 5%. Exceeding 5%, any serious safety event,
or two matching critical failures triggers stop-ship, containment, field notification,
root-cause analysis, corrective action, and effectiveness verification. A small
sample must include the count and confidence interval; zero observed failures is
not represented as zero risk.

## Evidence and review

- Link failures to serial, hardware revision, software/configuration hash, site, and hours.
- Preserve original logs, photos, measurements, replaced parts, and return-material chain.
- Use a controlled defect taxonomy and distinguish symptom, root cause, and correction.
- Review FPY, escapes, rework, returns, early failures, and open FMEA actions weekly in pilot.
- Close release only when high-RPN actions and critical corrective actions are verified.

Status: `EXECUTION_REQUIRED`. The specification is ready; pilot, reliability,
FMEA-action, and early-life evidence must be collected on real units.

`fmea-action-register.csv` keeps high-RPN actions visible, while
`early-failure-log.csv` is a deliberately empty execution template rather than
a fabricated reliability result.
