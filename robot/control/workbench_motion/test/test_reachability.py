"""Unit tests for the ROS-free reachability logic.

These are behaviour tests for the phase-1 acceptance gate's deterministic half:
sampling is reproducible and bounded, and scoring enforces the >=95% threshold
exactly at the boundary. They run under ``uv run pytest`` with no ROS/MoveIt.
The MoveIt-connected IK run is verified separately as PR local evidence.
"""

from __future__ import annotations

import math
import random

import pytest
from workbench_motion.reachability import (
    BLOCK_REGION,
    TRAY_REGION,
    Region,
    all_passed,
    default_regions,
    sample_poses,
    score_region,
    top_down_quat,
)


def test_sampling_is_deterministic_for_a_seed():
    a = sample_poses(BLOCK_REGION, 20, random.Random(0))
    b = sample_poses(BLOCK_REGION, 20, random.Random(0))
    assert a == b  # same seed -> identical poses (archived numbers are replayable)


def test_different_seeds_differ():
    a = sample_poses(BLOCK_REGION, 20, random.Random(0))
    b = sample_poses(BLOCK_REGION, 20, random.Random(1))
    assert a != b


@pytest.mark.parametrize("region", default_regions())
def test_samples_stay_inside_region_bounds(region: Region):
    for p in sample_poses(region, 50, random.Random(7)):
        assert region.x_min <= p.x <= region.x_max
        assert region.y_min <= p.y <= region.y_max
        assert region.z_min <= p.z <= region.z_max


def test_sample_count_matches_request():
    assert len(sample_poses(TRAY_REGION, 23, random.Random(3))) == 23


def test_sample_poses_rejects_nonpositive_n():
    with pytest.raises(ValueError):
        sample_poses(BLOCK_REGION, 0, random.Random(0))


def test_top_down_quat_is_normalised_and_points_down():
    for yaw in (-math.pi, -1.0, 0.0, 1.0, math.pi):
        qx, qy, qz, qw = top_down_quat(yaw)
        assert math.isclose(qx * qx + qy * qy + qz * qz + qw * qw, 1.0, rel_tol=1e-9)
        # Rotating the body +z axis by this quaternion must yield world -z (down).
        # v' = q * (0,0,1) * q^-1 ; z-component check is enough for "points down".
        # Using the rotation-matrix element R[2][2] = 1 - 2(qx^2 + qy^2).
        r22 = 1.0 - 2.0 * (qx * qx + qy * qy)
        assert math.isclose(r22, -1.0, abs_tol=1e-9)


def test_region_rejects_inverted_bounds():
    with pytest.raises(ValueError):
        Region(name="bad", x_min=1.0, x_max=0.0, y_min=0.0, y_max=1.0, z_min=0.0, z_max=1.0)


def test_score_region_rate_and_pass():
    res = score_region("block", [True] * 19 + [False], threshold=0.95)
    assert res.total == 20
    assert res.successes == 19
    assert math.isclose(res.rate, 0.95)
    assert res.passed  # exactly at threshold passes


def test_score_region_just_below_threshold_fails():
    res = score_region("tray", [True] * 18 + [False] * 2, threshold=0.95)
    assert math.isclose(res.rate, 0.90)
    assert not res.passed


def test_score_region_empty_raises():
    with pytest.raises(ValueError):
        score_region("empty", [], threshold=0.95)


def test_all_passed_requires_every_region():
    good = score_region("a", [True] * 20, threshold=0.95)
    bad = score_region("b", [True] * 10 + [False] * 10, threshold=0.95)
    assert all_passed([good])
    assert not all_passed([good, bad])
    assert not all_passed([])  # empty is not a pass
