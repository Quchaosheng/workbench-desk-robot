"""
集成测试:观测 → 规划 → 执行路径
"""

import io
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "tools/scripts"),
    str(ROOT / "libs/contracts"),
    str(ROOT / "services/agent_runtime"),
    str(ROOT / "services/world_model"),
]

import demo_scripted
from workbench_agent_runtime import build_template_plan
from workbench_contracts import VerificationStatus, WorldEvent, WorldEventType
from workbench_world_model import create_world_state_snapshot, reduce_events


def test_observe_to_plan_integration(event_store, sample_observation):
    """
    观测 → 世界状态 → 规划

    步骤:
    1. 收到一个 Observation
    2. WorldState reducer 接收它,更新实体位置
    3. 模板规划器基于目标产出 TaskGraph
    4. TaskGraph 包含合法的 semantic_action
    """
    # 1. 模拟收到观测
    obs_event = WorldEvent(
        event_id="evt-001",
        run_id="integration-test-001",
        sequence_no=1,
        event_type=WorldEventType.OBSERVATION,
        occurred_at="2026-08-04T10:00:00Z",
        payload={
            "observation_id": sample_observation.observation_id,
            "entity_id": sample_observation.entity_id,
            "entity_type": sample_observation.entity_type,
            "location": "on:table",
            "confidence": sample_observation.confidence,
        },
        evidence_refs=sample_observation.evidence_refs,
    )
    event_store.append(obs_event)

    # 2. Reduce 事件流,构建世界状态
    events = event_store.list_run("integration-test-001")
    state = reduce_events("integration-test-001", events)

    # 断言:世界状态包含实体
    assert sample_observation.entity_id in state.entity_locations

    # 3. 产出规划
    plan = build_template_plan("Place the red block in the tray")

    # 断言:规划合法
    assert plan.task_id.startswith("task-")
    assert len(plan.steps) > 0
    assert all(hasattr(step, "action") for step in plan.steps)

    # 断言:能序列化(不抛异常)
    json.loads(plan.model_dump_json())


def test_plan_to_action_integration(sample_semantic_action):
    """
    规划 → 动作执行(占位)

    步骤:
    1. 模板规划器产出 TaskGraph
    2. 第一个 step 的 action 是合法的 SemanticAction
    3. SemanticAction 能序列化并满足 schema

    注意:
        Motion 层尚未实现,这里只测契约一致性
    """
    plan = build_template_plan("Place the red block in the tray")
    first_step = plan.steps[0]

    # 断言:第一步是 observe(模板规划器的固定顺序)
    from workbench_contracts import ActionType

    assert first_step.action.action_type == ActionType.OBSERVE

    # 断言:能序列化
    action_json = first_step.action.model_dump_json()
    parsed = json.loads(action_json)
    assert "action_id" in parsed
    assert "action_type" in parsed


def test_event_replay_integration(event_store):
    """
    事件回放:写入 → 读取 → reduce

    步骤:
    1. 写入 3 个事件
    2. 从事件库读取
    3. reduce 产出 WorldState
    4. 验证 state_hash 存在(一致性检查的基础)
    """
    events = [
        WorldEvent(
            event_id=f"evt-{i:03d}",
            run_id="replay-test-001",
            sequence_no=i,
            event_type=WorldEventType.OBSERVATION,
            occurred_at=f"2026-08-04T10:00:{i:02d}Z",
            payload={
                "entity_id": f"block-{i}",
                "entity_type": "block",
                "location": "on:table",
                "confidence": 0.9,
            },
            evidence_refs=[f"evidence-{i}"],
        )
        for i in range(1, 4)
    ]

    for e in events:
        event_store.append(e)

    # 回放
    replayed = event_store.list_run("replay-test-001")
    assert len(replayed) == 3

    state = reduce_events("replay-test-001", replayed)
    assert state.applied_event_ids == [item.event_id for item in replayed]
    snapshot = create_world_state_snapshot("replay-test-001", replayed)
    assert len(snapshot.state_hash) == 64
    assert snapshot.state_hash.isascii()
    assert snapshot.state_hash.islower()


