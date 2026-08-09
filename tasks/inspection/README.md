# inspection

Check one or more attributes of an object: colour, orientation, presence of
markings, dimensional check via depth camera.

Verifier outputs per-attribute results and an overall pass/fail.
"Insufficient evidence" on any attribute propagates to the overall result.

The v0.2 offline template observes three workpieces and requests presence,
identity, and orientation evidence. The verifier requires every entity to be
observed above the confidence threshold and refuses completion without evidence.
