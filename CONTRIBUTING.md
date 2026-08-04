# Contributing

## Before coding

1. Use a Ready Issue with one human Owner and acceptance criteria.
2. Confirm the owning path and interface schemas.
3. Branch from current `main`.

## Branches

```text
feat/<issue>-<short-name>
fix/<issue>-<short-name>
test/<issue>-<short-name>
docs/<issue>-<short-name>
chore/<issue>-<short-name>
```

## Commits

Use Conventional Commits and DCO sign-off:

```text
feat(world-model): add deterministic tray verifier

Signed-off-by: Your Name <you@example.com>
```

## Pull requests

- Keep one purpose per PR.
- Do not mix interface, feature and formatting rewrites unless required.
- Include exact commands and results.
- Request the module Owner and every affected contract consumer.
- Never force-push or commit directly to protected `main`.

## Required local checks

```bash
make test
make contract
make scenario-check
make context-check
make demo-scripted
```

ROS, simulation and firmware PRs add their path-specific checks. A screenshot is evidence for UI appearance, not for physical task completion or safety.
