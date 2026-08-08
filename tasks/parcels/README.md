# parcel handling

Process any non-empty batch of parcels already present at the tabletop
workstation. The bounded flow scans the complete batch before manipulation,
routes verified intact parcels to a pickup shelf, and isolates damaged,
unreadable, or otherwise unverified parcels in a quarantine bin. Exceptions are
handled first so the arm does not carry a questionable item through the pickup
area. Condition exceptions are handled before label-only exceptions, followed
by verified intact parcels. Before any action graph is returned, an optional
capacity snapshot can reject a batch that would overflow either managed zone;
the planner never starts a batch that it already knows it cannot finish.

Parcel IDs that normalize to the same readable step name are disambiguated, so
mixed upstream naming styles cannot create duplicate graph steps. Capacity,
projected occupancy, policy version, priority, and routing reason are retained
in semantic action parameters for audit and replay.

When perception supplies a `tracking_id`, `barcode`, or `parcel_uid`, the batch
preflight normalizes compatibility characters, case, whitespace, and hyphens,
then rejects a repeated value even when it moves between identity fields. The
verifier repeats that guard from world-state attributes, so scanner formatting
differences cannot turn one parcel into two separately handled parcels.

An optional inbound manifest can bind every planned parcel to one or more of
those non-personal identity values. Planning fails before manipulation when the
manifest is incomplete, an observed identity is missing, or no observed value
matches the expected entry. The independent verifier treats a missing observed
identity as `insufficient_evidence` and a contradictory identity as `refuted`.
Manifest IDs and per-parcel match outcomes remain in the action and replay
metadata; recipient names and addresses are deliberately out of scope.

The verifier requires per-parcel confidence and evidence, exact destinations,
verified labels, the expected condition, a policy-derived destination, and no
extra parcel in either managed zone. Missing label or condition evidence is
`insufficient_evidence`; an observed mismatch or wrong destination is
`refuted`.

This capability does not navigate to a lobby or parcel locker. Requests that
require a mobile base fail closed until a navigation contract and hardware are
owned by the project.
