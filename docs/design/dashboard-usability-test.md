# Dashboard usability test

Status: **NOT_EXECUTED**. This protocol is not user feedback, accessibility conformance, or production acceptance.

## Participants and setup

Recruit five people who did not implement the dashboard: at least two robot/operator-domain users and at least one keyboard/screen-reader user. Record consent, assistive technology, viewport/device, task order, and session ID without collecting unnecessary personal data. Use committed synthetic fixtures only.

## Tasks

| Task | Success criterion | Evidence |
|---|---|---|
| find the run needing attention | selects `run-uncertain` without coaching | path, time, wrong turns |
| explain why it is not confirmed | names missing fresh/light/confidence evidence | answer and referenced UI region |
| compare live state with replay start/end | reaches both views and explains changed state | keyboard/pointer path and answer |
| inspect one camera and one action/log reference | opens/closes evidence and identifies synthetic source | reference IDs and observed source label |
| locate the failed first grasp and later recovery | identifies refuted attempt and confirmed conclusion separately | event sequence numbers |
| state what the dashboard cannot control | names read-only/no ROS/no emergency-stop boundary | answer |

## Measures

Record task success, time, errors, assistance, confidence (1-5), and short qualitative observation. Do not combine domain misunderstanding with interface failure without review. A screenshot proves appearance, not comprehension.

## Acceptance and iteration

- all five participants complete attention, evidence, and authority-boundary tasks;
- at least four of five complete replay without assistance;
- no participant interprets insufficient evidence as confirmed completion;
- keyboard/screen-reader path has no blocking issue;
- every high-impact finding receives an owner, issue, acceptance test, and retest result.

Preserve failures. Publish only aggregated, de-identified findings. Mark production usability as UNKNOWN until this protocol is executed and reviewed.