def test_scripted_demo_requires_post_action_observation(monkeypatch):
    captured = {}
    original_append = demo_scripted.SQLiteEventStore.append
    original_verify = demo_scripted.verify_object_in_tray

    def append_without_post_action_observation(store, item):
        if item.event_id == "evt-004":
            return None
        return original_append(store, item)

    def capture_verification(state, task_id, object_id, tray_id, *, context):
        result = original_verify(state, task_id, object_id, tray_id, context=context)
        captured["context"] = context
        captured["verification"] = result
        return result

    monkeypatch.setattr(
        demo_scripted.SQLiteEventStore,
        "append",
        append_without_post_action_observation,
    )
    monkeypatch.setattr(demo_scripted, "verify_object_in_tray", capture_verification)

    output = demo_scripted.run_once(
        "scripted-without-post-observation",
        demo_scripted.StructuredLogger("scripted-test", io.StringIO()),
    )
    verification = captured["verification"]
    context = captured["context"]

    assert output["verified_complete"] is False
    assert verification.status is VerificationStatus.INSUFFICIENT_EVIDENCE
    assert "action-result-003" not in verification.evidence_refs
    assert context.verified_at != "1970-01-01T00:00:00Z"
    assert context.clock_id.value == "wall"
    assert len(context.state_hash) == 64


def test_scripted_demo_replay_keeps_execution_and_sensor_evidence_separate(monkeypatch):
    captured = {}
    original_reduce = demo_scripted.reduce_events
    original_snapshot = demo_scripted.create_world_state_snapshot
    original_verify = demo_scripted.verify_object_in_tray
    injected_verified_at = "2026-08-27T12:34:56.123456Z"

    def capture_reduction(run_id, events, **kwargs):
        state = original_reduce(run_id, events, **kwargs)
        captured["events"] = events
        captured["state"] = state
        captured["reduction_kwargs"] = kwargs
        return state

    def capture_snapshot(run_id, events, **kwargs):
        snapshot = original_snapshot(run_id, events, **kwargs)
        captured["snapshot_events"] = list(events)
        captured["snapshot"] = snapshot
        captured["snapshot_kwargs"] = kwargs
        return snapshot

    def capture_verification(state, task_id, object_id, tray_id, *, context):
        result = original_verify(state, task_id, object_id, tray_id, context=context)
        captured["context"] = context
        captured["verification"] = result
        return result

    monkeypatch.setattr(demo_scripted, "reduce_events", capture_reduction)
    monkeypatch.setattr(demo_scripted, "create_world_state_snapshot", capture_snapshot)
    monkeypatch.setattr(demo_scripted, "verify_object_in_tray", capture_verification)
    monkeypatch.setattr(demo_scripted, "_utc_wall_clock_now", lambda: injected_verified_at)

    output = demo_scripted.run_once(
        "scripted-with-post-observation",
        demo_scripted.StructuredLogger("scripted-test", io.StringIO()),
    )
    replayed_events = captured["events"]
    state = captured["state"]
    snapshot = captured["snapshot"]
    context = captured["context"]
    verification = captured["verification"]

    assert output["verified_complete"] is True
    assert output["evidence_refs"] == ["camera-frame-004"]
    assert "state_hash" not in output
    assert [item.event_id for item in replayed_events] == [
        "evt-001",
        "evt-002",
        "evt-003",
        "evt-004",
    ]
    assert captured["snapshot_events"] == replayed_events
    assert any(item.event_type is WorldEventType.ACTION_RESULT for item in replayed_events)
    assert "action-result-003" in state.evidence_refs
    assert "action-result-003" not in state.entity_evidence_refs["red_block"]
    assert state.entity_evidence_refs["red_block"] == ["camera-frame-004"]
    assert len(snapshot.state_hash) == 64
    assert snapshot.state_hash.isascii()
    assert snapshot.state_hash.islower()
    assert context.state_hash == snapshot.state_hash
    assert context.verified_at == injected_verified_at
    assert context.clock_id.value == "wall"
    assert verification.verified_at == injected_verified_at


