# External cold-start protocol

Acceptance requires at least two of three participants to reach a healthy dashboard within 60 minutes from a clean machine.

## Participant record

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
