PYTHON ?= python3

.PHONY: bootstrap lint fmt test contract scenario-check golden-check evaluation-check evaluation-scripted context-check \
	dashboard-test dashboard demo-scripted demo-offline task-check check container-smoke

bootstrap:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

fmt:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

test:
	$(PYTHON) -m unittest discover -s tests -p "test_*.py" -v

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

dashboard-test:
	$(PYTHON) -m unittest tests.unit.test_dashboard_backend -v

dashboard:
	$(PYTHON) -m workbench_backend.server --host 127.0.0.1 --port 8080

container-smoke:
	docker build -t workbench-1:smoke .
	docker run --rm workbench-1:smoke python tools/scripts/local_runner.py --goal "Place the red block in the tray"

task-check:
	$(PYTHON) tools/scripts/check_task_packet.py $(PACKET)
