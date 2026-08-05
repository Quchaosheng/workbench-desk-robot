# operator_console

Operator-facing console for monitoring, manual override, and replay review.

Separate from `apps/dashboard` (which is task-status display for bystanders).
This is for operators who need to:
- Cancel a running task
- Trigger manual recovery
- Review failure evidence
- Approve a re-attempt after insufficient_evidence

Not implemented yet. Waiting for core task loop to stabilise in v0.1.
