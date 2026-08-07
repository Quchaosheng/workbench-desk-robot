# parcel handling

Process any non-empty batch of parcels already present at the tabletop
workstation. The bounded flow scans the complete batch before manipulation,
routes verified intact parcels to a pickup shelf, and isolates damaged,
unreadable, or otherwise unverified parcels in a quarantine bin. Exceptions are
handled first so the arm does not carry a questionable item through the pickup
area.

The verifier requires per-parcel confidence and evidence, exact destinations,
verified labels, the expected condition, a policy-derived destination, and no
extra parcel in either managed zone. Missing label or condition evidence is
`insufficient_evidence`; an observed mismatch or wrong destination is
`refuted`.

This capability does not navigate to a lobby or parcel locker. Requests that
require a mobile base fail closed until a navigation contract and hardware are
owned by the project.
