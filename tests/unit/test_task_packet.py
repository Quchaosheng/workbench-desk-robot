import copy
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "tools/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("check_task_packet", SCRIPTS / "check_task_packet.py")
assert SPEC and SPEC.loader
task_packet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(task_packet)


@pytest.fixture
def valid_packet() -> dict[str, object]:
    return {
        "issue": 106,
        "human_owner": "owner",
        "objective": "Enforce a bounded task.",
        "allowed_paths": ["tools/scripts/check_task_packet.py", "tests/unit/**"],
        "read_only_paths": ["interfaces/**"],
        "forbidden": ["robot/control/**", "firmware/**"],
        "acceptance": ["adversarial tests pass"],
        "commands": ["python -m pytest tests/unit -k task_packet -v"],
        "evidence": ["pytest output"],
        "stop_conditions": ["interface change required"],
    }


def test_valid_packet_passes_schema_boundaries_and_commands(valid_packet: dict[str, object]) -> None:
    task_packet._validate_schema(valid_packet)
    task_packet._validate_boundaries(valid_packet)
    task_packet._validate_commands(valid_packet["commands"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issue", 0),
        ("issue", ""),
        ("human_owner", "   "),
        ("objective", ["not", "a", "scalar"]),
        ("allowed_paths", "tools/**"),
        ("acceptance", [True]),
        ("commands", []),
        ("evidence", {"report": "output"}),
        ("stop_conditions", None),
    ],
)
def test_schema_rejects_malformed_or_empty_fields(valid_packet: dict[str, object], field: str, value: object) -> None:
    payload = copy.deepcopy(valid_packet)
    payload[field] = value
    with pytest.raises(task_packet.TaskPacketError, match="schema validation failed"):
        task_packet._validate_schema(payload)


def test_schema_rejects_missing_and_unknown_fields(valid_packet: dict[str, object]) -> None:
    missing = copy.deepcopy(valid_packet)
    del missing["human_owner"]
    with pytest.raises(task_packet.TaskPacketError, match="human_owner"):
        task_packet._validate_schema(missing)

    extra = copy.deepcopy(valid_packet)
    extra["unapproved_scope"] = ["services/**"]
    with pytest.raises(task_packet.TaskPacketError, match="Additional properties"):
        task_packet._validate_schema(extra)


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "tools/../outside",
        "tools//outside",
        "tools/./outside",
        "/absolute/path",
        "C:/outside",
        "C:\\outside",
        " tools/**",
        "tools/** ",
        "tools/a**/file.py",
    ],
)
def test_path_validation_rejects_escape_and_ambiguous_forms(path: str) -> None:
    with pytest.raises(task_packet.TaskPacketError):
        task_packet._normalize_repo_path(path, field="allowed_paths")


def test_path_validation_rejects_existing_symbolic_link_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    link = tmp_path / "link"
    link.mkdir()
    original_is_symlink = Path.is_symlink

    def pretend_link(path: Path) -> bool:
        return path == link or original_is_symlink(path)

    monkeypatch.setattr(task_packet, "ROOT", tmp_path)
    monkeypatch.setattr(Path, "is_symlink", pretend_link)
    with pytest.raises(task_packet.TaskPacketError, match="symbolic links"):
        task_packet._normalize_repo_path("link/output.json", field="allowed_paths")


def test_path_validation_rejects_link_below_wildcard_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed = tmp_path / "allowed"
    link = allowed / "nested" / "link"
    link.mkdir(parents=True)
    monkeypatch.setattr(task_packet, "ROOT", tmp_path)
    monkeypatch.setattr(task_packet, "_is_link", lambda path: path == link)
    with pytest.raises(task_packet.TaskPacketError, match="wildcard boundary contains a link"):
        task_packet._normalize_repo_path("allowed/**", field="allowed_paths")


@pytest.mark.parametrize(
    ("allowed", "protected"),
    [
        ("interfaces/**", "interfaces/**"),
        ("interfaces/json_schema/file.json", "interfaces/**"),
        ("tests/**", "tests/unit/**"),
        ("tests/*", "tests/unit/**"),
    ],
)
def test_boundary_validation_rejects_unsafe_overlap(
    valid_packet: dict[str, object], allowed: str, protected: str
) -> None:
    payload = copy.deepcopy(valid_packet)
    payload["allowed_paths"] = [allowed]
    payload["forbidden"] = [protected]
    with pytest.raises(task_packet.TaskPacketError, match="boundary overlap"):
        task_packet._validate_boundaries(payload)


def test_read_only_and_forbidden_overlap_is_rejected_as_contradictory(valid_packet: dict[str, object]) -> None:
    payload = copy.deepcopy(valid_packet)
    payload["read_only_paths"] = ["interfaces/**"]
    payload["forbidden"] = ["interfaces/**"]
    with pytest.raises(task_packet.TaskPacketError, match="boundary overlap"):
        task_packet._validate_boundaries(payload)


def test_command_is_data_and_unsafe_multiline_ambiguity_is_reported(valid_packet: dict[str, object]) -> None:
    commands = copy.deepcopy(valid_packet["commands"])
    commands.append("make test\nrm output")
    with pytest.raises(task_packet.TaskPacketError, match="never executed"):
        task_packet._validate_commands(commands)


@pytest.mark.parametrize("command", ["do something", "python -c 'unterminated", " make test"])
def test_command_validation_rejects_arbitrary_or_ambiguous_text(command: str) -> None:
    with pytest.raises(task_packet.TaskPacketError, match="command"):
        task_packet._validate_commands([command])


def test_command_validation_accepts_approved_evidence_wrappers() -> None:
    task_packet._validate_commands(
        [
            "git diff --check",
            "sudo make -C kernel/wbcan test",
            "sudo insmod kernel/wbcan/wbcan.ko fail_debugfs=1",
            "source /opt/ros/jazzy/setup.bash && colcon build",
        ]
    )


def test_validate_packet_reads_a_valid_repository_packet() -> None:
    task_packet.validate_packet(ROOT / "docs/task_packets/example-001-world-reducer.json")


def test_all_mode_validates_each_packet_without_executing_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packet_dir = tmp_path / "packets"
    packet_dir.mkdir()
    for name in ("one.json", "two.json"):
        (packet_dir / name).write_text("{}", encoding="utf-8")
    seen: list[str] = []
    monkeypatch.setattr(task_packet, "PACKET_DIR", packet_dir)
    monkeypatch.setattr(task_packet, "validate_packet", lambda path: seen.append(path.name))
    assert task_packet.main(["--all"]) == 0
    assert seen == ["one.json", "two.json"]


def test_invalid_json_reports_a_validation_error(tmp_path: Path) -> None:
    packet = tmp_path / "bad.json"
    packet.write_text("{", encoding="utf-8")
    with pytest.raises(task_packet.TaskPacketError, match="cannot read JSON"):
        task_packet._load_json(packet)
