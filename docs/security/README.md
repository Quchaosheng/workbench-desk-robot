# Security engineering baseline

Security controls protect code, dependencies, evidence integrity, deployment, and robot authority. They do not substitute for functional, simulation, or physical safety validation.

## Security task map

| Task | Control / artifact | State |
|---|---|---|
| SEC1 code audit standard | [Secure review standard](secure-review-standard.md) plus CodeQL | ACTIVE after workflow merge |
| SEC2 SBOM generation | pinned Anchore workflow and [supply-chain policy](supply-chain.md) | ACTIVE; next release proof pending |
| SEC3 dependency scanning | PR dependency review and Dependabot configuration | ACTIVE after workflow merge |
| SEC4 penetration test | [authorized test plan](penetration-test-plan.md) | NOT_EXECUTED |
| SEC5 security hardening | [Hardening baseline](hardening.md) | PARTIAL; review per deployment |
| SEC6 incident response | [Incident response](incident-response.md) | DEFINED; exercise pending |
| SEC7 security documentation | `SECURITY.md` plus this handbook | DEFINED |
| SEC8 compliance review | [Control matrix](compliance-matrix.md) | READINESS_ONLY; not certified |

## Release-blocking rules

- unresolved critical/high code, dependency, secret, container, or authority-boundary finding;
- a model or public interface gains raw control, emergency-stop, release, or completion authority;
- required SBOM/provenance is missing or cannot be tied to the published digest;
- penetration, compliance, or physical results are claimed without eligible evidence;
- a response action would destroy incident or safety evidence.

The Security Owner triages findings. Module owners implement fixes. A human Project Owner decides release and time-bounded risk acceptance.
