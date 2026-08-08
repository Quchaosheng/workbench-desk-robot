# Defect and corrective-action workflow

`OPEN -> CONTAINED -> ROOT_CAUSE_PENDING -> CORRECTIVE_ACTION -> VERIFY -> CLOSED`

Any safety, electrical overstress, or traceability defect moves the affected lot
to `QUARANTINED` before analysis. The defect record must include the first known
bad serial/lot, containment quantity, reproduction steps, suspected cause,
disposition authority, corrective-action revision, and verification evidence.

Use the manufacturing defect codes as the controlled vocabulary. A rework is not
closed until the same inspection gate is repeated and linked to the defect ID.
Do not delete failed records; close them with a disposition and evidence path.
