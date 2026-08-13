import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PMO = ROOT / "docs" / "project-management"


def test_every_pmo_task_has_a_repository_artifact() -> None:
    index = (PMO / "README.md").read_text(encoding="utf-8")
    for task_number in range(1, 13):
        assert f"PMO{task_number}" in index

    expected = {
        "plan.md",
        "risks.csv",
        "weekly-meeting.md",
        "status.md",
        "risk-management.md",
        "resource-plan.md",
        "monthly-report-template.md",
        "decision-log.md",
        "lessons-learned.md",
        "closeout-template.md",
        "quality-metrics.md",
        "future-work.md",
    }
    assert expected.issubset({path.name for path in PMO.iterdir()})


def test_risk_register_is_actionable_and_fail_closed() -> None:
    with (PMO / "risks.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    required = {
        "id",
        "category",
        "description",
        "probability",
        "impact",
        "owner",
        "trigger",
        "mitigation",
        "contingency",
        "status",
        "next_review",
        "evidence_ref",
    }
    assert rows
    assert set(rows[0]) == required
    assert len({row["id"] for row in rows}) == len(rows)

    for row in rows:
        assert all(row[field].strip() for field in required)
        assert row["probability"] in {"low", "medium", "high"}
        assert row["impact"] in {"low", "medium", "high", "critical"}
        assert row["status"] in {"open", "mitigating", "monitoring", "accepted", "closed"}
        assert row["next_review"].startswith("2026-")

    risk_plan = (PMO / "risk-management.md").read_text(encoding="utf-8")
    critical_open = {row["id"] for row in rows if row["impact"] == "critical" and row["status"] != "closed"}
    assert critical_open.issubset(set(risk_plan.split()))


def test_status_never_substitutes_fixture_results_for_formal_evidence() -> None:
    status = (PMO / "status.md").read_text(encoding="utf-8")
    metrics = (PMO / "quality-metrics.md").read_text(encoding="utf-8")

    assert "UNKNOWN - no formal Gazebo audit" in status
    assert "scripted fixtures are not physics runs" in status
    assert "hardware release blockers | 0 | 12 | RED" in status
    assert "Use `UNKNOWN` when the eligible source is missing" in metrics


def test_merged_dependency_status_does_not_regress_to_pending() -> None:
    status = (PMO / "status.md").read_text(encoding="utf-8")
    risks = (PMO / "risks.csv").read_text(encoding="utf-8")
    risk_plan = (PMO / "risk-management.md").read_text(encoding="utf-8")
    decisions = (PMO / "decision-log.md").read_text(encoding="utf-8")

    assert "fix tracked in PR #21" not in status
    assert "merge and verify the least-privilege SBOM fix" not in status
    assert "deliver the security baseline" not in status
    assert "PR #21 merged" in risks
    assert "merged PR #21" in risk_plan
    assert "merged PR #25" in risk_plan
    assert "implemented in merged PR #21; release verification pending" in decisions
