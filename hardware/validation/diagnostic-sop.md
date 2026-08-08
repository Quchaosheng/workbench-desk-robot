# Field hardware diagnostic SOP

## Safety first

1. Stop motion, remove the enable request, and verify both E-stop channels are
   open before probing. Never defeat a guard or safety interlock.
2. Record serial, hardware revision, firmware/config hash, battery voltage,
   ambient temperature, and the exact symptom before changing anything.
3. Use current-limited power for board-level diagnosis. Escalate smoke, heat,
   exposed conductors, repeated over-current, or failed isolation to the Safety
   Owner and quarantine the unit.

## Decision tree

- **No power:** inspect connector keying and fuse, measure input at the board,
  then verify 12 V, 3.3 V and Jetson rails in order. Do not bypass protection.
- **CAN offline:** capture bus activity, check termination and isolated supply,
  then run the controlled loopback. Replace the harness only after pinout and
  continuity are recorded.
- **One joint/sensor missing:** stop, identify the channel, inspect connector
  retention, capture sensor supply and signal, and apply the degraded-mode rule.
- **Unexpected enable or E-stop failure:** remove power, quarantine the unit,
  and execute the dual-channel truth-table test. This is a safety failure, not a
  software retry.
- **Thermal rise:** stop at the first limit breach, capture current and surface
  temperature, inspect airflow/thermal interfaces, and open a QA defect.

Every branch ends with a diagnostic record, disposition (`REPAIR`, `RETEST`,
`SCRAP`, or `ESCALATE`) and linked evidence path.
