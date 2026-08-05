# pick_place

Put object A into container B.

This is the v0.1 demo task. The verifier checks spatial containment:
is the object inside the tray bounding box, with sufficient confidence?

Verifier: `tasks/pick_place/verifier.py` (→ `services/world_model`)
Scenarios: `sim/scenarios/frozen/normal-*.json`, `occlusion-*.json`, etc.
