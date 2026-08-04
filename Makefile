PYTHON ?= python3

.PHONY: bootstrap test contract scenario-check context-check demo-scripted task-check

bootstrap:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m unittest discover -s tests -p "test_*.py" -v

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
