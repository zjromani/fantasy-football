PYTHON := python3
VENV := .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: venv install run test lint fmt clean

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install: venv

run:
	$(VENV)/bin/uvicorn app.main:app --reload

test:
	PYTHONPATH=$(PWD) $(VENV)/bin/pytest -q

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/black --check .

fmt:
	$(VENV)/bin/black .

clean:
	rm -rf $(VENV) __pycache__ **/__pycache__ .pytest_cache app.db

