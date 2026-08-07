# kitting

Assemble a kit by placing multiple specific parts into a tray in any order.

Verifier checks:
- Each required part is present in the tray
- No extra parts
- Each part has sufficient detection confidence

The v0.2 offline template now emits independent observe/grasp/place branches
for `red_block`, `blue_cylinder`, and `green_gear`. The verifier is
order-independent and fails closed when a required part is missing, an extra
part is in the tray, confidence is below threshold, or evidence is absent.
