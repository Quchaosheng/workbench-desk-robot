from _paths import ROOT

REQUIRED_FILES = [
    "AGENTS.md",
    "docs/context/CONTEXT_MANIFEST.md",
    "docs/context/CONSTRAINTS.yaml",
    "docs/context/MODEL_POLICY.yaml",
    "docs/context/GLOSSARY.md",
    "docs/context/EVIDENCE_INDEX.md",
]


def main() -> int:
    missing = [item for item in REQUIRED_FILES if not (ROOT / item).is_file()]
    if missing:
        raise RuntimeError(f"missing required context files: {', '.join(missing)}")
    print("context validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
