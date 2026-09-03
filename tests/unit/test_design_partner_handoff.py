from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs/product/design-partner-handoff.md"
SCENARIO_TEMPLATE = ROOT / "docs/product/design-partner-scenario-template.md"
PRODUCT_README = ROOT / "docs/product/README.md"
MKDOCS = ROOT / "mkdocs.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").casefold()


def test_handoff_answers_the_required_owner_response_sections() -> None:
    text = _text(HANDOFF)
    required_sections = (
        "## 1. decision vocabulary",
        "## 2. semantic action contract",
        "## 3. motion adapter result boundary",
        "## 4. handoff checklist",
        "## 5. evidence ladder",
        "## 6. abort, stop, recovery, and confirmation authority",
        "## 7. product acceptance versus motion/safety acceptance",
        "## 8. rejected request example",
        "## 9. copyable handoff record",
        "## 10. next step and decision record",
    )
    for section in required_sections:
        assert section in text


def test_handoff_preserves_semantic_and_safety_boundaries() -> None:
    text = _text(HANDOFF)
    required_terms = (
        "continue",
        "change",
        "defer",
        "reject",
        "semantic action",
        "actionresult",
        "worldstate",
        "safe_stop",
        "e-stop",
        "mcu-safety",
        "joint positions",
        "raw can frames",
        "controller goals",
        "safe-enable",
        "does not grant",
        "safety owner must refuse",
    )
    for term in required_terms:
        assert term in text


def test_handoff_keeps_evidence_classes_and_incomplete_statuses_distinct() -> None:
    text = _text(HANDOFF)
    for term in (
        "software",
        "scripted_fixture",
        "gazebo",
        "physical",
        "release_eligible: false",
        "confirmed",
        "failed",
        "refuted",
        "insufficient_evidence",
        "not_executed",
        "blocked",
    ):
        assert term in text


def test_generic_scenario_template_points_to_the_stricter_handoff() -> None:
    template = _text(SCENARIO_TEMPLATE)
    readme = _text(PRODUCT_README)
    mkdocs = _text(MKDOCS)
    assert "design partner handoff boundary" in template
    assert "handoff decision" in template
    assert "design-partner-handoff.md" in readme
    assert "product/design-partner-handoff.md" in mkdocs
