PYTHON ?= python3
EVAL_PYTHON := .venvs/evaluator/bin/python

.PHONY: setup setup-core demo test cli eval-live
setup:
	$(PYTHON) scripts/setup.py

setup-core:
	$(PYTHON) scripts/setup.py --only core

demo:
	$(EVAL_PYTHON) scripts/demo.py

test:
	$(PYTHON) scripts/test_all.py

cli:
	PYTHONPATH=src $(PYTHON) -m agent_eval_suite.cli $(ARGS)

eval-live:
	$(EVAL_PYTHON) -m agent_eval_suite.cli eval run $(ARGS)

