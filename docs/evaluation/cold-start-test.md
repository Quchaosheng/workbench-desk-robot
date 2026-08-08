# External cold-start protocol

Acceptance requires at least two of three participants to reach a healthy dashboard within 60 minutes from a clean machine.

## Participant records

Copy [`cold-start-results.template.json`](cold-start-results.template.json) to a private evidence file and fill it after each clean-machine run. Validate the completed file with:

```bash
python tools/scripts/validate_cold_start.py runs/evaluation/cold-start-results.json
```

The command intentionally fails until at least two of three real participants pass. The checked-in template is not evidence.

| Field | Value |
|---|---|
| Participant ID | |
| OS and version | |
| CPU / memory | |
| Docker version | |
| Started at | |
| First `/healthz` 200 at | |
| First `/readyz` 200 at | |
| Elapsed minutes | |
| Result | pass / fail |
| Blocking log reference | |

## Path under test

```bash
git clone https://github.com/Quchaosheng/workbench-desk-robot.git
cd workbench-desk-robot
docker compose up --build -d
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/readyz
```

Do not preinstall repository dependencies, reuse a prior image, or help the participant beyond the public README. Keep failures; they are release evidence, not scores to clean up.
