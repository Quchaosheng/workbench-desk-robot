# Lessons learned

## Evidence boundaries must be encoded

Scripted evaluation makes interface behavior reviewable, but it is not Gazebo or hardware evidence. Keeping `release_eligible: false` in generated outputs is stronger than relying on a note in a meeting.

## Defaults are part of the threat and failure model

The v0.1.0 release ran checks, built and smoke-tested the image, then failed because the SBOM action defaulted to uploading a release asset. Third-party action inputs and permissions need an explicit regression test, not only version pinning.

## Cross-layer contracts need one change unit

Schema and Pydantic model changes previously drifted when split across PRs. The repository now requires same-PR updates, three-owner review, and full contract validation. Ownership rules should be executable wherever possible.

## Blocked reports can still be successful controls

Hardware/procurement validators pass while their business status remains `RELEASE_BLOCKED` or `ORDER_RELEASE_BLOCKED`. A successful validator means the report is internally consistent; it does not mean the physical gate passed.

## Baselines and forecasts serve different purposes

The baseline preserves accountability. Forecasts may move as evidence arrives, but rewriting the baseline hides variance and weakens risk learning.

