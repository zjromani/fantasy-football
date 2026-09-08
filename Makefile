PYTHON := python3
VENV := .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: venv install migrate test lint fmt worker-test verify clean

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.lock

install: venv

migrate:
	$(PY) -m app.cli migrate

test:
	$(VENV)/bin/pytest -q

lint:
	$(VENV)/bin/ruff check app tests
	$(VENV)/bin/ruff format --check app tests

fmt:
	$(VENV)/bin/ruff check app tests --fix
	$(VENV)/bin/ruff format app tests

worker-test:
	node --test worker/test/worker.test.mjs

verify: lint test worker-test

clean:
	rm -rf $(VENV) .pytest_cache auto-gm.sqlite artifacts

