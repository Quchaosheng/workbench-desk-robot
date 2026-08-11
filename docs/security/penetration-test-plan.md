# Penetration-test plan

Status: **NOT_EXECUTED**. This plan is not a penetration-test result, attestation, or release approval.

## Authorization and scope

A human Project Owner must approve dates, testers, target commits/images, network range, data handling, emergency contacts, stop conditions, and physical-device exclusions in writing. Default scope is the isolated dashboard/backend container and optional local model boundary using synthetic event data. Public GitHub, third-party services, production credentials, firmware, emergency stop, and physical motion are out of scope unless separately authorized.

## Test cases

| Area | Cases | Expected control |
|---|---|---|
| HTTP boundary | unsupported methods, traversal, malformed encoding, oversized identifiers, cache confusion | writes rejected; paths contained; bounded errors without sensitive data |
| event ingestion | malformed JSONL, duplicate IDs, sequence rollback, forged evidence references | readiness fails closed; no partial trusted state |
| model endpoint | remote hosts, redirects, credentials, DNS/host confusion, malformed output | request rejected before plan construction |
| dashboard | stored/reflected script payloads, unsafe URLs, DOM injection, sensitive fixture data | output encoded; no executable attacker content or control path |
| container | UID/capabilities, writable paths, host/network exposure, secret mounts | non-root, read-only, minimal network and mounts |
| supply chain | dependency confusion, mutable action/image references, SBOM/provenance mismatch | immutable references and review gate detect drift |
| availability | bounded malformed request rate and corrupted data source | service degrades predictably; evidence preserved |

## Evidence package

Retain authorization, target hashes/digests, tool names/versions/configuration, timestamps, raw findings, sanitized reproductions, severity rationale, remediation commits, retest results, unresolved risk acceptance, and tester signature. Store secrets and exploit material outside public artifacts.

Stop immediately on unintended physical motion, access to real secrets/private data, third-party impact, loss of evidence integrity, or a target outside authorization. Follow the incident-response plan if active compromise is suspected.
