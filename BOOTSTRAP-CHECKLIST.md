# Project Owner bootstrap checklist

Complete these items before the team branches from the foundation:

- [ ] Approve the public repository name and organization.
- [ ] Choose the source-code license; update ADR-0002 and add `LICENSE`.
- [x] Track ownership on individual Issues and request reviewers per PR; do not publish a global owner map.
- [ ] Create the GitHub remote and push the initial reviewed commit.
- [ ] Protect `main`: PR required, required CI, resolved conversations, no force-push or deletion.
- [ ] Create one Epic per module from the internal execution plan (kept outside this repo).
- [ ] Require one Task Packet and one first-milestone Issue from each Owner.
- [ ] Freeze the simulation world version, the scenario categories and the release holdout Owner.

Do not start feature implementation until its Issue owner, license decision and CI checks are recorded.
