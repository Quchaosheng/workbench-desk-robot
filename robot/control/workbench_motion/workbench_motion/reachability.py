"""Pure (ROS-free) reachability sampling and pass/fail logic.

The phase-1 acceptance gate (PLAN.md §阶段 1) is: sample >=20 targets over the
block region and >=20 over the tray region, run IK, and require >=95% success
*per region* — with the numbers and the RNG seed archived.

This module owns the deterministic, testable half of that: what the regions are,
how positions are sampled, the candidate approach yaws, and how per-target IK
results are scored against the threshold. It has NO ROS imports, so it runs and
is unit-tested under a plain ``uv run pytest`` with no MoveIt installed. The ROS
half — actually calling MoveIt ``/compute_ik`` — lives in
``workbench_motion/reachability_check.py`` and imports this module.

What "reachable" means here (settled after diagnosis, see ``candidate_yaws``): a
sampled *position* is graspable if **at least one** top-down approach yaw yields a
collision-free, IK-valid solution. A parallel-jaw grasp is symmetric mod 180° and
a grasp planner chooses the wrist roll, so requiring an arbitrarily-dictated yaw
to be collision-free (an earlier mistake) measured a capability the system never
uses. The script still archives the raw pure-IK reach rate and the per-position
count of collision-free yaws, so the stricter view stays visible.

Frames: all poses are in the workbench ``world`` frame. Orientation is a top-down
grasp (grasp_tcp z-axis into the table, world -z) with a yaw about vertical.
Region bounds are Motion's sampling volumes over the block-start patch and the
tray opening; numbers trace to robot/description/FRAMES.md (surface top at world
z=0.75, module start near surface (-0.15, 0.05), tray near surface (0.22, -0.10),
tray depth 0.05).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# Quaternion (x, y, z, w) for a pure rotation of pi about the x-axis: maps the
# +z axis to -z, i.e. a tool pointing straight down. Yaw is composed on top.
_FLIP_DOWN_XYZW = (1.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Pose:
    """A target pose in the world frame: position (m) + quaternion (x, y, z, w)."""

    x: float
    y: float
    z: float
    qx: float
    qy: float
    qz: float
    qw: float


@dataclass(frozen=True)
class Region:
    """An axis-aligned sampling box in the world frame (metres).

    Poses are sampled uniformly within [min, max] on each axis. The z band is a
    hover range above the surface, not the surface itself, because grasp/place
    approach the target from above.
    """

    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float

    def __post_init__(self) -> None:
        if self.x_min > self.x_max or self.y_min > self.y_max or self.z_min > self.z_max:
            raise ValueError(f"region {self.name!r} has an inverted bound")


# Default sampling regions. Provenance in the module docstring / FRAMES.md.
# Block region: a 10 cm patch around the module start, hovering above the surface.
BLOCK_REGION = Region(
    name="block",
    x_min=-0.20,
    x_max=-0.10,
    y_min=0.00,
    y_max=0.10,
    z_min=0.80,
    z_max=0.90,
)
# Tray region = valid *place targets*, derived from FRAMES.md, not tuned to pass.
# Cavity interior is 0.228 (x) by 0.168 (y) centred on tray_base at surface
# (0.22, -0.10); rim top is ~world z 0.80. A place target is the cavity interior
# inset by the gripper clearance (Robotiq 2F-85 finger half-width ~0.043 m +
# ~0.007 margin ≈ 0.05 each side) so the fingers clear the walls, hovering above
# the rim so the 40 mm block clears the opening on descent:
#   x: 0.22 ± (0.114 - 0.05) = [0.156, 0.284]
#   y: -0.10 ± (0.084 - 0.05) = [-0.134, -0.066]
#   z: [0.86, 0.92]  (TCP above the 0.80 rim)
# This is why the earlier [0.13, 0.31] by [-0.17, -0.03] band failed a corner: its
# far x-edge (0.31) sat ~1 cm from the far wall AND at the arm's reach limit, a
# spot no wrist yaw could clear — and not a place a block would ever be set down.
TRAY_REGION = Region(
    name="tray",
    x_min=0.156,
    x_max=0.284,
    y_min=-0.134,
    y_max=-0.066,
    z_min=0.86,
    z_max=0.92,
)


def default_regions() -> list[Region]:
    """The two phase-1 sampling regions: block start and tray opening."""
    return [BLOCK_REGION, TRAY_REGION]


def candidate_yaws(count: int = 12) -> tuple[float, ...]:
    """Deterministic top-down approach yaws spanning ``[0, pi)``.

    A parallel-jaw grasp is symmetric under a 180° wrist roll (yaw and yaw+pi are
    the same physical grasp), so the distinct approach directions live in
    ``[0, pi)``. A grasp planner is free to pick any of them; reachability asks
    whether *at least one* is collision-free and IK-valid at a position (see
    module docstring / the ``reachability_check`` script). Diagnosis showed pure
    IK reaches 100% of poses and the collision-free yaws form a contiguous arc, so
    the failures the earlier per-yaw metric reported were an artifact of dictating
    a random wrist roll the system never needs to honour.
    """
    if count <= 0:
        raise ValueError("count must be positive")
    return tuple(i * math.pi / count for i in range(count))


def _quat_mul(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Hamilton product of two (x, y, z, w) quaternions -> (x, y, z, w)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def top_down_quat(yaw: float) -> tuple[float, float, float, float]:
    """Top-down grasp orientation with a yaw about world z, as (x, y, z, w).

    Composed as Rz(yaw) * Rx(pi): flip the tool to point down, then yaw about the
    world vertical. Always returned normalised.
    """
    half = yaw / 2.0
    q_yaw = (0.0, 0.0, math.sin(half), math.cos(half))
    qx, qy, qz, qw = _quat_mul(q_yaw, _FLIP_DOWN_XYZW)
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    return (qx / norm, qy / norm, qz / norm, qw / norm)


def sample_positions(region: Region, n: int, rng: random.Random) -> list[tuple[float, float, float]]:
    """Sample ``n`` positions uniformly within ``region`` using ``rng``.

    Deterministic for a given seeded ``rng`` — the same seed reproduces the same
    positions, which is what lets the archived reachability numbers be replayed.
    Orientation is handled separately via :func:`candidate_yaws`, because a
    position is graspable if *any* approach yaw works (see module docstring).
    """
    if n <= 0:
        raise ValueError("n must be positive")
    positions: list[tuple[float, float, float]] = []
    for _ in range(n):
        x = rng.uniform(region.x_min, region.x_max)
        y = rng.uniform(region.y_min, region.y_max)
        z = rng.uniform(region.z_min, region.z_max)
        positions.append((x, y, z))
    return positions


def poses_at(position: tuple[float, float, float], yaws: tuple[float, ...]) -> list[Pose]:
    """Build the top-down candidate poses at ``position`` for each yaw."""
    x, y, z = position
    poses: list[Pose] = []
    for yaw in yaws:
        qx, qy, qz, qw = top_down_quat(yaw)
        poses.append(Pose(x=x, y=y, z=z, qx=qx, qy=qy, qz=qz, qw=qw))
    return poses


@dataclass(frozen=True)
class RegionResult:
    """Scored IK outcome for one region."""

    name: str
    total: int
    successes: int
    threshold: float

    @property
    def rate(self) -> float:
        return self.successes / self.total if self.total else 0.0

    @property
    def passed(self) -> bool:
        return self.total > 0 and self.rate >= self.threshold


def score_region(name: str, successes: list[bool], threshold: float = 0.95) -> RegionResult:
    """Score a region's per-pose boolean IK results against ``threshold``."""
    if not successes:
        raise ValueError(f"region {name!r} has no results to score")
    return RegionResult(
        name=name,
        total=len(successes),
        successes=sum(1 for ok in successes if ok),
        threshold=threshold,
    )


def all_passed(results: list[RegionResult]) -> bool:
    """True only if every region met its threshold (and there is at least one)."""
    return bool(results) and all(r.passed for r in results)
