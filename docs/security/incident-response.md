# Incident response

## Roles

| Role | Responsibility |
|---|---|
| Incident Commander | scope, priority, safety, communications, and closure decision |
| Security Lead | triage, evidence plan, containment options, and retest |
| System/Module Owner | technical diagnosis, remediation, and recovery validation |
| Project Owner | release/deployment decision, risk acceptance, and external disclosure |
| Scribe | immutable timeline, actions, evidence references, and decision record |

## Lifecycle

1. **Receive privately:** acknowledge, create restricted record, assign commander and security lead.
2. **Triage:** identify affected versions/assets, data, authority boundary, exploitation, and severity.
3. **Preserve:** record time source, commit/image digests, logs, hashes, access, and chain of custody before destructive action when safety permits.
4. **Contain:** revoke/rotate credentials, isolate service/network, stop publication or physical operation, and preserve evidence.
5. **Eradicate:** remove root cause, add regression detection, scan related paths and versions.
6. **Recover:** restore from a verified source, validate security/function/safety gates, monitor for recurrence.
7. **Disclose and learn:** human-approved advisory, affected-user guidance, timeline, root cause, corrective actions, and effectiveness review.

Safety takes priority over evidence preservation during immediate physical danger. Record the action and rationale as soon as safe.

## Severity triggers

Critical/high examples include exposed credentials, raw robot/control authority, false-completion bypass, arbitrary code execution, evidence tampering, public private-log access, or an exploitable dependency in the runtime path. These block release and affected operation until fixed or covered by a time-bounded human risk decision.

## Exercise

Run a tabletop before P1 release using a synthetic leaked token plus forged evidence event. Verify private intake, rotation, service isolation, timeline/evidence capture, regression test, and coordinated status update. Record the exercise as a drill; do not call it a real incident or penetration test.
