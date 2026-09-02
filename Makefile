PYTHON ?= python3

.PHONY: bootstrap lint fmt test contract scenario-check golden-check evaluation-check evaluation-scripted context-check \
	dashboard-test dashboard demo demo-scripted demo-offline demo-model model-provision performance-test benchmark-startup \
	benchmark-resources performance-regression-test offline-integration dma-test docs task-check check container-smoke \
	sim sim-doctor sim-list sim-run

bootstrap:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

# Both rules and formatting are gated in CI. Run `make fmt` to fix locally.
lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

fmt:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

test:
	$(PYTHON) -m pytest -v

# Everything CI runs, in one command. Run this before opening a PR.
check: lint test contract scenario-check golden-check context-check demo-scripted demo-offline

contract:
	$(PYTHON) tools/scripts/validate_contracts.py

scenario-check:
	$(PYTHON) tools/scripts/validate_scenarios.py

golden-check:
	$(PYTHON) tools/scripts/validate_golden_set.py

evaluation-check: scenario-check golden-check
	$(PYTHON) -m unittest tests.unit.test_evaluation_tools -v

evaluation-scripted: scenario-check golden-check
	$(PYTHON) tools/scripts/run_evaluation.py --versions v0.2-A,v0.2-B,v0.2-C \
		--scenarios sim/scenarios/frozen/*.json sim/scenarios/expanded/*.json \
		--output-dir runs/nightly-scripted

context-check:
	$(PYTHON) tools/scripts/check_context.py

demo-scripted:
	$(PYTHON) tools/scripts/demo_scripted.py

demo-offline:
	$(PYTHON) tools/scripts/local_runner.py --goal "Place the red block in the tray"

demo: demo-offline

# Simulation control is deliberately truthful: without a configured Gazebo
# adapter, sim-run exits NOT_EXECUTED instead of manufacturing a pass.
sim: sim-run

sim-doctor:
	$(PYTHON) tools/scripts/sim_cli.py doctor

sim-list:
	$(PYTHON) tools/scripts/sim_cli.py list

sim-run:
	$(PYTHON) tools/scripts/sim_cli.py run --all --runner gazebo

demo-model:
	$(PYTHON) tools/scripts/local_runner.py --provider ollama --goal "Sort the parcels already in the intake area"

model-provision:
	docker compose --profile model-bootstrap run --rm model-bootstrap

performance-test:
	$(PYTHON) tools/scripts/demo_scripted.py --iterations 30 --telemetry runs/performance/simulation.jsonl
	$(PYTHON) tools/scripts/analyze_telemetry.py runs/performance/simulation.jsonl --output runs/performance/stages.json

benchmark-startup:
	$(PYTHON) tools/scripts/benchmark_startup.py --output runs/performance/startup.json

benchmark-resources:
	$(PYTHON) tools/scripts/benchmark_resources.py --project workbench-startup-benchmark --output runs/performance/resources.json

performance-regression-test:
	$(PYTHON) -m pytest tests/unit/test_performance_regression.py -v

dashboard-test:
	$(PYTHON) -m unittest tests.unit.test_dashboard_backend -v

offline-integration:
	$(PYTHON) -m pytest tests/integration/test_offline_system.py -v

dma-test:
	$(PYTHON) -m pytest tests/unit/test_dma_contract.py -v

dashboard:
	$(PYTHON) -m workbench_backend.server --host 127.0.0.1 --port 8080

docs:
	$(PYTHON) -m mkdocs build --strict

container-smoke:
	docker build -t workbench-1:smoke .
	docker run --rm workbench-1:smoke python tools/scripts/local_runner.py --goal "Place the red block in the tray"

task-check:
	$(PYTHON) tools/scripts/check_task_packet.py $(PACKET)
