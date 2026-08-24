# Mechanical engineering package

This directory is the source-controlled mechanical concept for the Workbench
Home Robot, Revision D. It is no longer the 280 x 240 x 330 mm tabletop shell.
The current target is a 540 x 520 mm mobile base with a 350 mm braked liftable torso,
a continuous mineral-white utility body, two seven-axis arms, an 18 L parcel bay,
and a locked quick-change tool system.

## Product architecture

- **Mobile base:** low-mounted battery and ballast, enclosed drive pods, wheel
  brakes, and four deployable stabilizer feet for stationary manipulation.
- **Lift:** four guides, two synchronized screws, two normally-closed brakes,
  two mechanical lock pins, dual encoders, hard limits, and pinch detection.
- **Arms:** each arm has J1 base yaw, J2 shoulder pitch, J3 shoulder roll,
  J4 elbow pitch, J5 forearm roll, J6 wrist pitch, and J7 tool roll. The per-arm
  planning envelope is 2 kg at 650 mm reach or 3 kg at 400 mm at reduced speed; these are not yet
  certified performance claims.
- **Tools:** adaptive parcel gripper, compliant brush/dry-mop head, and a
  removable 316L/PEEK/silicone induction-cooking tool. Cooking is supervised,
  induction-only, and excludes open flame, boiling-liquid carry, and hot-pan
  transport.

## Industrial design and CMF

The consumer-facing surface is a continuous warm mineral-white shell with hidden
primary parting lines. The structural waist, lift, and arm links use bead-blasted
graphite anodized aluminium; the face is a single smoked strengthened-glass
lens; the parcel-bay/acoustic insert is graphite 3D-knit recycled PET. Jade or
warm amber is reserved for one status light. Visible glossy plastic, exposed
fasteners, decorative color blocks, toy-like antennae, and exposed wheels are
out of scope.

The head uses a wide rounded-rectangle expression window inside a soft white
frame. It is not a floating shell: a dedicated neck mount has a load-bearing
pedestal, broad shoulder plate, keyed head register, four hidden M6 fasteners,
two dowel pins, and a 32 mm central cable passage. The head is lifted onto the
register after the harness is connected and can be removed vertically after
the rear cover and underside fasteners are released. Both shoulder centres are
mounted in the torso side walls below that neck; neither arm supports or
visually frames the head.

## Reproduce

```bash
python hardware/mechanical/tools/generate_artifacts.py
```

The command regenerates the analytical report, C revision general arrangement,
thermal path, drop screen, BOM, assembly sequence, and CadQuery STEP package.
It intentionally reports `CONCEPT_PHYSICAL_VALIDATION_REQUIRED`: no rendering
or analytical result substitutes for lift synchronization, arm sweep, thermal,
stability, force-limit, or guarded household-task tests on a serialized unit.

- `generated/enclosure.step`: torso exchange solid for supplier review.
- `generated/desk_robot_assembly.step`: mobile base, lift, torso, head, dual 7R arms,
  stabilizers, and tool dock assembly.
- `generated/desk_robot_exploded.step`: exploded assembly for work instructions.
- `generated/parts/*.step`: ten D revision concept parts, including the separate neck mount.
- `generated/drawings/general-arrangement.svg`: D revision architecture and lift states.
- `generated/drawings/thermal-flow.svg`: isolated electronics airflow path.
- `generated/analysis.json`: mass, CG, drive/stabilized tip screens, payload moment, and clearances.
- `revision-d-architecture.md`: bimanual workspace, task boundary, and architecture rationale.
