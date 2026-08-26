import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"


def _job_block(workflow: str, job_name: str, next_job: str | None = None) -> str:
    start = workflow.index(f"  {job_name}:\n")
    if next_job is None:
        return workflow[start:]
    end = workflow.index(f"  {next_job}:\n", start)
    return workflow[start:end]


def test_security_workflow_is_pinned_and_least_privileged() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    header = workflow.split("jobs:", maxsplit=1)[0]
    assert "permissions:\n  contents: read" in header
    assert "security-events: write" not in header

    action_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]
    assert action_lines
    assert all(re.search(r"@[0-9a-f]{40}\s+# v[0-9]", line) for line in action_lines)

    codeql = _job_block(workflow, "codeql-python", "codeql-c-cpp")
    assert "security-events: write" in codeql
    assert "build-mode: none" in codeql

    codeql_c_cpp = _job_block(workflow, "codeql-c-cpp", "dependency-review")
    assert "security-events: write" in codeql_c_cpp
    assert "packages: read" not in codeql_c_cpp
    assert "languages: c-cpp" in codeql_c_cpp
    assert "build-mode: manual" in codeql_c_cpp
    assert 'make -C kernel/wbcan KDIR="$kernel_headers"' in codeql_c_cpp
    assert "make -C firmware/mcu host" in codeql_c_cpp
    assert "make -C firmware/mcu qemu" in codeql_c_cpp
    assert "category: /language:c-cpp" in codeql_c_cpp
    assert "continue-on-error: true" not in codeql_c_cpp

    dependency_review = _job_block(workflow, "dependency-review")
    assert "if: github.event_name == 'pull_request'" in dependency_review
    assert "security-events: write" not in dependency_review
    assert "fail-on-severity: high" in dependency_review


def test_dependabot_covers_python_actions_and_container_inputs() -> None:
    config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    ecosystems = re.findall(r"package-ecosystem: ([a-z-]+)", config)
    assert ecosystems.count("pip") == 2
    assert ecosystems.count("github-actions") == 1
    assert ecosystems.count("docker") == 2
    assert "directory: /robot/control" in config
    assert "directory: /.devcontainer" in config


def test_security_handbook_preserves_unexecuted_and_not_certified_states() -> None:
    index = (ROOT / "docs" / "security" / "README.md").read_text(encoding="utf-8")
    for task_number in range(1, 9):
        assert f"SEC{task_number}" in index

    penetration_plan = (ROOT / "docs" / "security" / "penetration-test-plan.md").read_text(encoding="utf-8")
    compliance = (ROOT / "docs" / "security" / "compliance-matrix.md").read_text(encoding="utf-8")
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "Status: **NOT_EXECUTED**" in penetration_plan
    assert "not a legal opinion, audit, certification" in compliance
    assert "/security/advisories/new" in policy
    assert "Do not report vulnerabilities" in policy
