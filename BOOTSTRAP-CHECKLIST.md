# Project Owner bootstrap checklist

Complete these items before the team branches from the foundation:

- [ ] Approve the public repository name and organization.
- [ ] Choose the source-code license; update ADR-0002 and add `LICENSE`.
- [ ] Replace role placeholders in `.github/CODEOWNERS.example`, then rename it to `.github/CODEOWNERS`.
- [ ] Create the GitHub remote and push the initial reviewed commit.
- [ ] Protect `main`: PR required, required CI, resolved conversations, no force-push or deletion.
- [ ] Create nine Epics from `docs/product/EXECUTION-PLAN.md`.
- [ ] Require one Task Packet and one W1 Issue from each Owner.
- [ ] Freeze `WorkbenchSim-v0`, 30-scenario categories and the release holdout Owner.

Do not start feature implementation until the owner map, license decision and CI checks are visible in the repository.
