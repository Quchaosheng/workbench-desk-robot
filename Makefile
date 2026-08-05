PYTHON ?= python3

.PHONY: bootstrap lint fmt test contract scenario-check context-check demo-scripted task-check check

bootstrap:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check .

fmt:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

test:
	$(PYTHON) -m pytest tests/ -v

# Everything CI runs, in one command. Run this before opening a PR.
check: lint test contract scenario-check context-check demo-scripted

contract:
	$(PYTHON) tools/scripts/validate_contracts.py

scenario-check:
	$(PYTHON) tools/scripts/validate_scenarios.py

context-check:
	$(PYTHON) tools/scripts/check_context.py

demo-scripted:
	$(PYTHON) tools/scripts/demo_scripted.py

task-check:
	$(PYTHON) tools/scripts/check_task_packet.py $(PACKET)
