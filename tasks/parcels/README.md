# parcel handling

Process parcels already present at the tabletop workstation. The bounded flow
observes each label and package condition, routes verified intact parcels to a
pickup shelf, and isolates damaged parcels in a quarantine bin.

The verifier requires per-parcel confidence and evidence, exact destinations,
verified labels, the expected condition, and no extra parcel in either managed
zone. Missing label or condition evidence is `insufficient_evidence`; an
observed mismatch or wrong destination is `refuted`.

This capability does not navigate to a lobby or parcel locker. Requests that
require a mobile base fail closed until a navigation contract and hardware are
owned by the project.
