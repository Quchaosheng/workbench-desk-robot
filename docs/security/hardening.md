# Hardening baseline

## Application and authority

- Dashboard endpoints remain `GET`-only; write methods fail closed.
- The dashboard has no ROS, MCU, motion, emergency-stop, secret, or release publisher.
- Models return a bounded route; trusted deterministic builders construct semantic actions.
- Remote or credentialed model endpoints are rejected by default.
- Verifier conclusions require evidence and remain separate from action/device status.

## Container and network

- Run as non-root UID `10001` with a read-only filesystem, `no-new-privileges`, and all Linux capabilities dropped.
- Bind the dashboard to localhost by default.
- Keep the optional model runtime on an internal network; only the bootstrap profile receives egress for explicit provisioning.
- Pin base and model images by digest; rebuild and rescan after updates.
- Use a small writable `tmpfs`; do not mount host control sockets or secret directories into the dashboard.

## Secrets and logs

- Use short-lived least-privilege GitHub/environment credentials and job-level permissions.
- Never place tokens in source, image layers, Compose files, CLI arguments, screenshots, fixtures, event logs, or artifacts.
- Structured logs retain run ID and monotonic sequence for investigation, but omit prompts/private payloads unless explicitly approved and access-controlled.
- Rotate an exposed credential before investigating convenience or blame.

## Deployment review

This baseline must be re-evaluated for TLS termination, authentication, reverse proxies, remote access, orchestration, host mounts, device access, and physical networks. The current localhost/offline assumptions do not authorize an internet-facing deployment.
