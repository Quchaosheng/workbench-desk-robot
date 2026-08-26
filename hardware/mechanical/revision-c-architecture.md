# Revision C mobile manipulator architecture

Revision C is a household utility robot concept, not the earlier tabletop enclosure. The lower platform carries the battery, drive, ballast, brakes, and deployable stabilizers. A dual-guide, dual-screw lift raises the complete upper body and arm while normally-closed brakes and mechanical lock pins prevent uncontrolled descent.

## Seven-axis arm

The arm has seven revolute axes excluding the gripper: base yaw, shoulder pitch, shoulder roll, elbow pitch, forearm roll, wrist pitch, and tool roll. The redundant axis supports reaching around counters and doors without forcing the wrist into poor orientations. Joint torque values in `design-spec.json` are planning classes, not certified continuous ratings.

The target payload envelope is deliberately pose-dependent: 2 kg continuously at 650 mm reach, or 3 kg at 400 mm under reduced speed. The quick-change wrist carries an adaptive gripper, compliant cleaning head, or a removable food-contact tool. Cables remain inside the structural links; exposed spiral harnesses are not part of the consumer design.

## Lift and stability

The 250 mm lift uses two synchronized screws and four guides. Both encoders, upper/lower hard limits, motor-current pinch detection, normally-closed brakes, and mechanical lock pins are required. Raising the body or extending the arm reduces drive speed. Manipulation beyond the low-speed envelope requires wheel brakes and deployed stabilizers.

The driving footprint fits an indoor doorway; the larger stabilization polygon is only deployed while stationary. Analytical tip margin is a design screen. Release still requires maximum-reach pull testing, lift synchronization tests, emergency-stop tests, and floor-friction trials with a serialized prototype.

## Domestic task boundary

Parcel handling covers indoor pickup from a reachable shelf or doorstep and delivery to the onboard bay. It does not include stairs, uncontrolled elevators, locked doors, or public-road operation. Cleaning uses force-limited removable tools. Cooking assistance is restricted to supervised induction work with 316L stainless/PEEK tools, a thermal wrist barrier, washable covers, spill detection, and no open flame. The robot does not carry people, boiling liquid, or an unrestrained hot pan.

Status: `CONCEPT_PHYSICAL_VALIDATION_REQUIRED`.
