PYTHON ?= python3

.PHONY: bootstrap lint fmt test contract scenario-check context-check demo-scripted task-check check

bootstrap:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

# Formatting is not gated yet: the tree has never been formatted, so gating it
# now would fail every PR until one large reformat lands. Run `make fmt`, review
# the diff, commit it, then add `ruff format --check .` to this target.
lint:
	$(PYTHON) -m ruff check .

fmt:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

test:
	$(PYTHON) -m unittest discover -s tests -p "test_*.py" -v

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
