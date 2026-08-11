# Secure review standard

## Review inputs

Every review identifies the change owner, affected trust boundary, data class, dependencies, secrets/permissions, failure mode, tests, and evidence. Review the diff and generated artifacts; never accept a green check without understanding what it measured.

## Required checks

| Change type | Required review |
|---|---|
| Python or service logic | CodeQL, Ruff correctness rules, behavior tests, input/error-path review |
| dependency or action | dependency review, immutable action pin, license/source review, exit plan |
| container or deployment | non-root/read-only/capability/network/secret review, image smoke test, SBOM |
| model/runtime boundary | host allowlist, credential rejection, schema validation, no raw control authority |
| interface or contract | three-owner approval, producer/consumer review, matching Pydantic model, `make contract` |
| dashboard or logs | read-only HTTP boundary, output encoding, sensitive-data review, write-method rejection |
| robot/control or firmware | human owner authorization and path-specific safety tests; outside routine AI write scope |

## Reviewer checklist

- Validate all externally controlled input before use; fail closed on malformed, missing, duplicate, or ambiguous identity.
- Preserve dispatch state, device state, verification state, and evidence separately.
- Avoid shell construction, unsafe deserialization, path traversal, unrestricted URLs, and broad exception suppression.
- Keep credentials out of command lines, logs, exceptions, fixtures, images, and artifacts.
- Use minimal workflow/job permissions and immutable third-party action commits.
- Test denied and degraded paths, not only the happy path.
- Confirm logs support incident reconstruction without exposing secrets or unnecessary personal data.
- Check that a fixture, mock, screenshot, or successful validator is not mislabeled as physical evidence.

## Severity and release response

| Severity | Example | Response |
|---|---|---|
| critical | unauthenticated raw robot control, secret exfiltration, false-completion bypass | contain immediately; block release and affected deployment |
| high | privilege escalation, remote code execution, evidence tampering, known exploitable dependency | fix or obtain documented human exception before release |
| medium | bounded information disclosure or hardening gap with prerequisites | owner and due date required; evaluate release context |
| low | defense-in-depth improvement with no demonstrated impact | backlog with rationale and review date |

Risk acceptance records the finding, affected versions, compensating controls, owner, approver, expiry, and retest date. AI tools cannot accept risk.
