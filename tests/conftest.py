"""
pytest 共享 fixtures,供全部测试使用。
"""
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """临时目录,用完自动清理"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def event_store(temp_dir):
    """临时事件库"""
    from workbench_world_model import SQLiteEventStore

    store = SQLiteEventStore(temp_dir / "test.sqlite")
    yield store
    store.close()


@pytest.fixture
def frozen_scenario():
    """加载第一个冻结场景"""
    from _paths import ROOT

    scenarios = list((ROOT / "sim" / "scenarios" / "frozen").glob("*.json"))
    if not scenarios:
        pytest.skip("No frozen scenarios available")
    return scenarios[0]


@pytest.fixture
def sample_observation():
    """返回一个合法的 Observation 对象"""
    from workbench_contracts import ClockId, Detector, Observation, Orientation, Pose, Position

    return Observation(
        observation_id="test-obs-001",
        run_id="test-run-001",
        entity_id="red_block",
        entity_type="block",
        pose=Pose(
            frame_id="world",
            position=Position(x=0.1, y=0.2, z=0.05),
            orientation=Orientation(x=0.0, y=0.0, z=0.0, w=1.0),
        ),
        confidence=0.98,
        detector=Detector.MOCK,
        observed_at="2026-08-04T10:00:00Z",
        clock_id=ClockId.MONOTONIC,
        evidence_refs=["camera-frame-001"],
    )


@pytest.fixture
def sample_semantic_action():
    """返回一个合法的 SemanticAction 对象"""
    from workbench_contracts import ActionType, SemanticAction

    return SemanticAction(
        action_id="test-action-001",
        action_type=ActionType.GRASP,
        params={"entity_id": "red_block"},
    )