def test_scripted_demo_wall_clock_boundary_is_real_utc():
    verified_at = demo_scripted._utc_wall_clock_now()
    parsed = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))

    assert verified_at != "1970-01-01T00:00:00Z"
    assert parsed.utcoffset() == timedelta(0)


def test_scripted_demo_verification_identity_excludes_wall_time(monkeypatch):
    verified_times = iter(["2026-08-27T12:34:56Z", "2026-08-27T12:35:56Z"])
    verifications = []
    original_verify = demo_scripted.verify_object_in_tray

    def capture_verification(state, task_id, object_id, tray_id, *, context):
        result = original_verify(state, task_id, object_id, tray_id, context=context)
        verifications.append(result)
        return result

    monkeypatch.setattr(demo_scripted, "_utc_wall_clock_now", lambda: next(verified_times))
    monkeypatch.setattr(demo_scripted, "verify_object_in_tray", capture_verification)

    outputs = [
        demo_scripted.run_once(
            "scripted-stable-identity",
            demo_scripted.StructuredLogger("scripted-test", io.StringIO()),
        )
        for _ in range(2)
    ]

    assert all(output["verified_complete"] for output in outputs)
    assert verifications[0].verified_at != verifications[1].verified_at
    assert verifications[0].verification_id == verifications[1].verification_id


def test_scripted_demo_uses_explicit_aging_boundary(monkeypatch):
    captured = {}
    original_reduce = demo_scripted.reduce_events
    original_snapshot = demo_scripted.create_world_state_snapshot
    original_verify = demo_scripted.verify_object_in_tray
    injected_verified_at = "2026-08-28T12:34:56Z"

    def capture_reduction(run_id, events, **kwargs):
        captured["events"] = list(events)
        captured["reduction_kwargs"] = kwargs
        return original_reduce(run_id, events, **kwargs)

    def capture_snapshot(run_id, events, **kwargs):
        captured["snapshot_kwargs"] = kwargs
        return original_snapshot(run_id, events, **kwargs)

    def capture_verification(state, task_id, object_id, tray_id, *, context):
        captured["verification_context"] = context
        return original_verify(state, task_id, object_id, tray_id, context=context)

    monkeypatch.setattr(demo_scripted, "reduce_events", capture_reduction)
    monkeypatch.setattr(demo_scripted, "create_world_state_snapshot", capture_snapshot)
    monkeypatch.setattr(demo_scripted, "verify_object_in_tray", capture_verification)
    monkeypatch.setattr(demo_scripted, "_utc_wall_clock_now", lambda: injected_verified_at)

    output = demo_scripted.run_once(
        "scripted-explicit-aging",
        demo_scripted.StructuredLogger("scripted-test", io.StringIO()),
    )

    reduction_kwargs = captured["reduction_kwargs"]
    snapshot_kwargs = captured["snapshot_kwargs"]
    assert set(reduction_kwargs) == {"freshness_policy", "aging_boundary"}
    assert snapshot_kwargs == reduction_kwargs
    assert reduction_kwargs["freshness_policy"] is demo_scripted.SCRIPTED_FIXTURE_FRESHNESS_POLICY
    assert reduction_kwargs["aging_boundary"] is demo_scripted.SCRIPTED_FIXTURE_AGING_BOUNDARY
    assert reduction_kwargs["aging_boundary"].as_of == "2026-08-04T00:00:02Z"
    assert reduction_kwargs["aging_boundary"].clock_id.value == "wall"
    observations = [item for item in captured["events"] if item.event_type is WorldEventType.OBSERVATION]
    assert observations
    assert all(item.payload["observed_at"].startswith("2026-08-04T00:00:") for item in observations)
    assert all(item.payload["clock_id"] == "wall" for item in observations)
    assert all(item.payload["source"] == "scripted_camera" for item in observations)
    assert captured["verification_context"].verified_at == injected_verified_at
    assert captured["verification_context"].verified_at != reduction_kwargs["aging_boundary"].as_of
    assert output["verified_complete"] is True
