import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from integrations.rlsok import RlsokShadowError, RlsokShadowRunner, RlsokShadowUnavailable


def _fake_cli(tmp_path: Path) -> tuple[str, ...]:
    script = tmp_path / "fake_rlsok.py"
    script.write_text(
        """
import json
import sys
from pathlib import Path

command = sys.argv[1]
if command == "shadow":
    proposal = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    hardware_signal_sent = bool(proposal.get("unsafe"))
    evidence_path = Path(sys.argv[4]).resolve()
    bundle = {
        "apiVersion": "realitywarden.io/v1alpha1",
        "kind": "EvidenceBundle",
        "releaseId": "workbench-shadow-001",
        "executablePolicyHash": "a" * 64,
        "createdAt": "2026-09-03T00:00:00Z",
        "entries": [{
            "sequence": 0,
            "previousHash": None,
            "evidence": {
                "decision": "allowed",
                "hardwareSignalSent": hardware_signal_sent,
                "executionEvidence": "shadow_not_dispatched"
            },
            "hash": "b" * 64
        }]
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(bundle), encoding="utf-8")
    print(json.dumps({
        "mode": "standalone",
        "decision": "blocked",
        "reason": "shadow_observation_only:configuration_unbound",
        "controllerGoalsAttempted": 0,
        "hardwareSignalSent": hardware_signal_sent,
        "evidencePath": str(evidence_path)
    }))
elif command == "verify-evidence":
    print("PASS_BOUND_TO_RELEASE")
else:
    raise SystemExit(2)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return sys.executable, str(script)


def _inputs(tmp_path: Path, proposal: dict | None = None) -> tuple[Path, Path, Path]:
    release = tmp_path / "release.shadow.yaml"
    release.write_text("mode: shadow\n", encoding="utf-8")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal or {"proposalId": "p-1"}), encoding="utf-8")
    return release, proposal_path, tmp_path / "evidence" / "bundle.json"


def test_shadow_runner_accepts_blocked_zero_dispatch_result(tmp_path):
    release, proposal, evidence = _inputs(tmp_path)

    result = RlsokShadowRunner(_fake_cli(tmp_path)).run(release, proposal, evidence)

    assert result.decision == "blocked"
    assert result.controller_goals_attempted == 0
    assert result.hardware_signal_sent is False
    assert result.release_id == "workbench-shadow-001"
    assert result.evidence_ref == f"rlsok://evidence/sha256/{result.evidence_sha256}"
    assert result.verification_output == "PASS_BOUND_TO_RELEASE"


def test_shadow_runner_rejects_any_hardware_signal(tmp_path):
    release, proposal, evidence = _inputs(tmp_path, {"unsafe": True})

    with pytest.raises(RlsokShadowError, match="hardware signal"):
        RlsokShadowRunner(_fake_cli(tmp_path)).run(release, proposal, evidence)


def test_shadow_runner_refuses_to_overwrite_evidence(tmp_path):
    release, proposal, evidence = _inputs(tmp_path)
    evidence.parent.mkdir()
    evidence.write_text("preserve", encoding="utf-8")

    with pytest.raises(RlsokShadowError, match="overwrite"):
        RlsokShadowRunner(_fake_cli(tmp_path)).run(release, proposal, evidence)

    assert evidence.read_text(encoding="utf-8") == "preserve"


def test_shadow_runner_reports_missing_command(tmp_path):
    release, proposal, evidence = _inputs(tmp_path)

    with pytest.raises(RlsokShadowUnavailable):
        RlsokShadowRunner((str(tmp_path / "missing-rlsok"),)).run(release, proposal, evidence)
