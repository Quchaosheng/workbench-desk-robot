# 90-minute demonstration runbook

This route proves that a trained evaluator can move from inspection to a recorded
safe demo in 90 minutes. It does not replace site acceptance or certification.

| Time | Activity | Exit evidence |
|---:|---|---|
| 0-10 min | area, unit, battery, guards, E-stop, payload inspection | signed preflight |
| 10-20 min | start services and verify released versions/configuration | readiness snapshot |
| 20-30 min | operator controls, normal stop, E-stop and reset briefing | training acknowledgement |
| 30-45 min | calibrate/confirm sensors and arm home positions | calibration IDs |
| 45-60 min | run scripted single-arm task at reduced speed | task log and video |
| 60-75 min | run coordinated dual-arm task with handoff/interlock | task log and video |
| 75-85 min | inject one approved recoverable fault and restore | fault/recovery record |
| 85-90 min | park, shutdown, export evidence, review pass/fail | evidence bundle checksum |

Abort on safety-chain failure, uncontrolled motion, unexpected collision, battery
alarm, excessive temperature, repeated communication loss, evidence recorder loss,
or any condition outside the approved demo envelope. Record an abort as a valid
result; never compress later steps to preserve the 90-minute target.
