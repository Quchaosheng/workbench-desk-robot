"""Unit tests for the ROS-free reachability logic.

These are behaviour tests for the phase-1 acceptance gate's deterministic half:
sampling is reproducible and bounded, and scoring enforces the >=95% threshold
exactly at the boundary. They run under ``uv run pytest`` with no ROS/MoveIt.
The MoveIt-connected IK run is verified separately as PR local evidence.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest
from workbench_motion.reachability import (
    BLOCK_REGION,
    GATE_MIN_SAMPLES,
    GATE_MIN_THRESHOLD,
    TRAY_REGION,
    Region,
    all_passed,
    candidate_yaws,
    default_regions,
    is_gate_qualifying,
    poses_at,
    sample_positions,
    score_region,
    top_down_quat,
    validate_run_params,
)


def test_sampling_is_deterministic_for_a_seed():
    a = sample_positions(BLOCK_REGION, 20, random.Random(0))
    b = sample_positions(BLOCK_REGION, 20, random.Random(0))
    assert a == b  # same seed -> identical positions (archived numbers are replayable)


def test_different_seeds_differ():
    a = sample_positions(BLOCK_REGION, 20, random.Random(0))
    b = sample_positions(BLOCK_REGION, 20, random.Random(1))
    assert a != b


@pytest.mark.parametrize("region", default_regions())
def test_samples_stay_inside_region_bounds(region: Region):
    for x, y, z in sample_positions(region, 50, random.Random(7)):
        assert region.x_min <= x <= region.x_max
        assert region.y_min <= y <= region.y_max
        assert region.z_min <= z <= region.z_max


def test_sample_count_matches_request():
    assert len(sample_positions(TRAY_REGION, 23, random.Random(3))) == 23


def test_sample_positions_rejects_nonpositive_n():
    with pytest.raises(ValueError):
        sample_positions(BLOCK_REGION, 0, random.Random(0))


def test_candidate_yaws_span_symmetric_half_turn():
    yaws = candidate_yaws(12)
    assert len(yaws) == 12
    assert yaws[0] == 0.0
    # Parallel-jaw grasp is symmetric mod pi: all candidates live in [0, pi).
    assert all(0.0 <= y < math.pi for y in yaws)
    assert yaws == tuple(sorted(yaws))  # deterministic, ascending


def test_candidate_yaws_rejects_nonpositive():
    with pytest.raises(ValueError):
        candidate_yaws(0)


def test_poses_at_builds_one_top_down_pose_per_yaw():
    pos = (-0.15, 0.05, 0.85)
    yaws = candidate_yaws(6)
    poses = poses_at(pos, yaws)
    assert len(poses) == 6
    for p in poses:
        assert (p.x, p.y, p.z) == pos
        # every pose is a unit quaternion pointing down (R[2][2] == -1)
        assert math.isclose(p.qx**2 + p.qy**2 + p.qz**2 + p.qw**2, 1.0, rel_tol=1e-9)
        r22 = 1.0 - 2.0 * (p.qx**2 + p.qy**2)
        assert math.isclose(r22, -1.0, abs_tol=1e-9)


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


# --- run-parameter guards (defends against weakened-green reports) ---


def test_validate_run_params_accepts_gate_defaults():
    validate_run_params(samples=20, yaws=12, threshold=0.95)  # no raise


@pytest.mark.parametrize(
    "samples,yaws,threshold",
    [
        (0, 12, 0.95),
        (-1, 12, 0.95),
        (20, 0, 0.95),
        (20, 12, -0.01),
        (20, 12, 1.01),
    ],
)
def test_validate_run_params_rejects_nonsense(samples, yaws, threshold):
    with pytest.raises(ValueError):
        validate_run_params(samples=samples, yaws=yaws, threshold=threshold)


def test_gate_qualifying_true_only_at_or_above_gate():
    assert is_gate_qualifying(samples=GATE_MIN_SAMPLES, threshold=GATE_MIN_THRESHOLD)
    assert is_gate_qualifying(samples=50, threshold=0.99)


@pytest.mark.parametrize(
    "samples,threshold",
    [
        (1, 0.0),  # the exact weakened-green case the reviewer flagged
        (1, 0.95),  # too few samples
        (20, 0.0),  # threshold too weak
        (19, 0.95),  # one short of the sample floor
        (20, 0.94),  # just under the threshold floor
    ],
)
def test_gate_qualifying_false_for_weak_params(samples, threshold):
    # These are valid (no raise) but must NOT count as a gate pass.
    validate_run_params(samples=samples, yaws=12, threshold=threshold)
    assert not is_gate_qualifying(samples=samples, threshold=threshold)


# --- output-path resolution (regression: JSON must land at repo root, not cwd) --


def test_resolve_output_anchors_relative_path_to_repo_root(tmp_path):
    # A relative --output resolves against the git repo root, not the caller's cwd,
    # so `ros2 run ... reachability_check` from robot/control still writes the
    # archive to <repo>/docs/evaluation/... (regression for the cwd-relative bug).
    from workbench_motion.reachability_check import _resolve_output_path

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    subdir = repo / "robot" / "control"
    subdir.mkdir(parents=True)

    out = _resolve_output_path("docs/evaluation/phase1-reachability.json", start=subdir)
    assert out == repo / "docs" / "evaluation" / "phase1-reachability.json"


def test_resolve_output_keeps_absolute_path_verbatim(tmp_path):
    from workbench_motion.reachability_check import _resolve_output_path

    abs_target = tmp_path / "somewhere" / "report.json"
    assert _resolve_output_path(str(abs_target), start=tmp_path) == abs_target


def test_resolve_output_falls_back_to_relative_without_git(tmp_path, monkeypatch):
    # No .git anywhere up the tree -> return the relative path unchanged
    # (resolved against cwd by the caller), never crashing. Force every ancestor
    # to look git-less so the test does not depend on the real fs above tmp_path.
    from pathlib import Path as _P

    from workbench_motion import reachability_check as rc

    real_exists = _P.exists
    monkeypatch.setattr(
        rc.Path,
        "exists",
        lambda self: False if self.name == ".git" else real_exists(self),
    )
    out = rc._resolve_output_path("docs/evaluation/phase1-reachability.json", start=tmp_path)
    assert out == Path("docs/evaluation/phase1-reachability.json")
