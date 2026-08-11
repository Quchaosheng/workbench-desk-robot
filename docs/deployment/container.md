# Offline container runbook

## Frozen environment

- Ubuntu 24.04 base image;
- Python 3.12 from Ubuntu packages;
- no CUDA or NVIDIA runtime and no model server/network dependency in the default runtime;
- non-root UID `10001`;
- read-only filesystem, dropped Linux capabilities and `no-new-privileges` in Compose.

The build disables the unnecessary Ubuntu backports source, retries transient APT/pip failures, and uses a BuildKit pip cache. GitHub workflows persist pip and image layers between runs.

## Start and verify

```bash
docker compose up --build -d
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/readyz
curl --fail http://127.0.0.1:8080/api/runs
docker compose down
```

`/healthz` means the process can answer requests. `/readyz` additionally means the configured event source contains readable JSON Lines runs.

The image default command starts the read-only dashboard backend. The offline planning path can be checked independently:

```bash
docker run --rm workbench-1:local \
  python tools/scripts/local_runner.py --goal "Place the red block in the tray"
```

The optional local model profile provisions Ollama once and keeps model traffic on an internal Docker network:

```bash
docker compose --profile model-bootstrap run --rm model-bootstrap
docker compose --profile model up -d
docker compose run --rm dashboard python tools/scripts/local_runner.py \
  --provider ollama --endpoint http://model:11434 --allow-host model \
  --goal "Handle the parcels already in the intake area"
```

`model-bootstrap` is the only service attached to the egress-capable bootstrap network. After the model volume is populated,
the `model` and dashboard services use the `internal` runtime network. The template path remains fully usable with no model
image or network.

## Build and provenance

`.github/workflows/release-image.yml` runs `make check`, builds and smoke-tests the image, and emits an SPDX JSON SBOM. Version tags publish to GHCR; manual workflow runs build and validate without creating a release tag.

The SBOM action only writes the local SPDX file. A separate, pinned artifact step retains that file for provenance and review; it does not attach assets to a GitHub Release or require `contents: write`.

Publishing still requires a human-owned version tag and repository permissions. The workflow does not make Go/No-Go decisions and cannot turn scripted evaluation data into release evidence.

## Windows without Make

Run the equivalent checks with the active Python interpreter:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python tools/scripts/validate_contracts.py
python tools/scripts/validate_scenarios.py
python tools/scripts/validate_golden_set.py
python tools/scripts/check_context.py
python tools/scripts/demo_scripted.py
python tools/scripts/local_runner.py --goal "Place the red block in the tray"
```
