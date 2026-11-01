PYTHON ?= python3
EVAL_PYTHON ?= .venvs/evaluator/bin/python
BENCHMARK_OUTPUT ?= artifacts/benchmark-demo
BENCHMARK_CONFIG ?=

.PHONY: setup setup-core demo legacy-demo benchmark-live test cli eval-live
setup:
	$(PYTHON) scripts/setup.py

setup-core:
	$(PYTHON) scripts/setup.py --only core

demo:
	$(EVAL_PYTHON) -m agent_eval_suite.cli --evaluator-python "$(EVAL_PYTHON)" benchmark demo --limit 5 --split dev --output "$(BENCHMARK_OUTPUT)"
	$(EVAL_PYTHON) -m agent_eval_suite.cli --evaluator-python "$(EVAL_PYTHON)" benchmark report --run "$(BENCHMARK_OUTPUT)"

legacy-demo:
	$(EVAL_PYTHON) scripts/demo.py

benchmark-live:
	@test -n "$(BENCHMARK_CONFIG)" || { echo 'Set BENCHMARK_CONFIG to your local nanobot configuration JSON.'; exit 2; }
	$(EVAL_PYTHON) -m agent_eval_suite.cli --evaluator-python "$(EVAL_PYTHON)" benchmark run --config "$(BENCHMARK_CONFIG)" $(ARGS)

test:
	$(PYTHON) scripts/test_all.py

cli:
	PYTHONPATH=src $(PYTHON) -m agent_eval_suite.cli $(ARGS)

eval-live:
	@echo 'Legacy compatibility entry: new task benchmarks use make benchmark-live.'
	$(EVAL_PYTHON) -m agent_eval_suite.cli --evaluator-python "$(EVAL_PYTHON)" eval run $(ARGS)
