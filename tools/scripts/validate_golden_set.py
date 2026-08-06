import json

from _paths import ROOT


def validate(payload: dict) -> list[str]:
    problems: list[str] = []
    tasks = payload.get("tasks", [])
    dangerous = payload.get("dangerous_requests", [])
    if payload.get("frozen") is not True:
        problems.append("golden set must be frozen")
    if len(tasks) != 20:
        problems.append(f"expected 20 tasks, found {len(tasks)}")
    if len(dangerous) != 10:
        problems.append(f"expected 10 dangerous requests, found {len(dangerous)}")
    identifiers = [item.get("id") for item in tasks + dangerous]
    if len(identifiers) != len(set(identifiers)):
        problems.append("task and dangerous-request IDs must be unique")
    if any(item.get("expected_task_id") != "task-place-red-block" for item in tasks):
        problems.append("all P1 tasks must map to the frozen pick/place task")
    if any(item.get("expected_policy") != "reject" for item in dangerous):
        problems.append("every dangerous request must fail closed")
    if any(not item.get("request", "").strip() for item in tasks + dangerous):
        problems.append("every entry must contain a non-empty request")
    return problems


def main() -> int:
    path = ROOT / "evaluation" / "golden-set-v0.1.json"
    problems = validate(json.loads(path.read_text(encoding="utf-8")))
    if problems:
        raise RuntimeError("; ".join(problems))
    print("golden set validation passed for 20 tasks and 10 dangerous requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
